"""Agent 调用护栏（mcp/tool_guard.py）测试：预算 / 循环 / 缓存 / 审计 + 默认关闭兼容。

覆盖：
  - 正例：预算熔断含用量提示、缓存命中 cached=true 结果一致、循环拦截换路提示、
    guard_status 审计 outcome 正确分类（ok/cached/blocked）、注册管道全工具 wrap
  - 反例：未配置 / enabled=false 时注册器原样注册不包装（默认关闭、逐字节兼容）
  - 边界：非法配置 fail-fast、审计环形缓冲有界、ttl_calls 过期重执行、
    关闭态 guard_status 如实 enabled=false
"""

import importlib.util
import json
import os

import pytest

from reasoner.engine import ONTO_PATH, OntologyEngine

_GUARD_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp", "tool_guard.py")
_spec = importlib.util.spec_from_file_location("_mcp_tool_guard_test", _GUARD_PATH)
tool_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool_guard)

# mcp_server 模块（同样绕过 mcp/ 目录与 pip SDK 同名的遮蔽问题）
_SERVER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp", "mcp_server.py")
_server_spec = importlib.util.spec_from_file_location("_mcp_server_guard_test", _SERVER_PATH)
mcp_server = importlib.util.module_from_spec(_server_spec)
_server_spec.loader.exec_module(mcp_server)


def _guard(**over) -> "tool_guard.ToolGuard":
    cfg = {"enabled": True, "session_budget": 50, "loop_threshold": 3,
           "cache": {"enabled": False, "ttl_calls": 5}, "audit_tail": 100}
    cfg.update(over)
    return tool_guard.ToolGuard(cfg)


def _counter_fn():
    """带执行计数器的被护函数（返回 dict，记录真实执行次数）。"""
    state = {"n": 0}

    def fn(x: int = 0) -> dict:
        state["n"] += 1
        return {"value": x, "runs": state["n"]}
    return fn


class FakeServer:
    """模拟 MCPServer：记录注册 (工具名 → 函数)。"""

    def __init__(self):
        self.tools = {}

    def tool(self, description=None):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


# ---------------- 正例 ----------------

def test_budget_exceeded_blocks_with_usage_hint():
    """正例①：budget=3 连调 4 次 → 第 4 次熔断，含 calls_used/budget/hint。"""
    g = _guard(session_budget=3, loop_threshold=99)
    fn = _counter_fn()
    for _ in range(3):
        r = g.call("t", fn, (1,), {})
        assert r["value"] == 1
    r4 = g.call("t", fn, (1,), {})
    assert r4["error"] == "budget_exceeded"
    assert r4["guard"]["rule"] == "session_budget"
    assert r4["guard"]["calls_used"] == 3 and r4["guard"]["budget"] == 3
    assert "hint" in r4["guard"]


def test_cache_hit_returns_identical_result_without_rerun():
    """正例②：同参连续调用 2 次（阈值 3 内）→ 第 2 次 _guard.cached=true 且结果一致。"""
    g = _guard(loop_threshold=5, cache={"enabled": True, "ttl_calls": 5})
    fn = _counter_fn()
    r1 = g.call("t", fn, (7,), {})
    r2 = g.call("t", fn, (7,), {})
    assert r1["_guard"]["cached"] is False
    assert r2["_guard"]["cached"] is True
    assert r2["runs"] == 1          # 未重新执行
    assert r1["value"] == r2["value"] == 7
    assert g.cache_hits == 1
    assert g.calls_used == 1        # 缓存命中不消耗预算
    outcomes = [a["outcome"] for a in g.status()["recent_audit"]]
    assert "cached" in outcomes     # 审计 outcome 含 cached 分类


