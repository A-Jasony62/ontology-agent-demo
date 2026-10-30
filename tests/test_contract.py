"""P1-1 适配器契约测试：加载即校验 + 框架默认实现。

回归重点：
  1. `load_domain` 不再"先跑起来再说"——缺方法在加载时就拒绝；
  2. 拒绝的前提是"未声明排除"：声明 CAPABILITIES 的部分领域必须放行；
  3. `AdapterBase` 提供的 explain / graph_export 默认实现只依赖引擎原语，
     异构领域不写这两行也能导出图谱。
"""

import os
import sys

import pytest
from rdflib import BNode, Graph, Literal, Namespace, OWL, RDF, RDFS, URIRef

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.loader import load_config  # noqa: E402
from domains.registry import DomainContractError, load_domain  # noqa: E402
from reasoner.engine import local  # noqa: E402
from reasoner.protocol import (  # noqa: E402
    AdapterBase,
    REQUIRED_METHODS,
    missing_methods,
    supports,
    undeclared_missing,
)

_PROBE = "contract_probe"


@pytest.fixture(autouse=True)
def clean_modules():
    def _purge():
        for key in list(sys.modules):
            if key == f"domains.{_PROBE}" or key.startswith(f"domains.{_PROBE}."):
                del sys.modules[key]
    _purge()
    yield
    _purge()


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "domains"
    r.mkdir()
    return r


def _settings(tmp_path, root):
    return load_config(
        config_dir=tmp_path / "cfg", project_root=tmp_path,
        cli_root=str(root), env={},
    )


def _pkg(root, body):
    pkg = root / _PROBE
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(body, encoding="utf-8")
    return pkg


ALL_METHODS_BODY = "\n".join(
    f"    def {m}(self, *a, **k):\n        return {{'method': {m!r}}}"
    for m in REQUIRED_METHODS
)


# ---------------- 强制校验 ----------------


def test_missing_methods_rejected_at_load(tmp_path, root):
    """什么都没声明也没实现 → 加载即失败，而不是等请求进来。"""
    _pkg(root, "NAME = 'probe'\n"
              "def create_adapter(engine, config=None):\n"
              "    return object()\n")

    with pytest.raises(DomainContractError) as exc:
        load_domain(_PROBE, object(), settings=_settings(tmp_path, root))
    assert "capability_match" in str(exc.value)
    assert "CAPABILITIES" in str(exc.value)


def test_full_implementation_passes(tmp_path, root):
    _pkg(root, "NAME = 'probe'\n"
               "class A:\n"
               f"{ALL_METHODS_BODY}\n"
               "def create_adapter(engine, config=None):\n"
               "    return A()\n")

    adapter = load_domain(_PROBE, object(), settings=_settings(tmp_path, root))
    assert missing_methods(adapter) == []


def test_declared_subset_is_allowed(tmp_path, root):
    """声明即承诺：清单内实现即可加载，清单外的缺失不算违约。"""
    _pkg(root, "NAME = 'probe'\n"
               "class A:\n"
               "    CAPABILITIES = ('capability_match',)\n"
               "    def capability_match(self, *a, **k):\n"
               "        return {}\n"
               "def create_adapter(engine, config=None):\n"
               "    return A()\n")

    adapter = load_domain(_PROBE, object(), settings=_settings(tmp_path, root))
    assert undeclared_missing(adapter) == []
    assert supports(adapter, "capability_match")
    assert not supports(adapter, "orchestrate")       # 端点门禁走 400


def test_declared_but_unimplemented_is_rejected(tmp_path, root):
    """声明了却没实现，比不声明更糟——加载时就戳穿。"""
    _pkg(root, "NAME = 'probe'\n"
               "class A:\n"
               "    CAPABILITIES = ('capability_match', 'orchestrate')\n"
               "    def capability_match(self, *a, **k):\n"
               "        return {}\n"
               "def create_adapter(engine, config=None):\n"
               "    return A()\n")

    with pytest.raises(DomainContractError, match="orchestrate"):
        load_domain(_PROBE, object(), settings=_settings(tmp_path, root))


def test_zero_capability_domain_loads(tmp_path, root):
    """空清单是合法的「零能力领域」：只有通用层端点可用。"""
    _pkg(root, "NAME = 'probe'\n"
               "class A:\n"
               "    CAPABILITIES = ()\n"
               "def create_adapter(engine, config=None):\n"
               "    return A()\n")

    adapter = load_domain(_PROBE, object(), settings=_settings(tmp_path, root))
    assert undeclared_missing(adapter) == []
    assert [m for m in REQUIRED_METHODS if supports(adapter, m)] == []


