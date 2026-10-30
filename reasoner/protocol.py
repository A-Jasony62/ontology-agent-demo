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


def _has_named_between(g: Any, sub: Any, top: Any) -> bool:
    """`sub` 与 `top` 之间是否还存在具名中间类（即 sub 不是 top 的直接子类）。

    推理闭包里 subClassOf 已传递展开，所以只看 sub 的父类里有没有
    "自身仍是 top 后代"的那一个：有则 sub 应挂在那个父类下面。
    匿名中间类不算——它上不了类层次，跳过它才能把层次挂回具名类。
    """
    for mid in g.objects(sub, RDFS.subClassOf):
        if mid == sub or mid == top or not isinstance(mid, URIRef):
            continue
        if (mid, RDFS.subClassOf, top) in g:
            return True
    return False


def _descendants(g: Any, cls: Any, name: str, hidden: set, label) -> list[dict]:
    """递归收集 cls 之下的具名子类，parent 指向**直接**父类。

    三件事在推理图上必须显式处理，否则真实本体一上来就出错（都由
    examples/fault_diag 的三级类层次照出）：

      1. 不是具名 URI 的主语不是类层次的一层。owl:equivalentClass 在 RL
         推理后拆成两条 subClassOf，匿名端点（owl:Restriction）会作为主语
         冒出来，_local() 只能给出 N<hex> 这种名字。
         **判据必须用 `isinstance(x, URIRef)` 而不是 `isinstance(x, BNode)`：
         rdflib 的 BNode 继承自 str**，任何"先按 str 兜底"的转换都会把
         BNode 变成 Literal，那时 isinstance(x, BNode) 恒为假，过滤形同虚设。
      2. subClassOf 在闭包里已传递展开，subjects(subClassOf, cls) 拿到的是
         全部后代而非直接子类；直接拿来用会把多级层次压平到顶层之下。
      3. 只展开两代（top + 直接子类）会丢掉第三级；递归才能表达完整层次。
         环靠 seen 截断（等价类可以造环）。
    """
    out: list[dict] = []
    seen: set[str] = set()

    def walk(parent_cls, parent_name: str) -> None:
        for sub in sorted(g.subjects(RDFS.subClassOf, parent_cls), key=str):
            if not isinstance(sub, URIRef):      # 匿名类 / 字面量：不是类
                continue
            sub_name = _local(sub)
            # 自反边（X ⊑ X）、owl:Nothing ⊑ X、领域声明隐藏的子类
            if sub_name in hidden or sub_name == parent_name or sub_name in seen:
                continue
            if sub_name == "Nothing":
                continue
            # 只挂直接子类：若 sub 与 parent 之间还有具名中间类，交给那一层
            if _has_named_between(g, sub, parent_cls):
                continue
            seen.add(sub_name)
            out.append({"name": sub_name, "label": label(sub), "parent": parent_name})
            walk(sub, sub_name)

    walk(cls, name)
    return out


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
        classes.extend(_descendants(engine.g, cls, tc, hidden, engine.label))

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

    # /api/health 的推理器描述。框架只知道推理器本身；"业务规则 R2/R4"
    # 这类编号是领域词汇，由领域自己覆盖——否则异构领域（没有 R2/R4）
    # 的探针输出会撒谎。
    REASONER_SUMMARY = "OWL 2 RL (owlrl)"

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
