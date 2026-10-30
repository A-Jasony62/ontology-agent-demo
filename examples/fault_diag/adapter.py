"""「设备故障诊断」领域适配器（第二个异构领域）。

**这个包的存在理由不是功能，是证伪。**
`examples/agent_task` 是框架的第一个宿主，框架里那些"看起来通用"的抽象
（CAPABILITIES 三态、graph_groups、推导链配置、ABox 谓词声明）都只在它身上
验过。一个领域验证不了通用性——它只能验证"框架没把这个领域搞坏"。

本包与 agent_task 在四个维度上刻意异构：

    维度        agent_task                    fault_diag
    ----------  ----------------------------  ------------------------------
    类结构      Agent/Task/Capability 扁平    Asset→Equipment/Component 层级 + 因果链
    主要边      can_execute（分配关系）        impliesFault（因果关系）
    业务操作    分配给谁（assign/orchestrate） 这现象说明什么坏了（diagnose）
    推理用法    R2 复合任务委派（代码规则）    CriticalFault 由 owl:hasValue 推出

因此 CAPABILITIES 里出现了一个**不在框架 REQUIRED_METHODS 里的名字**
（diagnose）。这是有意的探针，用来回答"领域能不能声明框架没预见的操作"。

只从门面 import（P1-4 纪律，见 tests/test_plugin.py 的架构断言）。
"""

from __future__ import annotations

import os
from typing import Any

from reasoner.plugin import (
    AdapterBase,
    PluginContext,
    load_derivation_config,
    load_domain_config,
    local,
)

NAME = "fault_diag"
DESCRIPTION = (
    "设备故障诊断：部件现象 → 故障模式 → 处置措施（本体因果链 + OWL 推理定级）；"
    "不提供任务编排类能力"
)

# 本体文件（相对包目录，加载器按包定位；不写绝对路径）
ONTO_FILE = "fault_diag.owl"

# 能力声明（三态契约见 reasoner/protocol.py）：
#   diagnose     ← 本领域自定义能力，框架 REQUIRED_METHODS 里没有这个名字
#   consistency  ← 框架既有能力，本领域用"故障模式是否都有处置"来解读
#   explain / graph_export ← 由 AdapterBase 提供默认实现
# 未声明的 capability_match / orchestrate / assign / classify 是**明说不提供**，
# 端点应返 400「未声明能力」而不是 501 或 500。
CAPABILITIES = ("diagnose", "consistency", "explain", "graph_export")


