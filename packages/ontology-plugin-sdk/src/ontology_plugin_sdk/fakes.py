"""`FakeEngine`：让领域包脱离主框架单测的最小引擎。

它存在的理由不是"省依赖"，而是**让测试测对东西**：

    真实引擎里混了两类行为——图操作（领域关心的）与推理（宿主负责的）。
    领域包的单元测试如果跑在真引擎上，一旦断言涉及推理产物（比如"A 的所有
    子类"），测的其实是推理器而不是领域逻辑；推理器换实现、或物化策略变了，
    领域包会莫名其妙挂掉，而它自己一行没改。

    FakeEngine 刻意**不推理**：`g` 与 `raw` 是同一张图，`add_*` 写进去什么
    就能读到什么。领域若需要"推理后再判断"，那是集成测试的范围，用真引擎。

为什么不去 import 宿主：导入它就等于把 SDK 的测试绑在某个应用上，SDK 就
不再是"能独立发布的包"了。
"""

from __future__ import annotations

from typing import Any, Iterable

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef

from .engine import local

__all__ = ["FakeEngine"]


def _as_term(value: Any, ns: Namespace) -> Any:
    """短名按命名空间展开；真 IRI 与字面量原样返回。

    判据必须先查 `URIRef` 再查 `str`：**rdflib 的 `URIRef` 继承自 `str`**，
    顺序反了就会把 `RDFS.subClassOf` 拼成 `ns#http://...subClassOf` 这种
    伪谓词——图里查不到，而症状要到断言失败时才显形。
    """
    if isinstance(value, URIRef):
        return value
    if isinstance(value, str):
        return ns[value]
    return value