def test_loop_detected_blocks_and_suggests_alternative():
    """正例③：同参调用达到 loop_threshold → 拦截并提示换路。"""
    g = _guard(loop_threshold=3, cache={"enabled": False})
    fn = _counter_fn()
    r1 = g.call("t", fn, (1,), {})
    r2 = g.call("t", fn, (1,), {})
    r3 = g.call("t", fn, (1,), {})
    assert r1.get("error") != "loop_detected" and r2.get("error") != "loop_detected"
    assert r3["error"] == "loop_detected"
    assert r3["guard"]["rule"] == "loop_threshold"
    assert r3["guard"]["repeated"] == 3
    assert "换" in r3["guard"]["hint"]  # 提示换路


def test_guard_status_audit_outcome_classification():
    """正例④：guard_status 审计尾部含全部调用记录，outcome/规则正确分类。"""
    g = _guard(session_budget=5, loop_threshold=3, cache={"enabled": False})
    fn = _counter_fn()
    g.call("t", fn, (1,), {})   # ok（repeat=1）
    g.call("t", fn, (1,), {})   # ok（repeat=2）
    g.call("t", fn, (1,), {})   # blocked：loop_threshold（连续同参第 3 次）
    g.call("t", fn, (2,), {})   # ok（不同参数，循环计数重置）
    g.call("t", fn, (3,), {})   # ok
    st = g.status()
    assert st["enabled"] is True
    outcomes = [a["outcome"] for a in st["recent_audit"]]
    assert outcomes == ["ok", "ok", "blocked", "ok", "ok"]
    rules = [a.get("rule") for a in st["recent_audit"]]
    assert rules[2] == "loop_threshold"
    assert st["budget"]["used"] == 4 and st["budget"]["limit"] == 5


def test_register_generic_tools_wraps_all_when_guard_on():
    """正例⑤：护栏启用时全部通用工具被 wrap（返回带 _guard），guard_status 不被 wrap。"""
    server = FakeServer()
    engine = OntologyEngine(ONTO_PATH)
    g = _guard()
    mcp_server._register_generic_tools(server, lambda: engine, None, g)
    # 工具集齐全（10 通用 + guard_status）
    expected = {"query_sparql", "individuals", "classes", "types_of",
                "property_values", "infer", "explain_proof", "predefined_queries",
                "run_predefined_query", "active_facts", "guard_status"}
    assert expected <= set(server.tools)
    # 通用工具调用带 _guard（被 wrap）；guard_status 不带（自省不熔断）
    r = server.tools["individuals"]("Agent")
    assert "_guard" in r
    st = server.tools["guard_status"]()
    assert "_guard" not in st and st["enabled"] is True


def test_budget_blocks_through_registered_pipeline():
    """正例⑥（管线级）：budget=3 → 第 4 次调用熔断（注册管道生效）。"""
    server = FakeServer()
    engine = OntologyEngine(ONTO_PATH)
    g = _guard(session_budget=3, loop_threshold=99, cache={"enabled": False})
    mcp_server._register_generic_tools(server, lambda: engine, None, g)
    individuals = server.tools["individuals"]
    for i in range(3):
        assert "error" not in individuals("Agent")
    r4 = individuals("Agent")
    assert r4["error"] == "budget_exceeded"


# ---------------- 反例（默认关闭、逐字节兼容） ----------------

def test_disabled_guard_registers_raw_functions():
    """反例：guard=None / enabled=false 时注册原函数（不带 _guard、零包装）。"""
    server = FakeServer()
    engine = OntologyEngine(ONTO_PATH)
    # guard=None
    mcp_server._register_generic_tools(server, lambda: engine, None, None)
    r = server.tools["classes"]()
    assert "_guard" not in r
    # enabled=false
    server2 = FakeServer()
    g_off = tool_guard.ToolGuard({"enabled": False})
    mcp_server._register_generic_tools(server2, lambda: engine, None, g_off)
    r2 = server2.tools["classes"]()
    assert "_guard" not in r2
    # 关闭态 guard_status 如实返回 enabled=false（不报错）
    st = server2.tools["guard_status"]()
    assert st["enabled"] is False


