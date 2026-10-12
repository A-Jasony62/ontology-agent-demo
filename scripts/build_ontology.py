#!/usr/bin/env python3
"""构建「智能体任务编排」演示本体（OWL 2 DL），导出 .owl 文件并做 HermiT 推理自检。

用法:
    .venv/bin/python scripts/build_ontology.py

输出:
    domains/agent_task/agent_task_ontology.owl   （领域包自包含，可在 Protege 中打开）

推理设计:
    R1 能力匹配   has_capability ◦ requires_capability⁻  ⊑  can_execute   （OWL 属性链，HermiT 推理）
    R3 依赖传递   depends_on 为传递属性（TransitiveProperty）
    R2 复合任务委派 / R4 合规冲突 由 domains/agent_task/ 领域适配器中的规则执行
"""

import os
import sys

from owlready2 import (
    Thing,
    TransitiveProperty,
    FunctionalProperty,
    PropertyChain,
    Ontology,
    get_ontology,
)

import rdflib
from rdflib.namespace import RDF, OWL

ONTO_IRI = "http://demo.example.org/agent-task-ontology"
OUT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "domains", "agent_task", "agent_task_ontology.owl")
)


def build() -> Ontology:
    onto = get_ontology(ONTO_IRI)

    with onto:
        # ================= 类层次 =================
        # --- 智能体 ---
        class Agent(Thing):
            pass

        class RequirementAgent(Agent):
            pass

        class DevAgent(Agent):
            pass

        class JuniorDevAgent(DevAgent):
            pass

        class TestAgent(Agent):
            pass

        class DeployAgent(Agent):
            pass

        # --- 任务 ---
        class Task(Thing):
            pass

        class SimpleTask(Task):
            pass

        class ComplexTask(Task):
            pass

        # --- 能力 ---
        class Capability(Thing):
            pass

        class RequirementAnalysis(Capability):
            pass

        class Coding(Capability):
            pass

        class CodeReview(Capability):
            pass

        class Testing(Capability):
            pass

        class Deployment(Capability):
            pass

        # --- 工具 ---
        class Tool(Thing):
            pass

        class IDE(Tool):
            pass

        class GitRepo(Tool):
            pass

        class CICD(Tool):
            pass

        class KnowledgeBase(Tool):
            pass

        # --- 约束 ---
        class Constraint(Thing):
            pass

        class ComplianceRequirement(Constraint):
            pass

        class SecurityRequirement(Constraint):
            pass

        # ================= 对象属性 =================
        class has_capability(Agent >> Capability):
            """智能体具备的能力"""

        class requires_capability(Task >> Capability):
            """任务所需能力"""

        class required_by(Capability >> Task):
            """requires_capability 的显式逆属性（供属性链使用）"""

        required_by.inverse = requires_capability

        class depends_on(Task >> Task, TransitiveProperty):
            """任务依赖（传递闭包由 HermiT 计算）"""

        class composed_of(ComplexTask >> Task):
            """复合任务的子任务"""

        class can_execute(Agent >> Task):
            """推理结论：智能体可执行任务（不手工断言）"""

        class assigned_to(Task >> Agent):
            """任务分配（分配点，用于合规冲突检测）"""

        class requires_constraint(Task >> Constraint):
            """任务约束要求"""

        class uses_tool(Agent >> Tool):
            """智能体使用的工具"""

        # ================= 数据属性 =================
        class has_certified(Agent >> bool, FunctionalProperty):
            """是否具备合规认证"""

        class has_risk_level(Task >> int, FunctionalProperty):
            """风险等级 1-5"""

        class has_description(Thing >> str, FunctionalProperty):
            """中文描述"""

        # ================= 推理公理 =================
        # R1 能力匹配：A has_capability C 且 T requires_capability C  ⇒  A can_execute T
        can_execute.property_chain = [PropertyChain([has_capability, required_by])]

        # 等价类（供 HermiT 自动分类演示）
        class CertifiedAgent(Agent):
            equivalent_to = [Agent & has_certified.value(True)]

        class ComplianceTask(Task):
            equivalent_to = [Task & requires_constraint.some(ComplianceRequirement)]

        # ================= 类标签 =================
        Agent.label = ["智能体"]
        RequirementAgent.label = ["需求分析Agent类"]
        DevAgent.label = ["研发Agent类"]
        JuniorDevAgent.label = ["初级研发Agent类"]
        TestAgent.label = ["测试Agent类"]
        DeployAgent.label = ["部署Agent类"]
        Task.label = ["任务"]
        SimpleTask.label = ["简单任务"]
        ComplexTask.label = ["复合任务"]
        Capability.label = ["能力"]
        RequirementAnalysis.label = ["需求分析"]
        Coding.label = ["编码实现"]
        CodeReview.label = ["代码审查"]
        Testing.label = ["测试执行"]
        Deployment.label = ["部署发布"]
        Tool.label = ["工具"]
        Constraint.label = ["约束"]
        ComplianceRequirement.label = ["合规认证要求"]
        SecurityRequirement.label = ["安全要求"]

        # ================= 个体：智能体 =================
        req_agent = RequirementAgent(
            "req_agent",
            has_description="负责需求分析、用户故事与验收标准编写",
            has_capability=[RequirementAnalysis],
            uses_tool=[KnowledgeBase],
            has_certified=True,
        )
        req_agent.label = ["需求分析Agent"]

        dev_agent = DevAgent(
            "dev_agent",
            has_description="负责编码实现与代码审查，已通过合规认证",
            has_capability=[Coding, CodeReview],
            uses_tool=[IDE, GitRepo],
            has_certified=True,
        )
        dev_agent.label = ["研发Agent"]

        junior_dev = JuniorDevAgent(
            "junior_dev",
            has_description="仅具备编码能力，尚未通过合规认证",
            has_capability=[Coding],
            uses_tool=[IDE],
            has_certified=False,
        )
        junior_dev.label = ["初级研发Agent"]

        test_agent = TestAgent(
            "test_agent",
            has_description="负责测试执行与质量门禁",
            has_capability=[Testing],
            uses_tool=[CICD],
            has_certified=True,
        )
        test_agent.label = ["测试Agent"]

        deploy_agent = DeployAgent(
            "deploy_agent",
            has_description="负责生产部署与发布",
            has_capability=[Deployment],
            uses_tool=[CICD, GitRepo],
            has_certified=True,
        )
        deploy_agent.label = ["部署Agent"]

        # ================= 个体：任务 =================
        t_req = SimpleTask(
            "t_req",
            has_description="需求分析：新功能用户故事与验收标准",
            requires_capability=[RequirementAnalysis],
            has_risk_level=1,
        )
        t_req.label = ["需求分析任务"]

        t_login_dev = SimpleTask(
            "t_login_dev",
            has_description="登录模块开发",
            requires_capability=[Coding],
            has_risk_level=2,
        )
        t_login_dev.label = ["登录模块开发"]

        t_login_review = SimpleTask(
            "t_login_review",
            has_description="登录模块代码审查",
            requires_capability=[CodeReview],
            has_risk_level=2,
        )
        t_login_review.label = ["登录模块代码审查"]

        t_login_test = SimpleTask(
            "t_login_test",
            has_description="登录模块测试执行",
            requires_capability=[Testing],
            has_risk_level=3,
        )
        t_login_test.label = ["登录模块测试执行"]

        t_deploy = SimpleTask(
            "t_deploy",
            has_description="生产环境部署发布",
            requires_capability=[Deployment],
            has_risk_level=4,
        )
        t_deploy.label = ["生产部署发布"]

        t_compliance_dev = SimpleTask(
            "t_compliance_dev",
            has_description="涉及敏感数据的报表开发（需合规认证）",
            requires_capability=[Coding],
            requires_constraint=[ComplianceRequirement],
            has_risk_level=5,
        )
        t_compliance_dev.label = ["敏感数据报表开发"]

        # 复合任务：新功能上线
        t_feature = ComplexTask(
            "t_feature",
            has_description="新功能上线：需求 → 开发 → 审查 → 测试 → 部署",
            composed_of=[t_req, t_login_dev, t_login_review, t_login_test, t_deploy],
            has_risk_level=4,
        )
        t_feature.label = ["新功能上线（复合任务）"]

        # 复合任务：双模块开发（用于演示 R2 复合任务委派规则）
        t_double_dev = ComplexTask(
            "t_double_dev",
            has_description="双模块开发：登录模块 + 合规报表模块",
            composed_of=[t_login_dev, t_compliance_dev],
            has_risk_level=4,
        )
        t_double_dev.label = ["双模块开发（复合任务）"]

        # 任务依赖（直接边；传递闭包由 HermiT 计算）
        t_login_dev.depends_on = [t_req]
        t_login_review.depends_on = [t_login_dev]
        t_login_test.depends_on = [t_login_review]
        t_deploy.depends_on = [t_login_test]

    # ================= 导出 =================
    onto.save(OUT_PATH, format="rdfxml")
    print(f"[OK] 本体已导出: {OUT_PATH}")
    return onto


