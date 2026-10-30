"""P1-2 ABox 事务层测试：框架能力必须与领域无关。

用真实的 OntologyEngine + 直接构造 AboxStore（绕过 agent_task 适配器）验证：
  - reference_predicates 由调用方声明，框架不猜哪些谓词算引用；
  - 事务性：planner 抛错时内存与磁盘都不留半套数据；
  - 增量文件名协议（-del- 标记）与 extensions 缺失时的明确报错；
  - apply_triples 对 type / 字面量 / IRI 三类宾语的处理。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reasoner.abox import AboxStore  # noqa: E402
from reasoner.engine import NS, ONTO_PATH, OntologyEngine, local  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    """未挂 extensions 的 store：用于纯内存断言（落盘另测）。"""
    ext = tmp_path / "ext_mem"
    ext.mkdir(exist_ok=True)
    engine = OntologyEngine(ONTO_PATH, extensions_dir=str(ext))
    return AboxStore(
        engine,
        resolve_predicate=lambda key: NS[key],
        reference_predicates=("depends_on",),
        assignment_predicate="assigned_to",
    )


def test_delete_allows_when_referenced_by_undeclared_predicate(store):
    """assigned_to 引用不算"引用保护"——框架只看调用方声明的谓词。"""
    store.engine.add_type("abox_ref", "SimpleTask")
    store.engine.add_triple("t_login_dev", "assigned_to", "abox_ref")

    r = store.delete("abox_ref", cascade=False)     # depends_on 未引用它 → 放行
    assert r["deleted"] is True


def test_delete_blocks_declared_reference(store):
    with pytest.raises(ValueError, match="引用"):
        store.delete("t_login_dev")


def test_delete_cascade_removes_reference_edges(store):
    r = store.delete("t_login_dev", cascade=True)
    assert r["cascade"] is True and r["removed_triples"] > 0
    assert "t_login_dev" not in store.engine.individuals_of("SimpleTask")


def test_delete_missing_individual(store):
    with pytest.raises(ValueError, match="个体不存在"):
        store.delete("no_such_individual")


def test_revoke_requires_assignment_predicate(tmp_path):
    ext = tmp_path / "e2"
    ext.mkdir(exist_ok=True)
    engine = OntologyEngine(ONTO_PATH, extensions_dir=str(ext))
    bare = AboxStore(engine)
    with pytest.raises(ValueError, match="assignment_predicate"):
        bare.revoke("t_login_dev", "dev_agent")


def test_revoke_missing_assignment(store):
    with pytest.raises(ValueError, match="不存在分配"):
        store.revoke("t_login_dev", "dev_agent")


def test_revoke_removes_edge(store):
    store.engine.add_triple("t_login_dev", "assigned_to", "dev_agent")
    r = store.revoke("t_login_dev", "dev_agent")
    assert r["revoked"] is True
    assert ("t_login_dev", "dev_agent") not in store.engine.subject_objects("assigned_to")


# ---------------- 事务性 ----------------


def test_import_is_all_or_nothing(store):
    """planner 在第二条抛错 → 第一条的断言也不能进图。"""
    def planner(items):
        triples = []
        for i, item in enumerate(items):
            if i == 1:
                raise ValueError("第二条不合法（事务中止）")
            triples.append((item, "type", "SimpleTask"))
        return triples, list(items)

    with pytest.raises(ValueError, match="事务中止"):
        store.import_individuals(["abox_a", "abox_b"], planner=planner)
    assert "abox_a" not in store.engine.individuals_of("SimpleTask")


def test_import_empty_is_noop(store):
    before = (store.change_count, len(store.changelog))
    r = store.import_individuals([], planner=lambda items: ([], []))
    assert r == {"imported": 0, "individuals": [], "persisted": None}
    assert (store.change_count, len(store.changelog)) == before


def test_import_applies_triples_once(store):
    def planner(items):
        triples, names = [], []
        for name in items:
            names.append(name)
            triples.append((name, "type", "SimpleTask"))
            triples.append((name, "has_risk_level", 4))
            triples.append((name, "requires_capability", "Coding"))
        return triples, names

    r = store.import_individuals(["abox_c", "abox_d"], planner=planner)
    assert r["imported"] == 2
    assert "abox_c" in store.engine.individuals_of("SimpleTask")
    assert store.engine.objects_of("abox_d", "has_risk_level") == ["4"]
    assert store.engine.objects_of("abox_d", "requires_capability") == ["Coding"]
    assert store.change_count == 1          # 一次事务 = 一条 changelog


def test_change_count_resets_after_persist(tmp_path):
    ext = tmp_path / "ext"
    ext.mkdir(exist_ok=True)
    engine = OntologyEngine(ONTO_PATH, extensions_dir=str(ext))
    s = AboxStore(engine, resolve_predicate=lambda k: NS[k])
    s.note_change("assign", {"task": "x"}, None)
    assert s.change_count == 1 and s.last_commit is None

    persisted = s.write_increment("assign", "x", [("t_login_dev", "assigned_to", "dev_agent")])
    s.note_change("assign", {"task": "x"}, persisted)
    assert s.change_count == 0
    assert s.last_commit == persisted["path"]
    assert os.path.isfile(persisted["path"])


# ---------------- 落盘协议 ----------------


def test_write_increment_requires_extensions_dir(tmp_path):
    engine = OntologyEngine(ONTO_PATH, extensions_dir=str(tmp_path))
    engine.extensions_dir = None            # 模拟未启用扩展目录
    s = AboxStore(engine, resolve_predicate=lambda k: NS[k])
    with pytest.raises(ValueError, match="extensions"):
        s.write_increment("assign", "x", [])


def test_delete_increment_uses_del_marker(tmp_path):
    engine = OntologyEngine(ONTO_PATH, extensions_dir=str(tmp_path))
    s = AboxStore(engine, resolve_predicate=lambda k: NS[k])
    s.engine.add_triple("abox_tmp", "type", "SimpleTask")
    r = s.delete("abox_tmp", persist=True)
    name = os.path.basename(r["persisted"]["path"])
    assert "-del-" in name and name.endswith(".ttl")
    assert not os.path.exists(r["persisted"]["path"] + ".tmp")   # 原子写：不留临时文件


def test_apply_triples_handles_bool_and_iri(store):
    store.apply_triples([
        ("abox_e", "type", "SimpleTask"),
        ("abox_e", "has_certified", True),
        ("abox_e", "requires_capability", NS["Coding"]),
    ])
    assert "abox_e" in store.engine.individuals_of("SimpleTask")
    assert store.engine.objects_of("abox_e", "has_certified") == ["true"]   # rdflib 字面量小写
    assert store.engine.objects_of("abox_e", "requires_capability") == [local(NS["Coding"])]
