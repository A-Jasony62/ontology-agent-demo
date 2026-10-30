"""模块合并冲突预检（reasoner/merge_check.py）测试：合并前的冲突扫描仪。

覆盖：
  - 正例：三类冲突（同 URI 异定义 / 同 label 异 IRI / disjoint 矛盾）的最小本体
    全部检出且分级正确、每条含双侧对照与 suggestion
  - 反例：真同义（同 IRI 且定义一致）不误报；纯新增归 info 不进 conflicts
  - 边界：空 RDF 零交集 → overlap=0 诚实报告；语法错 fail-fast；
    同绝对 IRI 不同前缀写法归一化为同一实体；注册管道级调用可用
"""

import os

from rdflib import Graph

from reasoner.merge_check import compare, parse_rdf, run_merge_check
from reasoner.engine import ONTO_PATH, OntologyEngine

# mcp_server 模块（绕过 mcp/ 目录与 pip SDK 同名的遮蔽问题，同 test_tool_guard 惯例）
import importlib.util

_SERVER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp", "mcp_server.py")
_server_spec = importlib.util.spec_from_file_location("_mcp_server_merge_test", _SERVER_PATH)
mcp_server = importlib.util.module_from_spec(_server_spec)
_server_spec.loader.exec_module(mcp_server)

CURRENT_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/cur#> .

ex:Customer a owl:Class ; rdfs:subClassOf ex:Party ; rdfs:label "客户" .
ex:Party a owl:Class .
ex:A a owl:Class .
ex:B a owl:Class .
ex:A owl:disjointWith ex:B .
<http://example.org/cur#X> a owl:Class ; rdfs:subClassOf <http://example.org/cur#A> .
ex:Common a owl:Class ; rdfs:subClassOf ex:Party .
ex:shared_prop a owl:ObjectProperty ;
    rdfs:domain ex:Task ; rdfs:range ex:Agent .
ex:Task a owl:Class .
ex:Agent a owl:Class .
"""

# 含全部三类冲突的外部本体（与前缀写法混用，验证 IRI 归一化）
INCOMING_CONFLICTS_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/cur#> .
@prefix alt: <http://example.org/alt#> .

# ① 同 URI 异定义：Customer 父类 Contact ≠ Party（前缀写法，与 current 全 IRI 写法同实体）
ex:Customer a owl:Class ; rdfs:subClassOf alt:Contact ; rdfs:label "客户" .
alt:Contact a owl:Class .

# ② 名称冲突：同 label "客户" 不同 IRI（alt:Client vs cur:Customer）
alt:Client a owl:Class ; rdfs:label "客户" .

# ③ 公理矛盾：incoming X ⊑ B，current X ⊑ A 且 A disjointWith B
ex:X rdfs:subClassOf ex:B .

# 同理：incoming 侧写法用短名（前缀）
ex:shared_prop_new a owl:ObjectProperty .
"""


def test_all_three_conflict_types_detected_and_classified():
    """正例：三类冲突全检出、分级正确（同 URI 异定义 + disjoint = conflict；
    同 label 异 IRI = warning）、每条含双侧对照与 suggestion。"""
    cur, inc = parse_rdf(CURRENT_TTL), parse_rdf(INCOMING_CONFLICTS_TTL)
    r = compare(cur, inc)
    by_type = {c["type"] for c in r["conflicts"]}
    assert "same_uri_diff_definition" in by_type
    assert "disjoint_axiom_violation" in by_type
    assert len(r["conflicts"]) == 2          # ① Customer + ③ X
    assert len(r["warnings"]) == 1           # ② 同 label 异 IRI
    # ① 双侧事实对照
    c1 = next(c for c in r["conflicts"] if c["type"] == "same_uri_diff_definition")
    assert c1["entity"] == "Customer"
    assert "Party" in c1["current"]["parents"] and "Contact" in c1["incoming"]["parents"]
    assert c1["suggestion"].startswith("align")
    # ③ 指明矛盾两侧
    c2 = next(c for c in r["conflicts"] if c["type"] == "disjoint_axiom_violation")
    assert c2["entity"] == "X" and set(c2["via"]) == {"A", "B"}
    # ② warning 建议 rename/align
    w = r["warnings"][0]
    assert w["type"] == "same_label_diff_uri" and w["label"] == "客户"
    assert w["current_iri"] == "Customer" and w["incoming_iri"] == "Client"
    assert w["suggestion"].startswith("rename")
    # summary 计数一致
    assert r["summary"]["conflicts"] == 2 and r["summary"]["warnings"] == 1


