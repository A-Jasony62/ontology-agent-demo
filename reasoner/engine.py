"""推理引擎（通用层）：本体加载 + OWL 2 RL 前向推理 + 通用查询接口。

与本体定义完全解耦，核心代码不含任何领域词汇：

  - 加载任意 .owl（rdflib 解析，无需 Java / HermiT）
  - L1 本体推理：owlrl OWL 2 RL（属性链、传递闭包、子类/等价类）
  - 通用查询接口：SPARQL / 个体 / 类层次 / 类型 / 属性取值 / 重推理
  - 通用原语：individuals_of / objects_of / subject_objects / has_type /
    add_type / add_triple / add_literal / reparse / topological_sort

领域语义（能力匹配 / 编排 / 分配合规 / 分类 / 图谱导出）不在本文件——
由独立目录 domains/ 下的领域适配器在运行时动态加载（见 domains/__init__.py），
适配器把本引擎当作通用图 + 推理服务使用。
"""

import os

from rdflib import Graph, Namespace, URIRef, Literal, RDF, RDFS, OWL
import owlrl

ONTO_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "domains", "agent_task", "agent_task_ontology.owl")
)
DEFAULT_NS = "http://demo.example.org/agent-task-ontology#"
NS = Namespace(DEFAULT_NS)  # 默认本体命名空间（兼容旧引用；实例请用 self.NS）


def local(iri) -> str:
    """取 IRI 的短名（最后一个 # 或 / 之后）。"""
    s = str(iri)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


class OntologyEngine:
    """通用本体引擎：加载 / 推理 / 查询 / 写图原语，与本体定义无关。"""

    def __init__(self, onto_path: str = ONTO_PATH, ns: str | None = None):
        self.onto_path = onto_path
        self.NS = Namespace(ns or DEFAULT_NS)

        self.g = Graph()
        self.g.parse(onto_path, format="xml")
        # L1：OWL 2 RL 推理（属性链、传递闭包、子类/等价类分类）
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(self.g)

    # ---------------- 通用原语（供领域适配器组合） ----------------

    def label(self, iri) -> str:
        """取 rdfs:label 中文名；无 label 时回退短名。同时接受 URIRef 与短名。"""
        if isinstance(iri, str) and not iri.startswith("http"):
            iri = self.NS[iri]
        v = self.g.value(iri, RDFS.label)
        return str(v) if v is not None else local(iri)

    def _subclass_of(self, cls: URIRef) -> set:
        """类 cls 及其全部子类（含自身）。"""
        result = {cls}
        changed = True
        while changed:
            changed = False
            for sub in self.g.subjects(RDFS.subClassOf, cls):
                if sub not in result:
                    result.add(sub)
                    changed = True
        return result

    def individuals_of(self, class_name: str) -> list[str]:
        """指定类（短名）及其全部子类的个体短名列表。"""
        cls = self.NS[class_name]
        inds = set()
        for t in self._subclass_of(cls):
            inds |= set(self.g.subjects(RDF.type, t))
        return sorted(local(i) for i in inds)

    def objects_of(self, subject: str, property_name: str) -> list[str]:
        """主体-属性 的全部取值（IRI 值转短名，字面值取 str）。"""
        vals = self.g.objects(self.NS[subject], self.NS[property_name])
        return sorted(
            (local(v) if isinstance(v, URIRef) else str(v)) for v in vals
        )

    def subject_objects(self, property_name: str) -> list[tuple[str, str]]:
        """属性的全部 (主语, 宾语) 短名对。"""
        return sorted(
            (local(s), local(o))
            for s, o in self.g.subject_objects(self.NS[property_name])
        )

    def has_type(self, individual: str, class_name: str) -> bool:
        """个体（短名）是否属于该类（含子类/推理结论）。"""
        return class_name in self.types_of(individual)

    def add_type(self, individual: str, class_name: str) -> None:
        """断言个体类型（短名）。"""
        self.g.add((self.NS[individual], RDF.type, self.NS[class_name]))

    def add_triple(self, subject: str, property_name: str, value: str) -> None:
        """断言对象属性三元组（subject/value 均为短名）。"""
        self.g.add((self.NS[subject], self.NS[property_name], self.NS[value]))

    def add_literal(self, subject: str, property_name: str, value) -> None:
        """断言数据属性三元组（value 为字面量，如数字/字符串）。"""
        self.g.add((self.NS[subject], self.NS[property_name], Literal(value)))

    def reparse(self) -> None:
        """重新执行 OWL 2 RL 推理（新增断言后调用）。"""
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(self.g)

    def triples_count(self) -> int:
        return len(self.g)

    @staticmethod
    def topological_sort(nodes: list, edges: list) -> list:
        """Kahn 拓扑排序（含环保护：有环时剩余节点按原顺序追加）。"""
        indeg = {n: 0 for n in nodes}
        adj = {n: [] for n in nodes}
        for s, o in edges:
            adj[s].append(o)
            indeg[o] += 1
        ready = [n for n in nodes if indeg[n] == 0]
        order = []
        while ready:
            n = ready.pop(0)
            order.append(n)
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
        for n in nodes:
            if n not in order:
                order.append(n)
        return order

    # ---------------- 通用查询接口（对外，与本体定义无关） ----------------

    def query_sparql(self, sparql: str) -> list[dict]:
        """执行 SPARQL SELECT，返回 [{变量: 值}, ...]（IRI 值转短名）。"""
        rows = []
        for row in self.g.query(sparql):
            d = {}
            for var in row.asdict():
                v = row[var]
                d[var] = local(v) if isinstance(v, URIRef) else str(v)
            rows.append(d)
        return rows

    def individuals(self, class_name: str) -> list[str]:
        """指定类（短名）及其子类的全部个体短名。"""
        return self.individuals_of(class_name)

    def classes(self) -> list[dict]:
        """全部类：name/label/direct_parent（rdfs:subClassOf 直接父类短名）。"""
        out = []
        for cls in sorted(self.g.subjects(RDF.type, OWL.Class), key=str):
            parent = self.g.value(cls, RDFS.subClassOf)
            out.append({
                "name": local(cls),
                "label": self.label(cls),
                "parent": local(parent) if parent else None,
            })
        return out

    def types_of(self, individual: str) -> list[str]:
        """个体推理后的全部类型短名（含推理出的等价类/子类结论）。"""
        return sorted({local(t) for t in self.g.objects(self.NS[individual], RDF.type)})

    def property_values(self, subject: str, property_name: str) -> list[str]:
        """主体-属性 取值列表（IRI 值转短名）。"""
        return self.objects_of(subject, property_name)

    def infer(self) -> dict:
        """重新执行 OWL 2 RL 推理，返回三元组/类/个体数量统计。"""
        before = len(self.g)
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(self.g)
        return {
            "triples_before": before,
            "triples_after": len(self.g),
            "added": len(self.g) - before,
            "classes": len(self.classes()),
            "individuals": len(set(self.g.subjects(RDF.type, OWL.NamedIndividual))),
        }


_engine = None


def get_engine(onto_path: str = ONTO_PATH, ns: str | None = None) -> OntologyEngine:
    """共享单例（API / MCP / CLI 复用同一份加载与推理结果）。"""
    global _engine
    if _engine is None or _engine.onto_path != onto_path:
        _engine = OntologyEngine(onto_path, ns=ns)
    return _engine
