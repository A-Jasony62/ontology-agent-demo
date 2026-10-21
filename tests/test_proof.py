"""reasoner/proof 结构化证明导出：机器可读的推理依据（引擎级，与领域无关）。

覆盖三类推理规则（MVP）+ 三种 mode（asserted / derived / unproven）：
  - property_chain   (R1)：owl:propertyChainAxiom 属性链
  - transitive       (R3)：owl:TransitiveProperty 传递闭包
  - class_membership (R4)：rdfs:subClassOf 类型判定

设计要点：诚实降级——推不出来的结论不伪造证明（unproven / 空公理）。
"""

import time

from reasoner.engine import ONTO_PATH, OntologyEngine
from reasoner.proof import build_proof, diff_materialized


def _engine():
    return OntologyEngine(ONTO_PATH)


def test_rule1_property_chain_returns_full_premises():
    """正例：R1 属性链——dev_agent can_execute t_login_dev 的证明含公理链与两条前提。"""
    p = build_proof(_engine(), "dev_agent", "can_execute", "t_login_dev")
    assert p["mode"] == "derived"
    assert p["rule"] == "property_chain"
    assert len(p["axioms"]) == 1
    axiom = p["axioms"][0]
    assert axiom["type"] == "owl:propertyChainAxiom"
    assert axiom["chain"] == ["has_capability", "required_by"]
    # 前提 = 两条事实边：has_capability（断言） + required_by（可能派生，标注 source）
    assert p["premises"][0]["predicate"] == "has_capability"
    assert p["premises"][0]["object"] == "Coding"
    assert p["premises"][1]["predicate"] == "required_by"
    assert p["premises"][1]["object"] == "t_login_dev"
    assert p["premises"][0]["source"] == "asserted"
    assert p["conclusion"] == {"subject": "dev_agent", "predicate": "can_execute",
                                "object": "t_login_dev"}


def test_negative_unproven_is_empty_safe():
    """反例①：问一个不存在的结论 → mode=unproven，空安全，不伪造。"""
    p = build_proof(_engine(), "dev_agent", "can_execute", "t_ghost_task")
    assert p["mode"] == "unproven"
    assert p["rule"] is None
    assert p["premises"] == []
    assert p["axioms"] == []


def test_asserted_conclusion_has_no_fabricated_axioms():
    """反例②：本体直接断言的三元组 → mode=asserted，无公理/前提，不伪造证明。"""
    p = build_proof(_engine(), "dev_agent", "has_capability", "Coding")
    assert p["mode"] == "asserted"
    assert p["premises"] == []
    assert p["axioms"] == []


def test_rule3_transitive_returns_fact_edge_chain():
    """边界①：R3 传递闭包——premises 是原始直接依赖边链，而非闭包结论本身。"""
    p = build_proof(_engine(), "t_deploy", "depends_on", "t_req")
    assert p["mode"] == "derived"
    assert p["rule"] == "transitive"
    assert p["axioms"][0]["type"] == "owl:TransitiveProperty"
    # 前提全是原始直接边（asserted），且不含「闭包结论本身」那条边
    assert all(prem["source"] == "asserted" for prem in p["premises"])
    assert len(p["premises"]) >= 2
    assert ("t_deploy", "depends_on", "t_req") not in {
        (prem["subject"], prem["predicate"], prem["object"]) for prem in p["premises"]
    }


def test_rule4_class_membership_subclass_basis():
    """边界②：R4 类归属——dev_agent type Agent 由 (type DevAgent) + (DevAgent ⊑ Agent) 支撑。"""
    p = build_proof(_engine(), "dev_agent", "type", "Agent")
    assert p["mode"] == "derived"
    assert p["rule"] == "class_membership"
    subs = [(prem["predicate"], prem["object"]) for prem in p["premises"]]
    assert ("type", "DevAgent") in subs
    assert ("subClassOf", "Agent") in subs


def test_diff_materialized_returns_only_new_triples():
    """边界③：物化 diff 只含推理新增三元组，供 proof 与评测 harness 复用。"""
    e = _engine()
    d = diff_materialized(e.g, e.raw)
    assert isinstance(d, frozenset)
    assert len(d) > 0
    # 断言边不属于新增（已在原始断言图中）
    assert (e.NS.dev_agent, e.NS.has_capability, e.NS.Coding) not in d


def test_proof_construction_fast_enough():
    """边界④：agent_task 体量下 proof 构造在百毫秒量级内。"""
    e = _engine()
    start = time.perf_counter()
    build_proof(e, "dev_agent", "can_execute", "t_login_dev")
    build_proof(e, "t_deploy", "depends_on", "t_req")
    build_proof(e, "dev_agent", "type", "Agent")
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0