# ---------------- 框架默认实现 ----------------

T = "http://demo.example.org/t#"
_NS = Namespace(T)


class _FakeEngine:
    """只提供默认实现所需的引擎原语——用真 rdflib 图，避免夹具语义漂移。

    刻意不继承 OntologyEngine：默认实现若偷偷依赖引擎的某个具体方法，
    这个测试就会炸，这正是它存在的意义。
    """

    def __init__(self, triples):
        self.g = Graph()
        for s, p, o in triples:
            self.g.add((_term(s), _term(p), _term(o)))
        # raw = 断言图（无推理产物）；默认实现用它区分推断边
        self.raw = Graph()
        for triple in self.g:
            self.raw.add(triple)
        self.NS = _NS

    def label(self, iri):
        target = _NS[iri] if isinstance(iri, str) and not iri.startswith("http") else iri
        value = self.g.value(target, RDFS.label)
        return str(value) if value is not None else local(target)

    def individuals_of(self, class_name):
        cls = _NS[class_name]
        wanted = {cls}
        changed = True
        while changed:                      # 子类闭包（与引擎同语义）
            changed = False
            for sub, _p, sup in self.g.triples((None, RDFS.subClassOf, None)):
                if sup in wanted and sub not in wanted:
                    wanted.add(sub)
                    changed = True
        found = set()
        for cls_iri in wanted:
            found |= set(self.g.subjects(RDF.type, cls_iri))
        return sorted(local(i) for i in found)


def _term(value):
    # BNode 必须在 str 判断之前返回：rdflib.BNode 继承自 str，
    # 落进下面那个分支会被转成 Literal，匿名节点就不再是匿名节点了
    if isinstance(value, BNode):
        return value
    if isinstance(value, str) and value.startswith("http"):
        return URIRef(value)
    if isinstance(value, str):
        return Literal(value)
    return value


def _engine():
    triples = [
        (f"{T}Widget", RDF.type, f"{T}Thing"),
        (f"{T}Widget", RDFS.label, "部件"),
        (f"{T}Gadget", RDFS.subClassOf, f"{T}Widget"),
        (f"{T}Gadget", RDFS.label, "小装置"),
        (f"{T}w1", RDF.type, f"{T}Widget"),
        (f"{T}g1", RDF.type, f"{T}Gadget"),
        (f"{T}w1", f"{T}uses", f"{T}g1"),
    ]
    return _FakeEngine(triples)


def _minimal_adapter():
    from reasoner.semantic import SemanticConfig

    class A(AdapterBase):
        CAPABILITIES = ("capability_match",)

        def __init__(self, engine):
            self.engine = engine
            self.c = SemanticConfig(
                top_classes=["Widget"],
                hidden_label_classes=[],
                graph_groups={"Thing": "Widget"},
            )

        def capability_match(self, *a, **k):
            return {}

    return A(_engine())


def test_default_explain_shape():
    a = _minimal_adapter()
    a.last_query_kind = "capability_match"
    a.last_derivation = [{"text": "推导"}]
    assert a.explain() == {"query_kind": "capability_match", "derivation": [{"text": "推导"}]}


def test_default_explain_before_any_query():
    a = _minimal_adapter()
    assert a.explain() == {"query_kind": None, "derivation": []}


def test_default_graph_export_walks_config_only():
    out = _minimal_adapter().graph_export()

    class_names = [c["name"] for c in out["classes"]]
    assert class_names == ["Widget", "Gadget"]          # 顶层类 + 子类
    assert out["classes"][1]["parent"] == "Widget"
    assert out["classes"][1]["label"] == "小装置"        # label 走 rdfs:label

    groups = {i["name"]: i["group"] for i in out["individuals"]}
    assert groups == {"w1": "Thing", "g1": "Thing"}

    edges = [(e["source"], e["target"], e["property"]) for e in out["edges"]]
    assert edges == [("w1", "g1", "uses")]              # 结构谓词不成边
    assert out["edges"][0]["inferred"] is False


def test_default_graph_export_marks_inferred_edges():
    a = _minimal_adapter()
    a.engine.g.add((_NS.g1, _NS.uses, _NS.w1))          # 只在 g、不在 raw → 推理产物
    inferred = [e for e in a.graph_export()["edges"] if e["source"] == "g1"]
    assert inferred and inferred[0]["inferred"] is True


