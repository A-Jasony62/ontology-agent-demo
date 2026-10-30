"""自定义业务规则引擎（reasoner/rules.py）测试：JSON IF-THEN 单步匹配 + 派生导出。

覆盖：
  - 正例：三条件规则（含 not_exists）恰好命中目标任务；conclusions 与 proof.premises
    完整（前提逐条列出、asserted 分流、absence 留痕）；proof 键级对齐 build_proof
  - 反例：任一条件改否（gte 提高到 5 / 给任务补 can_execute 断言）→ 零产出无误报
  - 边界：全无匹配诚实空清单；规则 JSON 非法 fail-fast 指明规则 ID 与字段；
    单步语义（A 规则产物不作为 B 规则输入）；rules.json 未配置提示；MCP 管道级可用
"""

import json
import os

import pytest

from reasoner import rules as rules_mod
from reasoner.proof import build_proof
from reasoner.engine import OntologyEngine

import importlib.util

from _helpers import domain_module, submodule  # noqa: E402

_SERVER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp", "mcp_server.py")
_server_spec = importlib.util.spec_from_file_location("_mcp_server_rules_test", _SERVER_PATH)
mcp_server = importlib.util.module_from_spec(_server_spec)
_server_spec.loader.exec_module(mcp_server)

mod = domain_module()

# 三条件规则（含 not_exists）：复合 ∧ 高风险 ∧ 无人可整体执行 → 需人工介入
R5 = {
    "id": "R5_complex_no_executor",
    "description": "复合任务高风险且无人可整体执行 → 标记需人工介入",
    "when": [
        {"s": "?task", "p": "composed_of", "o": "?sub"},
        {"s": "?task", "p": "has_risk_level", "o": {"gte": 4}},
        {"not_exists": {"s": "?agent", "p": "can_execute", "o": "?task"}},
    ],
    "then": [
        {"s": "?task", "p": "needs_manual_review", "o": True},
        {"s": "?task", "p": "review_reason", "o": "no_executor"},
    ],
}


def _engine_with_adapter():
    """独立引擎 + 适配器（adapter 会把 R2 委派边写入 g，贴近 MCP 运行时判定面）。"""
    e = OntologyEngine(mod.ONTO_FILE)
    mod.create_adapter(e)
    return e


# ---------------- 正例 ----------------

def test_three_condition_rule_hits_exactly_target_task():
    """正例①：三条件规则恰好命中 t_feature（t_double_dev 因 R2 委派边存在被排除）。"""
    r = rules_mod.apply_rules(_engine_with_adapter(), [R5])
    assert r["rules_loaded"] == 1 and r["matched"] == 1
    res = r["results"][0]
    concl = {(c["subject"], c["predicate"], c["object"]) for c in res["conclusions"]}
    assert ("t_feature", "needs_manual_review", True) in concl
    assert ("t_feature", "review_reason", "no_executor") in concl
    # 恰好一个任务命中：t_double_dev 有委派边（not_exists 不成立），不误报
    subjects = {c["subject"] for c in res["conclusions"]}
    assert subjects == {"t_feature"}
    # 新谓词未在本体声明 → declared=false 诚实提示
    assert all(c["declared"] is False for c in res["conclusions"])


def test_proof_premises_complete_and_asserted():
    """正例②：proof.premises 完整——composed_of 五条子任务边 + 风险边（asserted 分流）
    + not_exists absence 留痕；键级对齐 build_proof（mode/rule/axioms/premises/conclusion）。"""
    r = rules_mod.apply_rules(_engine_with_adapter(), [R5])
    target = next(c for c in r["results"][0]["conclusions"]
                  if c["predicate"] == "needs_manual_review")
    proof = target["proof"]
    # 键级对齐 build_proof
    bp = build_proof(_engine_with_adapter(), "dev_agent", "can_execute", "t_login_dev")
    assert set(proof.keys()) == set(bp.keys())
    assert proof["mode"] == "derived"
    assert proof["rule"] == "custom_rule:R5_complex_no_executor"
    assert proof["conclusion"] == {"subject": "t_feature", "predicate": "needs_manual_review",
                                   "object": True}
    # 前提：子任务边（5 条）+ 风险边，全部 asserted
    preds = [p["predicate"] for p in proof["premises"]]
    assert preds.count("composed_of") == 5
    assert preds.count("has_risk_level") == 1
    assert any(p["source"] == "asserted" and p["predicate"] == "has_risk_level"
               and p["object"] == 4 for p in proof["premises"])
    # 反条件 absence 留痕：自由变量保留名（?agent），绑定变量解析（t_feature）
    absence = [p for p in proof["premises"] if p["source"] == "absence"]
    assert len(absence) == 1
    assert absence[0]["predicate"] == "can_execute"
    assert absence[0]["subject"] == "?agent" and absence[0]["object"] == "t_feature"
    # axioms 携带规则定义（依据可复现）
    assert proof["axioms"][0]["id"] == "R5_complex_no_executor"


def test_domain_rules_json_loads_and_applies():
    """正例③：领域包 rules.json 出厂规则可直接执行（R5 命中 t_feature；R6 低风险三条）。"""
    rules = rules_mod.load_rules_from_domain("agent_task")
    assert rules is not None and len(rules) == 2
    r = rules_mod.apply_rules(_engine_with_adapter(), rules)
    assert r["matched"] == 2
    by_rule = {x["rule_id"]: x for x in r["results"]}
    r5_subs = {c["subject"] for c in by_rule["R5_complex_no_executor"]["conclusions"]}
    assert r5_subs == {"t_feature"}
    r6_subs = {c["subject"] for c in by_rule["R6_low_risk_solo"]["conclusions"]}
    assert r6_subs == {"t_login_dev", "t_login_review", "t_req"}   # 风险 ≤2 且有能力要求
    assert len(r["derived"]) == 5                                   # R5 两条 + R6 三条