class FakeEngine:
    """内存图引擎：满足 `EngineProtocol`，无推理、无落盘。

    用法：
        from ontology_plugin_sdk import FakeEngine
        from ontology_plugin_sdk.fakes import FakeEngine   # 显式路径亦可

        g = FakeEngine(ns="http://example.org/demo#")
        g.add_type("pump_01", "Pump")
        g.add_triple("pump_01", "exhibits", "vibration_high")
        adapter = MyAdapter(g, cfg)        # 领域适配器照常构造
        assert adapter.diagnose("pump_01")["most_likely"] == "bearing_wear"

    参数：
        ns      默认命名空间（决定 `NS` 与短名↔IRI 的映射）
        graph   外部传入的 rdflib 图（用于复用已有夹具）
    """

    def __init__(self, ns: str = "http://example.org/fake#", graph: Graph | None = None):
        self.NS = Namespace(ns)
        self.g: Graph = graph if graph is not None else Graph()
        self.raw: Graph = self.g            # 不推理，断言图即推理图
        self.extensions_dir: str | None = None   # 单文件模式：ABox 不落盘

    # ---------------- 读取 ----------------

    def label(self, iri: Any) -> str:
        """rdfs:label 优先，缺失回退短名（与真引擎一致）。"""
        if isinstance(iri, str) and not iri.startswith("http"):
            iri = self.NS[iri]
        v = self.g.value(iri, RDFS.label)
        return str(v) if v is not None else local(iri)

    def _subclass_of(self, cls: URIRef) -> set:
        """类 cls 及其全部子类（含自身）。

        必须自己沿链递归：真引擎的图是 OWL RL 闭包，`subjects(subClassOf, X)`
        直接就能拿到**所有**后代；FakeEngine 没有物化，只查一层的话
        `Pump ⊑ Equipment ⊑ Asset` 里的 Pump 在查 Asset 时就丢了。
        这个差异不补，领域包在 FakeEngine 上写的测试会与真引擎上行为不一致
        ——那比"测不出来"更糟，它会给出错误的信心。
        """
        result = {cls}
        stack = [cls]
        while stack:
            cur = stack.pop()
            for sub in self.g.subjects(RDFS.subClassOf, cur):
                if sub not in result:
                    result.add(sub)
                    stack.append(sub)
        return result

    def individuals_of(self, class_name: str) -> list[str]:
        cls = self.NS[class_name]
        inds: set = set()
        for t in self._subclass_of(cls):
            inds |= set(self.g.subjects(RDF.type, t))
        return sorted(local(i) for i in inds)

    def objects_of(self, subject: str, property_name: str) -> list[str]:
        vals = self.g.objects(self.NS[subject], self.NS[property_name])
        return sorted(
            (local(v) if isinstance(v, URIRef) else str(v)) for v in vals
        )

    def subject_objects(self, property_name: str) -> list[tuple[str, str]]:
        return sorted(
            (local(s), local(o))
            for s, o in self.g.subject_objects(self.NS[property_name])
        )

    def has_type(self, individual: str, class_name: str) -> bool:
        return (self.NS[individual], RDF.type, self.NS[class_name]) in self.g

    def types_of(self, individual: str) -> list[str]:
        return sorted(local(t) for t in self.g.objects(self.NS[individual], RDF.type))

    def classes(self) -> list[dict]:
        """全部类：name/label/direct_parent（与真引擎同形状）。"""
        out = []
        for cls in sorted(set(self.g.subjects(RDF.type, RDFS.Class))
                          | set(self.g.subjects(RDF.type, URIRef("http://www.w3.org/2002/07/owl#Class"))),
                          key=str):
            if not isinstance(cls, URIRef):
                continue
            parent = next((p for p in self.g.objects(cls, RDFS.subClassOf)
                           if isinstance(p, URIRef)), None)
            out.append({
                "name": local(cls),
                "label": self.label(cls),
                "direct_parent": local(parent) if parent else None,
            })
        return out

    def query_sparql(self, sparql: str) -> list[dict]:
        rows = []
        for row in self.g.query(sparql):
            d = {}
            for var in row.asdict():
                v = row[var]
                d[var] = local(v) if isinstance(v, URIRef) else str(v)
            rows.append(d)
        return rows

    # ---------------- 写入 ----------------

    def add_triple(self, subject: str, property_name: str, value: str) -> None:
        """宾语按 IRI 处理（与真引擎一致：属性值若是字面量用 add_literal）。"""
        self.g.add((self.NS[subject], self.NS[property_name], self.NS[value]))

    def add_type(self, individual: str, class_name: str) -> None:
        self.g.add((self.NS[individual], RDF.type, self.NS[class_name]))

    def add_literal(self, subject: str, property_name: str, value: Any) -> None:
        self.g.add((self.NS[subject], self.NS[property_name], Literal(value)))

    def remove_triples(self, subject: str, property_name: str,
                       value: str | None = None) -> None:
        s, p = self.NS[subject], self.NS[property_name]
        if value is None:
            self.g.remove((s, p, None))
        else:
            self.g.remove((s, p, self.NS[value]))
            # 宾语也可能是字面量（add_literal 写入的），一并清掉
            self.g.remove((s, p, Literal(value)))

    def reparse(self) -> None:
        """真引擎会重推理并重建闭包；FakeEngine 无需动作（保持接口一致）。"""

    # ---------------- 分析 ----------------

    @staticmethod
    def topological_sort(nodes: list, edges: list) -> list:
        """Kahn 拓扑排序（含环保护：有环时剩余节点按原顺序追加）。

        与宿主引擎同一算法——这不是"实现细节"，而是排序**语义**的一部分
        （同层节点的输出顺序会直接影响推导链文案），复制会让两边慢慢漂移。
        """
        indeg = {n: 0 for n in nodes}
        adj: dict = {n: [] for n in nodes}
        for s, o in edges:
            adj[s].append(o)
            indeg[o] += 1
        ready = [n for n in nodes if indeg[n] == 0]
        order: list = []
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

    # ---------------- 夹具构造便利 ----------------

    def load_triples(self, triples: Iterable[tuple]) -> "FakeEngine":
        """批量断言，便于写夹具。

        谓词与宾语都接受三种写法：
          - 短名（`"exhibits"`）→ 按本引擎 NS 展开
          - `URIRef`（如 `RDFS.subClassOf` / `RDF.type`）→ 原样使用
          - 其它（`Literal` 等）→ 原样使用
        必须支持 URIRef：`subClassOf` 这类标准词汇若也按 NS 展开，写出来的
        会是一条 `ns#subClassOf` 伪谓词——图里查不到，而报错要等到断言失败
        才出现，排查成本远高于这里多一个分支。
        """
        for s, p, o in triples:
            self.g.add((_as_term(s, self.NS), _as_term(p, self.NS), _as_term(o, self.NS)))
        return self

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<FakeEngine ns={self.NS} triples={len(self.g)}>"
