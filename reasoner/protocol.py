"""领域适配器契约：框架与领域之间唯一显式声明的接口。

背景：`api/main.py` 一直通过鸭子类型调用适配器的若干方法，契约只存在于注释里。
换一个领域若漏实现某个方法，错误要等到对应请求进来才以 500 暴露。
本模块把这些方法显式声明出来，并提供运行时探测（缺哪些方法），
供出口层做"未实现 → 501"的门禁。

设计约束（P0 阶段，只声明不改行为）：
    - 不引入基类、不改 `create_adapter` 签名、不影响任何现有调用；
    - `runtime_checkable` 的 isinstance 只校验方法**是否存在**，不校验签名
      （签名一致性靠类型检查器，P1 起用基类默认实现约束）；
    - 领域包可以继续用类或普通对象实现，无需继承任何东西。

框架提供 vs 领域实现：
    - `explain` / `graph_export` 只依赖引擎原语，P1 起由框架基类提供默认实现；
    - 其余 5 个是业务语义，必须由领域实现。

用法：
    from reasoner.protocol import missing_methods, supports

    missing = missing_methods(adapter)          # [] 表示契约完整
    supports(adapter, "capability_match")       # 端点门禁用
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = [
    "AdapterProtocol",
    "BUSINESS_METHODS",
    "FRAMEWORK_METHODS",
    "REQUIRED_METHODS",
    "CAPABILITIES",
    "missing_methods",
    "supports",
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