# ---------------- 反例 ----------------

def test_any_condition_broken_no_output():
    """反例①：任一条件改否 → 零产出无误报：gte 4 → 5（风险不达标）。"""
    r5_higher = {**R5, "id": "R5x", "when": [
        R5["when"][0], {"s": "?task", "p": "has_risk_level", "o": {"gte": 5}},
        R5["when"][2]]}
    r = rules_mod.apply_rules(_engine_with_adapter(), [r5_higher])
    assert r["matched"] == 0 and r["results"][0]["conclusions"] == []
    assert r["derived"] == []


def test_not_exists_blocks_when_executor_assigned():
    """反例②：给 t_feature 补一条 can_execute 断言 → not_exists 不成立 → 不再命中。"""
    e = _engine_with_adapter()
    e.add_triple("dev_agent", "can_execute", "t_feature")
    r = rules_mod.apply_rules(e, [R5])
    assert r["matched"] == 0
    assert r["results"][0]["conclusions"] == []


# ---------------- 边界例 ----------------

def test_no_match_honest_empty_result():
    """边界①：全规则无匹配 → matched=0 空清单（非报错、非假成功）。"""
    never = {"id": "NEVER", "when": [{"s": "?t", "p": "has_risk_level", "o": {"gte": 99}}],
             "then": [{"s": "?t", "p": "x", "o": True}]}
    r = rules_mod.apply_rules(_engine_with_adapter(), [never])
    assert r["matched"] == 0 and r["derived"] == []
    assert r["results"][0]["matched_bindings"] == 0


@pytest.mark.parametrize("bad,part", [
    ({"id": "B1", "when": [{"s": "?t", "p": "has_risk_level", "o": {"gte": 4}}]}, "缺 then"),
    ({"id": "B2", "when": [], "then": [{"s": "?t", "p": "x", "o": True}]}, "when 须为非空"),
    ({"id": "B3", "when": [{"s": "?t", "p": "p", "o": {"gt": 1}}],
      "then": [{"s": "?t", "p": "x", "o": True}]}, "算子"),
    ({"id": "B4", "when": [{"s": "?t", "p": "?p", "o": 1}],
      "then": [{"s": "?t", "p": "x", "o": True}]}, "谓词"),
])
def test_broken_rules_fail_fast_naming_rule_and_field(bad, part):
    """边界②：规则 JSON 非法 → fail-fast 指明规则 ID 与问题字段（不静默）。"""
    with pytest.raises(ValueError) as ei:
        rules_mod.apply_rules(_engine_with_adapter(), [bad])
    assert bad["id"] in str(ei.value) and part in str(ei.value)


def test_single_step_semantics():
    """边界③：单步执行——A 规则产物（needs_manual_review）不作为 B 规则的输入，
    同一次调用中 B 零触发（产物不写回图，天然无环）。"""
    chain = {"id": "CHAIN",
             "when": [{"s": "?t", "p": "needs_manual_review", "o": {"eq": "true"}}],
             "then": [{"s": "?t", "p": "escalated", "o": True}]}
    e = _engine_with_adapter()
    r = rules_mod.apply_rules(e, [R5, chain])
    assert r["results"][0]["rule_id"] == "R5_complex_no_executor"
    assert r["results"][0]["conclusions"]            # A 正常产出
    assert r["results"][1]["rule_id"] == "CHAIN"
    assert r["results"][1]["conclusions"] == []      # B 不看 A 的产物
    # 且图未被写回（escalated/needs_manual_review 均不在图中）
    assert (e.NS["t_feature"], e.NS["needs_manual_review"], None) not in e.g


def test_mcp_pipeline_registration_and_default_rules():
    """边界④：MCP 管道级——apply_tools 注册后用领域默认规则可跑；未配置时诚实提示。"""

    class FakeServer:
        def __init__(self):
            self.tools = {}

        def tool(self, description=None):
            def deco(fn):
                self.tools[fn.__name__] = fn
                return fn
            return deco

    server = FakeServer()
    e = _engine_with_adapter()
    defaults = rules_mod.load_rules_from_domain("agent_task")
    mcp_server._register_generic_tools(server, lambda: e, None, None, default_rules=defaults)
    assert "apply_rules" in server.tools
    r = server.tools["apply_rules"]()
    assert r["matched"] == 2 and len(r["derived"]) == 5
    # 内联规则优先于默认
    r2 = server.tools["apply_rules"]([{**R5, "id": "INLINE"}])
    assert r2["matched"] == 1
    # 非法内联 → 结构化 error（指明规则与字段），不 crash
    r3 = server.tools["apply_rules"]([{"id": "BAD", "when": []}])
    assert "error" in r3 and "BAD" in r3["error"]
    # 未配置领域默认且未传内联 → 诚实提示
    server2 = FakeServer()
    mcp_server._register_generic_tools(server2, lambda: e, None, None, default_rules=None)
    r4 = server2.tools["apply_rules"]()
    assert r4.get("configured") is False and "rules.json" in r4["message"]


def test_missing_rules_file_returns_none(tmp_path, monkeypatch):
    """边界⑤：领域包无 rules.json → load 返回 None（「未配置」而非报错）。"""
    monkeypatch.setattr(rules_mod, "_DOMAINS_DIR", str(tmp_path))
    assert rules_mod.load_rules_from_domain("no_such_domain") is None
    # JSON 损坏 → fail-fast 指明文件（不静默降级）
    d = tmp_path / "foo"
    d.mkdir(parents=True)
    (d / "rules.json").write_text("{ broken json", encoding="utf-8")
    with pytest.raises(ValueError):
        rules_mod.load_rules_from_domain("foo")