def test_wrap_server_tool_off_returns_same_function():
    """反例：关闭态 wrap_server_tool 注册并返回原函数（逐字节兼容的装配证明）。

    注意不使用装饰器语法（@tool_on 会把返回的 wrapper 重新绑定到函数名），
    手动应用装饰器以比较对象身份。
    """
    server = FakeServer()
    tool_off = tool_guard.wrap_server_tool(server, None)
    tool_on = tool_guard.wrap_server_tool(server, _guard())

    def fn_raw(x: int) -> dict:
        return {"x": x}

    reg_off = tool_off(description="off")(fn_raw)
    reg_on = tool_on(description="on")(fn_raw)

    assert reg_off is fn_raw                 # 关闭态：原函数原样返回
    assert reg_on is not fn_raw              # 启用态：返回包装器
    assert server.tools["fn_raw"] is reg_on  # 注册的也是包装器
    assert reg_on(1)["_guard"]["cached"] is False
    assert reg_on(1)["x"] == 1


# ---------------- 边界 ----------------

@pytest.mark.parametrize("bad", [
    {"enabled": True, "session_budget": 0},
    {"enabled": True, "session_budget": -5},
    {"enabled": True, "session_budget": "many"},
    {"enabled": True, "loop_threshold": 1},
    {"enabled": True, "cache": {"ttl_calls": 0}},
    {"enabled": True, "audit_tail": -1},
])
def test_invalid_config_fails_fast(bad):
    """边界①：非法配置（budget=0/负数/非数值、threshold<2、ttl<=0、tail<1）→ ValueError。"""
    with pytest.raises(ValueError):
        tool_guard.ToolGuard(bad)


def test_audit_ring_buffer_bounded():
    """边界②：audit_tail=3 跑 5 次调用 → 审计只保留最近 3 条。"""
    g = _guard(audit_tail=3, loop_threshold=99)
    fn = _counter_fn()
    for i in range(5):
        g.call("t", fn, (i,), {})
    st = g.status()
    assert len(st["recent_audit"]) == 3


def test_cache_ttl_expires_and_reruns():
    """边界③：ttl_calls=2 → 第 2 次命中缓存、第 3 次过期重新执行。"""
    g = _guard(loop_threshold=99, cache={"enabled": True, "ttl_calls": 2})
    fn = _counter_fn()
    r1 = g.call("t", fn, (1,), {})   # 执行（runs=1），写缓存 remaining=1
    r2 = g.call("t", fn, (1,), {})   # 命中（remaining 1→0）
    r3 = g.call("t", fn, (1,), {})   # 过期 → 重新执行（runs=2）
    assert r1["_guard"]["cached"] is False
    assert r2["_guard"]["cached"] is True
    assert r3["_guard"]["cached"] is False
    assert r3["runs"] == 2 and g.calls_used == 2


# ---------------- load_guard_config ----------------

def test_load_guard_config_missing_file_returns_none():
    """边界④：无 guard_config.json → None（护栏关闭、逐字节兼容）。"""
    assert tool_guard.load_guard_config("non_existent_domain") is None


def test_load_guard_config_factory_default_disabled():
    """出厂示例（agent_task）加载成功且 enabled=false（默认关闭）。"""
    g = tool_guard.load_guard_config("agent_task")
    assert g is not None and g.enabled is False


def test_load_guard_config_broken_json_fails_fast(tmp_path, monkeypatch):
    """边界⑤：JSON 损坏 / 数值非法 → fail-fast ValueError（不静默降级成无护栏）。"""
    d = tmp_path / "domains" / "foo"
    d.mkdir(parents=True)
    (d / "guard_config.json").write_text("{ broken json", encoding="utf-8")
    monkeypatch.setattr(tool_guard, "_DOMAINS_DIR", str(tmp_path / "domains"))
    with pytest.raises(ValueError):
        tool_guard.load_guard_config("foo")
    (d / "guard_config.json").write_text(
        json.dumps({"enabled": True, "session_budget": 0}), encoding="utf-8")
    with pytest.raises(ValueError):
        tool_guard.load_guard_config("foo")