def test_default_graph_export_ignores_materialization_noise():
    """owlrl 物化会补两类噪音：自反的 X ⊑ X / owl:Nothing ⊑ X，以及 sameAs 自反边。

    两者都不是领域知识，出图时必须滤掉——这是 examples/_minimal 用真实
    小本体跑出来的（假图单元测试看不出来），在此钉死防回归。
    """
    a = _minimal_adapter()
    a.engine.g.add((_NS.Widget, RDFS.subClassOf, _NS.Widget))     # 自反
    a.engine.g.add((_NS.Nothing, RDFS.subClassOf, _NS.Widget))    # Nothing ⊑ X
    a.engine.g.add((_NS.w1, OWL.sameAs, _NS.w1))                  # sameAs 自反

    out = a.graph_export()
    assert [c["name"] for c in out["classes"]] == ["Widget", "Gadget"]
    assert [(e["source"], e["target"], e["property"]) for e in out["edges"]] == [
        ("w1", "g1", "uses")]


def test_adapter_can_override_defaults():
    class A(AdapterBase):
        def graph_export(self):
            return {"classes": [], "individuals": [], "edges": [], "custom": True}

    assert A().graph_export()["custom"] is True


def _adapter_with(engine, top=("Widget",)):
    """用给定引擎装配一个最小适配器（只测默认实现，不测业务）。"""
    from reasoner.semantic import SemanticConfig

    class A(AdapterBase):
        CAPABILITIES = ("capability_match",)

        def __init__(self):
            self.engine = engine
            self.c = SemanticConfig(
                top_classes=list(top), hidden_label_classes=[], graph_groups={},
            )

        def capability_match(self, *a, **k):
            return {}

    return A()


def test_default_graph_export_skips_anonymous_subclass():
    """匿名类不得作为类层次的一层出现。

    owl:equivalentClass 在 OWL RL 推理后会拆成两条 subClassOf，匿名端点
    （owl:Restriction）于是作为主语进入 subjects(subClassOf, cls)。
    若不过滤 BNode，图谱里会冒出 `N34ea94cb…` 这种名字的"类"——
    这是 examples/fault_diag 的 CriticalFault（owl:hasValue 定义）照出来的，
    agent_task 与 _minimal 都没有匿名类，所以一直没暴露。
    """
    anon = BNode()
    engine = _FakeEngine([
        (f"{T}Widget", RDF.type, f"{T}Thing"),
        (f"{T}Widget", RDFS.label, "部件"),
        (anon, RDFS.subClassOf, f"{T}Widget"),        # 等价类拆出的匿名子类
        (f"{T}Widget", OWL.equivalentClass, anon),
    ])

    names = [c["name"] for c in _adapter_with(engine).graph_export()["classes"]]
    assert names == ["Widget"]


def test_default_graph_export_nests_multi_level_hierarchy():
    """多级类层次的 parent 必须指向直接父类。

    OWL RL 会把 subClassOf 做成传递闭包：Widget 下面能同时查到 Gadget 和
    SubGadget（因为 SubGadget ⊑ Gadget ⊑ Widget 被推出 SubGadget ⊑ Widget）。
    默认实现若把 subjects 的结果全部当作"子类"，三级层次就会被压平——
    SubGadget 的 parent 写成 Widget。同时只展开两代还会让第三级整个消失。
    agent_task 的类层次只有一级，这个洞由 fault_diag 的
    Pump ⊑ Equipment ⊑ Asset 照出。
    """
    engine = _FakeEngine([
        (f"{T}Widget", RDFS.label, "部件"),
        (f"{T}Gadget", RDFS.subClassOf, f"{T}Widget"),
        (f"{T}Gadget", RDFS.label, "小装置"),
        (f"{T}SubGadget", RDFS.subClassOf, f"{T}Gadget"),
        (f"{T}SubGadget", RDFS.label, "子装置"),
        # 推理闭包会补出这条（这里手写以模拟推理后的图）
        (f"{T}SubGadget", RDFS.subClassOf, f"{T}Widget"),
        # 物化噪音，一并验证不干扰层级判断
        (f"{T}Widget", RDFS.subClassOf, f"{T}Widget"),
        (f"{T}Nothing", RDFS.subClassOf, f"{T}Widget"),
    ])

    parents = {c["name"]: c["parent"]
               for c in _adapter_with(engine).graph_export()["classes"]}
    assert parents == {"Widget": None, "Gadget": "Widget", "SubGadget": "Gadget"}

