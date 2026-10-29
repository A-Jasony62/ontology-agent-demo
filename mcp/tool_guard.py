"""Agent 调用护栏：预算熔断 + 循环拦截 + 缓存复用 + 审计留痕（MCP 出口层，与任何领域无关）。

设计（Agentic RAG 防失控共识「四道工事」的工程化落地，读侧运行时防护）：
  - 会话预算（session_budget）：单次 MCP 会话内工具执行次数上限，超限熔断——
    不是报错崩掉，而是返回结构化提示（含已用次数与调整指引）；缓存命中不消耗预算；
  - 循环检测（loop_threshold）：同一工具 + 同一参数连续调用达到阈值 → 判定
    Agent 打转，拦截并提示换路；
  - 结果缓存复用（cache.ttl_calls）：同工具同参数的最近结果直接返回
    （_guard.cached=true），以「调用次数」计 TTL（MCP 无挂钟语义，调用计数
    比时间戳更适合会话内缓存）；
  - 调用审计（audit_tail）：何时、调了什么、参数、结果状态与耗时——环形缓冲
    只留最近 N 条，防内存膨胀（guard_status 在线可查，「每次调用有账可查」）；
  - **默认关闭**：无配置文件 / enabled=false 时出口层零开销直通原逻辑，
    逐字节兼容（对齐 policy.py 向后兼容硬标准）。

与 mcp/policy.py 正交互补：policy 管「能不能调」（权限闸、语义白名单），
本模块管「调多少次」（预算闸、过程防护）——外防越权 × 内防失控双防线。

配置文件放领域包 `domains/<name>/guard_config.json`（随领域走）；本模块无领域知识。
计数语义（MVP）：进程级计数（MCP stdio 单进程单会话即等价）；`session_id`
预留给多会话网关场景。
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import os
import time
from collections import deque

# None = 按运行态配置解析 root；测试可显式赋值为具体目录
_DOMAINS_DIR: str | None = None


def _domains_dir() -> str:
    """领域包根目录：优先显式覆盖，否则取运行态配置。"""
    if _DOMAINS_DIR:
        return _DOMAINS_DIR
    try:
        from config import load_config

        return str(load_config().root)
    except Exception:  # noqa: BLE001
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "domains")


class ToolGuard:
    """调用护栏（从领域包 guard_config.json 加载；enabled 为显式开关）。

    配置约定（全部数值在加载时 fail-fast 校验，非法值直接抛 ValueError）：
        enabled         是否启用（出厂 false）
        session_budget  会话内工具执行次数上限（正整数）
        loop_threshold  连续同参调用拦截阈值（>= 2，1 次就拦没有意义）
        cache.enabled   结果缓存开关（默认 false，时敏查询可关）
        cache.ttl_calls 缓存有效期（写入后允许命中的查询次数，>= 1）
        audit_tail      审计环形缓冲容量（>= 1）
    """

    def __init__(self, config: dict | None = None):
        cfg = dict(config or {})
        self.enabled = bool(cfg.get("enabled", False))
        b = cfg.get("session_budget", 50)
        if not isinstance(b, int) or isinstance(b, bool) or b <= 0:
            raise ValueError(f"session_budget 必须为正整数，当前：{b!r}")
        self.session_budget = b
        lt = cfg.get("loop_threshold", 3)
        if not isinstance(lt, int) or isinstance(lt, bool) or lt < 2:
            raise ValueError(f"loop_threshold 必须为 >= 2 的整数，当前：{lt!r}")
        self.loop_threshold = lt
        cache_cfg = cfg.get("cache") or {}
        if not isinstance(cache_cfg, dict):
            raise ValueError(f"cache 应为 JSON 对象，当前：{cache_cfg!r}")
        self.cache_enabled = bool(cache_cfg.get("enabled", False))
        ttl = cache_cfg.get("ttl_calls", 5)
        if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl < 1:
            raise ValueError(f"cache.ttl_calls 必须为 >= 1 的整数，当前：{ttl!r}")
        self.ttl_calls = ttl
        tail = cfg.get("audit_tail", 100)
        if not isinstance(tail, int) or isinstance(tail, bool) or tail < 1:
            raise ValueError(f"audit_tail 必须为 >= 1 的整数，当前：{tail!r}")
        self.audit_tail = tail

        # 运行态
        self.calls_used = 0            # 真实执行次数（缓存命中不计）
        self.cache_hits = 0
        self._cache: dict = {}         # (tool, params_hash) -> (result, remaining_hits)
        self._last_key: tuple | None = None  # 最近一次调用的 (tool, params_hash)
        self._repeat = 0               # 最近键的连续重复次数
        self._audit_log: deque = deque(maxlen=self.audit_tail)  # 环形缓冲（内存有界）

    # ---------------- 包装与执行 ----------------

    def wrap_tool(self, tool_name: str, fn):
        """返回包装后的工具函数（保留原签名与文档；关闭态不调用本方法）。"""
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return self.call(tool_name, fn, args, kwargs)
        return wrapper

    def call(self, tool_name: str, fn, args=(), kwargs=None):
        """执行一次受护栏保护的工具调用（预算 → 循环 → 缓存 → 执行 → 元数据）。"""
        kwargs = kwargs or {}
        params_hash = self._hash(args, kwargs)
        key = (tool_name, params_hash)

        # ① 预算熔断：真实执行次数达上限 → 结构化提示（不崩、不静默）
        if self.calls_used >= self.session_budget:
            self._audit(tool_name, params_hash, "blocked", 0.0, rule="session_budget")
            return {
                "error": "budget_exceeded",
                "guard": {
                    "rule": "session_budget",
                    "calls_used": self.calls_used,
                    "budget": self.session_budget,
                    "hint": (f"本会话调用预算已用尽（{self.calls_used}/{self.session_budget}）；"
                             "如需继续请开启新会话或调整 guard_config.json 的 session_budget"),
                },
            }

        # ② 循环检测：连续同工具同参数达到阈值 → 判定打转，拦截并提示换路
        self._repeat = self._repeat + 1 if key == self._last_key else 1
        self._last_key = key
        if self._repeat >= self.loop_threshold:
            self._audit(tool_name, params_hash, "blocked", 0.0, rule="loop_threshold")
            return {
                "error": "loop_detected",
                "guard": {
                    "rule": "loop_threshold",
                    "repeated": self._repeat,
                    "threshold": self.loop_threshold,
                    "tool": tool_name,
                    "hint": (f"同一工具同参数已连续调用 {self._repeat} 次（阈值 {self.loop_threshold}），"
                             "疑似循环打转；请更换参数、换一个工具，或换一条解决思路"),
                },
            }

        # ③ 缓存命中：TTL 内直接返回（不消耗执行预算）
        if self.cache_enabled:
            hit = self._cache.get(key)
            if hit is not None:
                result, remaining = hit
                if remaining > 0:
                    self._cache[key] = (result, remaining - 1)
                    self.cache_hits += 1
                    self._audit(tool_name, params_hash, "cached", 0.0)
                    out = copy.deepcopy(result)
                    return self._tag(out, cached=True)
                del self._cache[key]  # 过期：不返回陈旧结果

        # ④ 执行原工具（含异常路径：审计记 error 后如实传播，不吞）
        start = time.time()
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            self.calls_used += 1
            self._audit(tool_name, params_hash, "error",
                        round((time.time() - start) * 1000, 2), error=str(exc))
            raise
        duration_ms = round((time.time() - start) * 1000, 2)
        self.calls_used += 1
        self._audit(tool_name, params_hash, "ok", duration_ms)
        if self.cache_enabled and isinstance(result, dict):
            # 缓存干净副本（不含 _guard 元数据，命中时重新标注）
            self._cache[key] = (copy.deepcopy(result), max(self.ttl_calls - 1, 0))
        # ⑤ 附加 _guard 元数据（仅护栏启用时；声明为非契约字段）
        return self._tag(result, cached=False)

    # ---------------- 状态查询 ----------------

    def status(self) -> dict:
        """护栏状态：预算用量 / 循环 / 缓存命中 / 最近审计尾部（自身不被 wrap，不会熔断）。"""
        return {
            "enabled": self.enabled,
            "budget": {"used": self.calls_used, "limit": self.session_budget,
                       "remaining": self.session_budget - self.calls_used},
            "loop": {"threshold": self.loop_threshold, "current_repeat": self._repeat},
            "cache": {"enabled": self.cache_enabled, "ttl_calls": self.ttl_calls,
                      "hits": self.cache_hits, "entries": len(self._cache)},
            "audit_tail": self.audit_tail,
            "recent_audit": list(self._audit_log),
        }

    # ---------------- 内部 ----------------

    @staticmethod
    def _hash(args, kwargs) -> str:
        """参数指纹（排序 + 稳定序列化 → sha1 短哈希，审计不落明文参数）。"""
        payload = json.dumps({"args": list(args), "kwargs": kwargs},
                             sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    def _tag(self, result, cached: bool):
        """附加 _guard 元数据（_ 前缀声明为非契约字段；关闭态完全不经过本函数）。"""
        if isinstance(result, dict):
            out = dict(result)
            out["_guard"] = {"calls_used": self.calls_used, "cached": cached}
            return out
        return result

    def _audit(self, tool: str, params_hash: str, outcome: str,
               duration_ms: float = 0.0, **extra) -> None:
        self._audit_log.append({
            "ts": round(time.time(), 3),
            "tool": tool,
            "params": params_hash,
            "outcome": outcome,   # ok / cached / blocked / error
            "duration_ms": duration_ms,
            **extra,
        })


def load_guard_config(domain_name: str) -> ToolGuard | None:
    """从领域包加载 guard_config.json；文件不存在返回 None（护栏关闭、逐字节兼容）。

    JSON 损坏或数值非法 → fail-fast 抛 ValueError（指明文件），不静默降级。
    """
    path = os.path.join(_domains_dir(), domain_name, "guard_config.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"guard_config.json 解析失败（{path}）：{exc}") from exc
    if not isinstance(cfg, dict):
        raise ValueError(f"guard_config.json 应为 JSON 对象（{path}）")
    try:
        return ToolGuard(cfg)
    except ValueError as exc:
        raise ValueError(f"guard_config.json 配置非法（{path}）：{exc}") from exc


def wrap_server_tool(server, guard):
    """返回工具注册装饰器：guard 启用时统一 wrap（否则原样注册、逐字节兼容）。

    用法（对齐 mcp_server._register_generic_tools）：
        tool = wrap_server_tool(server, guard)
        @tool(description="…")
        def my_tool(x): …
    guard_status 等自省工具应用裸 @server.tool 注册（自省不应被预算熔断）。
    """
    active = guard is not None and guard.enabled

    def tool(description=None, **kw):
        def deco(fn):
            if not active:
                return server.tool(description=description, **kw)(fn)
            wrapper = guard.wrap_tool(fn.__name__, fn)
            return server.tool(description=description, **kw)(wrapper)
        return deco

    return tool