def self_check(path: str) -> None:
    """结构自检（RDF 层面，不依赖 Java/推理器）：

    推理行为的正确性由 tests/test_reasoning.py 通过 reasoner 引擎验证。
    """
    g = rdflib.Graph()
    g.parse(path, format="xml")
    ns = f"{ONTO_IRI}#"
    q = lambda name: rdflib.URIRef(f"{ns}{name}")

    # 1) R1 属性链公理存在
    chains = list(g.objects(q("can_execute"), OWL.propertyChainAxiom))
    if not chains:
        print("[FAIL] 缺少 can_execute 的 owl:propertyChainAxiom")
        return False

    # 2) depends_on 是传递属性
    if (q("depends_on"), RDF.type, OWL.TransitiveProperty) not in g:
        print("[FAIL] depends_on 未声明为 TransitiveProperty")
        return False

    # 3) 逆属性声明
    if (q("required_by"), OWL.inverseOf, q("requires_capability")) not in g:
        print("[FAIL] required_by/requires_capability 缺少 inverseOf 声明")
        return False

    # 4) 个体数量与类型
    agents = list(g.subjects(RDF.type, q("Agent")))
    tasks = list(g.subjects(RDF.type, q("Task")))
    # 子类个体的 type 断言是具体类，这里按子类汇总统计
    agent_types = [q("RequirementAgent"), q("DevAgent"), q("JuniorDevAgent"),
                   q("TestAgent"), q("DeployAgent")]
    agents_all = set(agents)
    for at in agent_types:
        agents_all |= set(g.subjects(RDF.type, at))
    task_types = [q("SimpleTask"), q("ComplexTask")]
    tasks_all = set(tasks)
    for tt in task_types:
        tasks_all |= set(g.subjects(RDF.type, tt))
    agents_all.discard(q("Agent"))
    tasks_all.discard(q("Task"))

    ok = True
    print(f"  智能体个体数: {len(agents_all)}（期望 5）")
    print(f"  任务个体数:   {len(tasks_all)}（期望 8：6 简单 + 2 复合）")
    if len(agents_all) != 5 or len(tasks_all) != 8:
        ok = False
    if ok:
        print("[OK] 本体结构自检通过：属性链 / 传递属性 / 逆属性 / 个体齐全")
    return ok


if __name__ == "__main__":
    ontology = build()
    if not self_check(OUT_PATH):
        sys.exit(1)
