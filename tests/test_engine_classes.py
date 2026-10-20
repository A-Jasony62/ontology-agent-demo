"""engine.classes() 应过滤 owlrl 物化混入的匿名空节点（"幽灵类"）。

背景：
`classes()` 用 `g.subjects(RDF.type, OWL.Class)` 枚举类（engine.py）。owlrl 做 OWL 2 RL
物化时会把 equivalentClass 公理中的类表达式节点（如 intersectionOf 的 `owl:Class`
匿名节点）类型化为 owl:Class（ClassExpression ⊑ Class 推论），导致这些无 IRI 的
BNode 混入类层次输出，污染 /api/classes、MCP entities() 与前端类树。

修复：`classes()` 循环开头跳过 `isinstance(cls, BNode)`。

BNode 特征：rdflib 自动生成的 ID 形如 `N` + 32 位 hex（共 33 字符）。
"""

from rdflib import BNode, OWL, RDF

from reasoner.engine import ONTO_PATH, OntologyEngine

# 最小反例本体：Employee 等价于「Person ∩ 具有 worksFor 属性」的 intersectionOf 类表达式。
# 物化后该 owl:Class 匿名节点会被类型化为 owl:Class，制造一个本应被过滤的 BNode 幽灵。
MINI_OWL = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF
    xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
    xmlns:owl="http://www.w3.org/2002/07/owl#"
    xmlns="http://ex.org/o#">
  <owl:Ontology rdf:about="http://ex.org/o"/>
  <owl:Class rdf:about="http://ex.org/o#Person"/>
  <owl:Class rdf:about="http://ex.org/o#Company"/>
  <owl:Class rdf:about="http://ex.org/o#Employee">
    <owl:equivalentClass>
      <owl:Class>
        <owl:intersectionOf rdf:parseType="Collection">
          <rdf:Description rdf:about="http://ex.org/o#Person"/>
          <owl:Restriction>
            <owl:onProperty rdf:resource="http://ex.org/o#worksFor"/>
            <owl:someValuesFrom rdf:resource="http://ex.org/o#Company"/>
          </owl:Restriction>
        </owl:intersectionOf>
      </owl:Class>
    </owl:equivalentClass>
  </owl:Class>
  <owl:ObjectProperty rdf:about="http://ex.org/o#worksFor"/>
</rdf:RDF>
"""


def _is_ghost_bnode(name: str) -> bool:
    """是否 rdflib BNode 短名（N + 32 位 hex，共 33 字符）。"""
    return name.startswith("N") and len(name) == 33


def _write_mini_owl(tmp_path):
    path = tmp_path / "mini_intersection.owl"
    path.write_text(MINI_OWL, encoding="utf-8")
    return str(path)


def test_default_ontology_exposes_only_named_classes():
    """正例：默认 agent_task 本体 classes() 只含具名语义类，零 BNode 幽灵。

    修复前 29 条类含 2 条 BNode 幽灵 → 修复后 27 条真实类；若上游本体演化使总数
    变化，断言零幽灵与关键类保留仍成立（27 以「已知类数 − 幽灵数」形式注释）。
    """
    engine = OntologyEngine(ONTO_PATH)
    names = [c["name"] for c in engine.classes()]
    assert not any(_is_ghost_bnode(n) for n in names)
    assert len(names) == 27  # 29（含 2 幽灵）− 2 = 27
    assert {"CertifiedAgent", "ComplianceTask"} <= set(names)


def test_minimal_equivalent_intersection_bnode_is_skipped(tmp_path):
    """反例：owlrl 物化确实制造了 BNode 类，classes() 必须过滤且保留具名类。

    先断言图中确有 BNode 幽灵（证明用例真实触发），再断言 classes() 输出干净。
    """
    engine = OntologyEngine(_write_mini_owl(tmp_path))
    raw_classes = list(engine.g.subjects(RDF.type, OWL.Class))
    assert any(isinstance(c, BNode) for c in raw_classes), "反例未触发：图中应存在 BNode 幽灵类"
    names = [c["name"] for c in engine.classes()]
    assert not any(_is_ghost_bnode(n) for n in names)
    assert {"Person", "Employee", "Company"} <= set(names)


def test_infer_metadata_and_graph_export_stay_consistent():
    """边界：infer() 统计与 classes() 一致；图谱导出天然免疫 BNode。"""
    engine = OntologyEngine(ONTO_PATH)
    assert engine.infer()["classes"] == len(engine.classes())
    graph_data = engine._graph_data(engine.g)
    node_ids = [n["id"] for n in graph_data["nodes"]]
    assert not any(_is_ghost_bnode(i) for i in node_ids)