class FaultDiagnosisAdapter(AdapterBase):
    """故障诊断查询：包一层通用引擎，业务全在因果链遍历上。"""

    NAME = NAME
    CAPABILITIES = CAPABILITIES
    # 本领域没有 R2/R4 那类编号规则，推理就靠 OWL RL + 因果链遍历
    REASONER_SUMMARY = "OWL 2 RL (owlrl) + 因果链遍历"

    def __init__(self, engine, config=None, ctx: PluginContext | None = None):
        self.ctx = ctx or PluginContext.for_engine(engine)
        self.engine = engine
        self.NS = engine.NS
        self.label = engine.label
        self.last_query_kind: str | None = None
        self.last_derivation: list = []

        # 领域数据随包走：与 agent_task 同样是「_DIR + 文件名」，不依赖 CWD
        here = os.path.dirname(os.path.abspath(__file__))
        if config is None or not hasattr(config, "resolve"):
            config = load_domain_config(os.path.join(here, "config.json")).config
        der = load_derivation_config(os.path.join(here, "derivation.json"))
        self.c = config
        self.templates = dict(der.templates)
        self.derivations = dict(der.derivations)

        # ABox 事务：诊断域只读，但仍声明引用谓词——指向不存在个体的边
        # 应当在落盘/校验阶段被发现，而不是被静默当成"没有这个关系"
        self.abox = self.ctx.abox(
            resolve_predicate=self._p,
            reference_predicates=("hasComponent", "exhibits", "impliesFault", "hasRemedy"),
        )

    # ---------------- 语义访问 ----------------

    def _p(self, key: str):
        return self.NS[self.c.resolve(key)]

    def _cls(self, key: str) -> str:
        return self.c.resolve(key)

    # ---------------- 因果链查询 ----------------

    def components(self) -> list[str]:
        """全部部件（含子类个体）。诊断的最小单元。"""
        return self.engine.individuals_of(self._cls("component_class"))

    def equipment(self) -> list[str]:
        return self.engine.individuals_of(self._cls("equipment_class"))

    def symptoms_of(self, component) -> list[str]:
        return self.engine.objects_of(local(component), self.c.resolve("exhibits"))

    def faults_for_symptom(self, symptom) -> list[str]:
        return self.engine.objects_of(local(symptom), self.c.resolve("impliesFault"))

    def remedies_of(self, fault) -> list[str]:
        return self.engine.objects_of(local(fault), self.c.resolve("hasRemedy"))

    def severity_of(self, fault) -> int:
        vals = self.engine.objects_of(local(fault), self.c.resolve("hasSeverity"))
        try:
            return int(vals[0])
        except (IndexError, TypeError, ValueError):
            return 0

    def is_critical(self, fault) -> bool:
        """是否重大故障——**读推理结果**，不比较 severity 数值。

        CriticalFault 在本体里定义为「hasSeverity 恰为 4 的 FaultMode」，
        由 owlrl 的 OWL RL 规则推出类型。这里若改成 `severity_of(f) == 4`，
        测试仍全绿但推理链已经不被使用了——所以这一步刻意走类型查询。
        """
        return self.engine.has_type(local(fault), self._cls("critical_fault_class"))

    def faults(self) -> list[str]:
        return self.engine.individuals_of(self._cls("fault_class"))

    # ---------------- 业务能力：diagnose ----------------

    def diagnose(self, component, with_derivation: bool = True) -> dict:
        """给定部件，按因果链推出候选故障并按严重度排序。

        排序键刻意固定为 (严重度降序, 支持现象数降序, 名称升序)：
        诊断结果要有稳定顺序，前端才不至于每次刷新换一个"最可能"。
        """
        comp = local(component)
        symptoms = self.symptoms_of(comp)

        support: dict[str, list[str]] = {}
        for symptom in symptoms:
            for fault in self.faults_for_symptom(symptom):
                support.setdefault(fault, []).append(symptom)

        candidates = []
        for fault, supporters in support.items():
            remedies = self.remedies_of(fault)
            candidates.append({
                "name": fault,
                "label": self.label(fault),
                "severity": self.severity_of(fault),
                "critical": self.is_critical(fault),      # 推理产物
                "critical_mark": "，重大" if self.is_critical(fault) else "",
                "remedies": [{"name": r, "label": self.label(r)} for r in remedies],
                # 推导链里 `loop` 引用的键必须存在：解释器对 $x.y 缺键是 KeyError
                # 而不是跳过（配置错误要暴露）。所以这里把渲染所需形状一次摊平。
                "remedy_labels": [self.label(r) for r in remedies],
                "evidence": supporters,
                "support_count": len(supporters),
                # 推导链的 if 只做真值判断，1 也是真——所以"多现象共指"要
                # 单独算成布尔，否则只有 1 个现象支持时也会说"被共同指向"
                "multi_support": len(supporters) > 1,
                "no_remedy": not remedies,
            })
        candidates.sort(key=lambda f: (-f["severity"], -f["support_count"], f["name"]))

        symptom_items = [
            {
                "name": s,
                "label": self.label(s),
                "fault_labels": [self.label(f) for f in self.faults_for_symptom(s)],
            }
            for s in symptoms
        ]
        # 推导链需要 1 起的序号（模板里 "{i}." 直接渲染）
        for i, item in enumerate(symptom_items, start=1):
            item["i"] = i
        for i, item in enumerate(candidates, start=1):
            item["i"] = i

        self.last_query_kind = "diagnose"
        self.last_derivation = self.ctx.expand(
            self.derivations["diagnose"],
            {
                "symptom_labels": symptom_items,
                "faults": candidates,
                "top_label": candidates[0]["label"] if candidates else "",
            },
            self.templates,
        ) if with_derivation else []

        return {
            "component": comp,
            "component_label": self.label(comp),
            "symptoms": [
                {"name": s["name"], "label": s["label"]} for s in symptom_items
            ],
            "faults": candidates,
            "most_likely": candidates[0]["name"] if candidates else None,
            "derivation": self.last_derivation,
        }

    # ---------------- 业务能力：consistency ----------------

    def consistency(self, with_derivation: bool = True) -> dict:
        """维护手册完整性检查：故障是否都有处置、现象是否都指向故障。

        与 agent_task 的 consistency（合规冲突）同名不同义——这正是
        "框架能力名 + 领域自解释"的用法：框架只要求"存在一致性检查这件事"。
        """
        checks = []
        for fault in self.faults():
            has_remedy = bool(self.remedies_of(fault))
            checks.append({
                "kind": "fault_remedy",
                "fault": fault,
                "label": self.label(fault),
                "ok": has_remedy,
                "tpl": "sec_check_ok" if has_remedy else "sec_check_bad",
            })

        orphans = [
            s for s in self.engine.individuals_of(self._cls("symptom_class"))
            if not self.faults_for_symptom(s)
        ]

        violations = [c for c in checks if not c["ok"]]
        self.last_query_kind = "consistency"
        self.last_derivation = self.ctx.expand(
            self.derivations["consistency"],
            {
                "checks": checks,
                "orphan_symptoms": [self.label(s) for s in orphans],
            },
            self.templates,
        ) if with_derivation else []

        return {
            "consistent": not violations and not orphans,
            "checks": checks,
            "violations": violations,
            "orphan_symptoms": orphans,
            "derivation": self.last_derivation,
        }


# ---------------- 工厂（两种签名都要支持） ----------------


def create_adapter_ctx(ctx: PluginContext) -> FaultDiagnosisAdapter:
    """首选工厂：配置从包目录读，不硬编码路径。"""
    return FaultDiagnosisAdapter(ctx.engine, ctx.load_domain_config("config.json").config, ctx=ctx)


def create_adapter(engine, config: Any = None) -> FaultDiagnosisAdapter:
    """兼容工厂：`create_adapter(engine)` / `create_adapter(engine, cfg)` 均可。"""
    return FaultDiagnosisAdapter(engine, config)
