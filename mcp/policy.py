"""受控语义接口：语义白名单 + 预定义查询（MCP 出口层门禁，与任何领域无关）。

设计（Ontop 语义白名单 + 预定义查询端点的落地）：
  - 白名单：只暴露「允许的类 / 谓词」，白名单外查询被拒并返回诚实提示；
  - 预定义查询：受控查询模板（{{param}} 占位），Agent 只能按名调用，渲染结果再复核谓词白名单；
  - **默认关闭**：无策略文件（SemanticPolicy 为 None）时出口层零开销直通原逻辑，逐字节兼容。

策略文件放领域包 `<运行态 root>/<name>/access_policy.json`（随领域走，
root 由 config 决定，默认 `domains/`、示例在 `examples/`）；本模块无领域知识。
"""

from __future__ import annotations

import json
import os
import re

from rdflib import URIRef, RDFS

# None = 按运行态配置解析 root；测试可显式赋值为具体目录
_DOMAINS_DIR: str | None = None


def _domains_dir() -> str:
    """领域包根目录：优先显式覆盖，否则取运行态配置（root 可被配置/环境变量改）。"""
    if _DOMAINS_DIR:
        return _DOMAINS_DIR
    try:
        from config import load_config

        return str(load_config().root)
    except Exception:  # noqa: BLE001 —— 配置不可用时退回历史位置，保持可诊断
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "domains"
        )


def _short(iri) -> str:
    s = str(iri)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


class SemanticPolicy:
    """语义白名单 + 预定义查询策略（从领域包 access_policy.json 加载）。"""

    def __init__(self, config: dict):
        self.allowed_classes = set(config.get("allowed_classes") or [])
        self.allowed_predicates = set(config.get("allowed_predicates") or [])
        self.predefined_queries = config.get("predefined_queries") or {}

    @property
    def enabled(self) -> bool:
        """是否有任何受控配置（类 / 谓词白名单或预定义查询）。"""
        return bool(self.allowed_classes or self.allowed_predicates or self.predefined_queries)

    # ---------------- 白名单检查 ----------------

    def class_allowed(self, engine, cls_name: str) -> bool:
        """类是否可见：在白名单，或为白名单某类的子类（子类继承规则，显式文档化）。"""
        if cls_name in self.allowed_classes:
            return True
        # 子类继承：沿 subClassOf 上溯到任一白名单类
        stack = [engine.NS[cls_name]]
        seen = set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            for parent in engine.g.objects(cur, RDFS.subClassOf):
                pname = _short(parent)
                if pname in self.allowed_classes:
                    return True
                stack.append(parent)
        return False

    def predicate_allowed(self, name: str) -> bool:
        return name in self.allowed_predicates

    def visible_classes(self) -> list:
        return sorted(self.allowed_classes)

    def visible_predicates(self) -> list:
        return sorted(self.allowed_predicates)

    def query_names(self) -> list:
        return sorted(self.predefined_queries)

    def query_descriptions(self) -> list:
        return [
            {"name": name, "description": q.get("description", ""), "params": q.get("params", {})}
            for name, q in sorted(self.predefined_queries.items())
        ]

    # ---------------- 预定义查询渲染 + 白名单复核 ----------------

    def render_predefined(self, name: str, params: dict, short_to_iri=None) -> dict:
        """渲染预定义查询（{{param}} 占位 → 完整 IRI），返回 {"ok","sparql"} 或 {"ok","error"}。

        白名单复核针对**模板自身的谓词**（渲染前提取 <...>）；参数渲染到对象/主体位置，
        不影响谓词白名单。short_to_iri 为「短名→<完整IRI> 文本」的回调（来自引擎），
        缺省时参数按原样（字符串）替换。
        """
        q = self.predefined_queries.get(name)
        if q is None:
            return {"ok": False, "error": f"未知预定义查询：{name}（可用：{'、'.join(self.query_names()) or '无'}）"}
        template = q["sparql"]
        required = set(re.findall(r"\{\{(\w+)\}\}", template))
        given = set(params or {})
        missing = required - given
        if missing:
            return {"ok": False, "error": f"缺少参数：{'、'.join(sorted(missing))}（{name} 需要：{q.get('params', {})}）"}
        extra = given - required
        if extra:
            return {"ok": False, "error": f"多余参数：{'、'.join(sorted(extra))}（{name} 只接受：{sorted(required)}）"}
        # 白名单复核（渲染前，模板自身引入的谓词必须在白名单）
        for iri in re.findall(r"<([^>]+)>", template):
            if not self.predicate_allowed(_short(URIRef(iri))):
                return {"ok": False,
                        "error": f"预定义查询「{name}」模板引入未授权谓词：{_short(URIRef(iri))}（白名单：{'、'.join(self.visible_predicates()) or '无'}）"}
        # 渲染参数：短名 → 完整 IRI（对象位置）
        sparql = template
        for k, v in (params or {}).items():
            rendered = short_to_iri(v) if short_to_iri else str(v)
            sparql = sparql.replace("{{" + k + "}}", rendered)
        return {"ok": True, "sparql": sparql, "name": name, "params": sorted(given)}


def load_policy(domain_name: str) -> SemanticPolicy | None:
    """从领域包加载 access_policy.json；文件不存在返回 None（策略关闭、逐字节兼容）。"""
    path = os.path.join(_domains_dir(), domain_name, "access_policy.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"access_policy.json 解析失败（{path}）：{exc}") from exc
    return SemanticPolicy(cfg)