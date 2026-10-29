"""领域适配器契约：框架与领域之间唯一显式声明的接口。

背景：`api/main.py` 一直通过鸭子类型调用适配器的若干方法，契约只存在于注释里。
换一个领域若漏实现某个方法，错误要等到对应请求进来才以 500 暴露。
本模块把这些方法显式声明出来，并提供运行时探测（缺哪些方法），
供出口层做"未实现 → 501"的门禁。

设计约束：
    - `runtime_checkable` 的 isinstance 只校验方法**是否存在**，不校验签名
      （签名一致性靠类型检查器，基类默认实现提供兜底语义）；
    - 领域包可以继续用类或普通对象实现；继承 `AdapterBase` 可白拿
      `explain` / `graph_export` 的默认实现。

P1-1 起契约**强制**：`domains.registry.load_domain` 加载即校验，
缺方法直接 `DomainContractError`（不再是等请求进来才 500/501）。
豁免方式只有一条——在领域包里声明 `CAPABILITIES`，把**不实现**的能力
显式排除；声明了 `CAPABILITIES` 就等于承诺"清单内的方法我都实现了"。

框架提供 vs 领域实现：
    - `explain` / `graph_export` 只依赖引擎原语，由 `AdapterBase` 提供默认实现；
    - 其余 5 个是业务语义，必须由领域实现（或显式排除）。

用法：
    from reasoner.protocol import missing_methods, supports

    missing = missing_methods(adapter)          # [] 表示契约完整
    supports(adapter, "capability_match")       # 端点门禁用
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from rdflib import OWL, RDF, RDFS, URIRef

__all__ = [
    "AdapterBase",
    "AdapterProtocol",
    "BUSINESS_METHODS",
    "FRAMEWORK_METHODS",
    "REQUIRED_METHODS",
    "CAPABILITIES",
    "default_explain",
    "default_graph_export",
    "missing_methods",
    "supports",
    "undeclared_missing",
]


# 业务语义方法：必须由领域实现，框架无法代劳
BUSINESS_METHODS: tuple[str, ...] = (
    "capability_match",
    "orchestrate",
    "assign",
    "classify",
    "consistency",
)

# 框架能力：只依赖引擎原语，P1 起由基类提供默认实现
FRAMEWORK_METHODS: tuple[str, ...] = (
    "explain",
    "graph_export",
)

# 当前框架要求的全部方法（P0 阶段与 CAPABILITIES 同集）
REQUIRED_METHODS: tuple[str, ...] = BUSINESS_METHODS + FRAMEWORK_METHODS

# 标准能力标识：领域包可用 CAPABILITIES 声明"我支持哪些"，缺省视为全量
CAPABILITIES: tuple[str, ...] = REQUIRED_METHODS


@runtime_checkable
class AdapterProtocol(Protocol):
    """领域适配器契约。

    只描述"方法存在"这一层；参数语义由各方法自己的 docstring 负责。
    注意 `classify` 的 `capabilities` / `constraints` / `risk_level` 是
    「智能体任务编排」领域的形状，异构领域无法照此实现——这里如实声明，
    不假装通用；自由 payload 方案留待后续单独评估。
    """

    def capability_match(self, task_iri: Any, with_derivation: bool = True) -> dict:
        """哪些 Agent 可执行该任务（附推导链）。"""
        ...

    def orchestrate(self, task_iri: Any, with_derivation: bool = True) -> dict:
        """按依赖顺序拆解执行链并逐环节匹配执行者。"""
        ...

    def assign(
        self, task_iri: Any, agent_iri: Any,
        with_derivation: bool = True, persist: bool = False,
    ) -> dict:
        """分配任务给 Agent，含合规冲突检测；persist=True 时落盘。"""
        ...

    def consistency(self, with_derivation: bool = True) -> dict:
        """全量一致性 / 合规冲突检查。"""
        ...

    def classify(
        self, name: str, capabilities: list, constraints: list,
        risk_level: int = 3, persist: bool = False,
    ) -> dict:
        """新增个体、重推理、自动分类。"""
        ...

    def explain(self) -> dict:
        """最近一次推理的推导链（中文）。"""
        ...

    def graph_export(self) -> dict:
        """图谱渲染数据（节点 / 边）。"""
        ...


def missing_methods(adapter: Any) -> list[str]:
    """返回适配器缺失的契约方法；空列表表示契约完整。"""
    return [m for m in REQUIRED_METHODS if not callable(getattr(adapter, m, None))]


def undeclared_missing(adapter: Any) -> list[str]:
    """缺失**且未声明排除**的方法——即加载器真正该拒绝的清单。

    语义（三态，不要简化成两态）：
      - 无 `CAPABILITIES` 属性 / 为 None → 视为"全量能力"，缺一个都不行；
      - `CAPABILITIES = ("capability_match", ...)` → 声明即承诺，清单外的
        缺失方法算已排除（端点走 400「未声明能力」）；
      - `CAPABILITIES = ()` → 合法的"零能力领域"（只有通用层可用）。

    为什么不是"缺了就拒绝"：异构领域不可能都实现 `classify` 那种
    带领域形状的方法（见 AdapterProtocol 的说明）。强制的是"要么实现、
    要么明说"，而不是"必须全实现"。
    """
    missing = missing_methods(adapter)
    declared = getattr(adapter, "CAPABILITIES", None)
    if declared is None:
        return missing
    return [m for m in missing if m in declared]


def supports(adapter: Any, capability: str) -> bool:
    """端点门禁：方法存在 **且** 领域未在 CAPABILITIES 里显式排除。

    领域包未声明 CAPABILITIES 时视为全量能力（向后兼容）。
    """
    if not callable(getattr(adapter, capability, None)):
        return False
    declared = getattr(adapter, "CAPABILITIES", None)
    if declared is None:
        return True
    return capability in declared


# ---------------------------------------------------------------- 框架默认实现


def _local(iri: Any) -> str:
    """IRI 短名（本模块不 import reasoner.engine，避免协议层反向依赖引擎）。"""
    text = str(iri)
    return text.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def default_explain(adapter: Any) -> dict:
    """默认的推导链出口：读适配器自己记录的 last_query_kind / last_derivation。

    约定（而非接口）：领域在一次业务查询后把这两项写给实例；没写过就是空。
    """
    return {
        "query_kind": getattr(adapter, "last_query_kind", None),
        "derivation": getattr(adapter, "last_derivation", []) or [],
    }


def default_graph_export(adapter: Any) -> dict:
    """默认的图谱导出：只依赖引擎原语 + 领域 config 的结构声明。

    产物形状（classes / individuals / edges）与前端既有约定一致，
    但个体属性是通用提取（label + 该个体全部对象属性值），不含领域特效字段。
    需要「已认证 / 风险等级 / 复合任务」这类展示语义的领域，自行覆盖。

    读取的配置键（都可缺省）：
        top_classes           顶层类短名列表
        hidden_label_classes  不在图谱里展开的子类
        graph_groups          {"Agent": "agent_class", "Task": "task_class"}
                              group 名 → 取该 group 个体的类键（走 resolve）
    """
    engine = adapter.engine
    cfg = adapter.c
    NS = engine.NS

    top = list(cfg.get("top_classes", []) or [])
    hidden = set(cfg.get("hidden_label_classes", []) or [])

    classes: list[dict] = []
    for tc in top:
        cls = NS[tc]
        classes.append({"name": tc, "label": engine.label(cls), "parent": None})
        for sub in sorted(engine.g.subjects(RDFS.subClassOf, cls), key=str):
            name = _local(sub)
            # 推理物化会补出自反边（X ⊑ X）与 owl:Nothing ⊑ X，两者都不是「子类」，
            # 拿假图做单元测试看不出来——是 _minimal 这类真实小本体把它们照出来的
            if name in hidden or name == tc or name == "Nothing":
                continue
            classes.append({"name": name, "label": engine.label(sub), "parent": tc})

    individuals: list[dict] = []
    for group, class_key in (cfg.get("graph_groups", {}) or {}).items():
        for name in engine.individuals_of(cfg.resolve(class_key)):
            individuals.append({
                "name": name,
                "label": engine.label(name),
                "group": group,
            })

    known = {i["name"] for i in individuals}
    edges: list[dict] = []
    for s, p, o in engine.g:
        if not isinstance(o, URIRef) or p in _META_PREDICATES:
            continue
        s_name, o_name = _local(s), _local(o)
        if s_name in known and o_name in known:
            edges.append({
                "source": s_name, "target": o_name, "property": _local(p),
                # 断言图里没有的边即推理产物（引擎 raw 保留原始断言）
                "inferred": (s, p, o) not in getattr(engine, "raw", engine.g),
            })
    return {"classes": classes, "individuals": individuals, "edges": edges}


# 结构谓词：图谱导出时不当作业务边（类层次用 classes 表达）
_META_PREDICATES = frozenset({
    RDF.type, RDFS.subClassOf, RDFS.subPropertyOf, RDFS.label, RDFS.comment,
    RDFS.domain, RDFS.range, RDFS.seeAlso, RDFS.isDefinedBy,
    OWL.equivalentClass, OWL.equivalentProperty, OWL.disjointWith,
    OWL.intersectionOf, OWL.unionOf, OWL.complementOf, OWL.oneOf,
    OWL.someValuesFrom, OWL.allValuesFrom, OWL.hasValue, OWL.onProperty,
    # owlrl 会给每个个体补 sameAs 自反边——它是推理产物，不是业务关系
    OWL.sameAs, OWL.differentFrom,
})


class AdapterBase:
    """领域适配器基类：白拿框架默认实现，只写业务方法。

    用法：
        class MyAdapter(AdapterBase):
            CAPABILITIES = ("capability_match",)     # 我只实现这一个

            def __init__(self, engine, config):
                self.engine = engine
                self.c = config

            def capability_match(self, task_iri, with_derivation=True): ...

    子类必须自己设置 `self.engine` 与 `self.c`（语义配置）：框架不知道
    领域怎么装配它们，也不该知道。
    """

    NAME = ""
    CAPABILITIES: tuple[str, ...] | None = None     # None = 全量能力
    last_query_kind: str | None = None
    last_derivation: list = []

    # 变更状态的"无持久化"默认语义（P2）：/api/health 是运维探针，任何领域
    # 都得能查。没有 ABox 写入能力的领域（如 examples/_minimal）不能因为
    # 查 change_count 就让整个 health 端点 500——它只是从未变更过而已。
    @property
    def change_count(self) -> int:
        return 0

    @property
    def changelog(self) -> list:
        return []

    @property
    def last_commit(self) -> str | None:
        return None

    @property
    def assignments(self) -> dict:
        return {}

    def explain(self) -> dict:
        """最近一次查询的推导链（默认实现，子类可覆盖）。"""
        return default_explain(self)

    def graph_export(self) -> dict:
        """图谱渲染数据（默认实现，子类可覆盖）。"""
        return default_graph_export(self)