def test_true_synonyms_and_pure_additions_no_false_positive():
    """反例：①同 IRI 且定义完全一致（真同义）不误报；②纯新增 5 个实体全部归 info。"""
    clean = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/cur#> .
@prefix new: <http://example.org/new#> .

ex:Common a owl:Class ; rdfs:subClassOf ex:Party .
ex:Party a owl:Class .
ex:shared_prop a owl:ObjectProperty ; rdfs:domain ex:Task ; rdfs:range ex:Agent .
ex:Task a owl:Class .
ex:Agent a owl:Class .
new:S1 a owl:Class .  new:S2 a owl:Class .  new:S3 a owl:Class .
new:P1 a owl:ObjectProperty .  new:P2 a owl:DatatypeProperty .
"""
    cur, inc = parse_rdf(CURRENT_TTL), parse_rdf(clean)
    r = compare(cur, inc)
    assert r["summary"]["conflicts"] == 0     # 同 IRI 同父类/同 domain-range：不误报
    assert r["summary"]["warnings"] == 0      # 无名称冲突
    assert r["summary"]["overlap_entities"] == 5   # Common/Party/shared_prop/Task/Agent 五实体重叠
    # 纯新增归 info（不进 conflicts）
    additions = {i["entity"] for i in r["info"]}
    assert {"S1", "S2", "S3", "P1", "P2"} <= additions
    assert all(i["type"] == "addition" for i in r["info"])


def test_empty_rdf_zero_overlap_honest_report():
    """边界①：空 RDF（合法空图）→ overlap=0 零冲突诚实报告。"""
    cur = parse_rdf(CURRENT_TTL)
    r = compare(cur, Graph())
    assert r["summary"]["incoming_triples"] == 0
    assert r["summary"]["overlap_entities"] == 0
    assert r["summary"]["conflicts"] == 0
    assert r["conflicts"] == [] and r["warnings"] == []


def test_syntax_error_fails_fast_with_position():
    """边界②：Turtle 语法错 → fail-fast 返回 error（含解析失败信息），不 crash。"""
    r = run_merge_check(parse_rdf(CURRENT_TTL), "not a turtle @@@ triple")
    assert "error" in r and "解析失败" in r["error"]
    assert r["conflicts"] == [] and r["summary"]["incoming_triples"] == 0


def test_same_absolute_iri_prefix_vs_full_form_normalized():
    """边界③：同绝对 IRI 不同前缀写法（alt 前缀 vs 完整 IRI）→ 归一化后同一实体。"""
    # incoming 用全 IRI 写 X ⊑ B（与正例的前缀写法指向同一绝对 IRI）
    full_form = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<http://example.org/cur#X> rdfs:subClassOf <http://example.org/cur#B> .
<http://example.org/cur#B> a owl:Class .
"""
    r = compare(parse_rdf(CURRENT_TTL), parse_rdf(full_form))
    assert any(c["type"] == "disjoint_axiom_violation" and c["entity"] == "X"
               for c in r["conflicts"])


def test_registered_tool_end_to_end():
    """边界④：注册管道级——merge_check 经 _register_generic_tools 注册后可调用。"""

    class FakeServer:
        def __init__(self):
            self.tools = {}

        def tool(self, description=None):
            def deco(fn):
                self.tools[fn.__name__] = fn
                return fn
            return deco

    server = FakeServer()
    engine = OntologyEngine(ONTO_PATH)
    mcp_server._register_generic_tools(server, lambda: engine, None, None)
    assert "merge_check" in server.tools
    # 真引擎图 + 无害新增（一个新类）→ info 报告正常产出
    benign = "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n" \
             "<http://example.org/neo#TotallyNew> a owl:Class .\n"
    r = server.tools["merge_check"](benign)
    assert "error" not in r
    assert r["summary"]["info_additions"] == 1
    assert r["info"][0]["entity"] == "TotallyNew"
    # 语法错走 error 通道
    r2 = server.tools["merge_check"]("broken @@@")
    assert "error" in r2 and "解析失败" in r2["error"]
