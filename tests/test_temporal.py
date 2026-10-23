"""时序 ABox（engine.facts_at 主体级 validFrom/validTo）测试。

覆盖：
  - 正例：validFrom 未过 → 今天活跃；at 早于 validFrom → 失效进 inactive
  - 反例：validTo 已过 → 失效（inactive 带 valid_to），原始三元组仍在（失效≠删除）
  - 边界：半开区间（at==from 活跃 / at==to 失效）、无时间戳永远活跃、非法格式 → warning
所有测试基于独立 engine 实例 add_literal/add_triple 构造，不落盘、不污染默认本体。
"""

from reasoner.engine import ONTO_PATH, OntologyEngine

PROP = "assigned_to"


def _engine():
    return OntologyEngine(ONTO_PATH)


def _assign(e, task, agent):
    e.add_triple(task, PROP, agent)


def _has_inactive(e, subject, at):
    return any(i["subject"] == subject for i in e.facts_at(PROP, at)["inactive"])


def test_valid_from_future_is_inactive():
    """正例：validFrom 在未来（今天查询 inactive），且原三元组仍在图中。"""
    e = _engine()
    _assign(e, "t_a", "dev_agent")
    e.add_literal("t_a", "validFrom", "2026-01-01")
    assert any(f["subject"] == "t_a" for f in e.facts_at(PROP)["facts"])        # 今天活跃
    assert _has_inactive(e, "t_a", "2025-06-01")                                 # 未来 → inactive
    # 原始三元组仍在（失效≠删除）
    assert ("t_a", "dev_agent") in e.subject_objects(PROP)


def test_valid_to_expired_goes_inactive_but_not_deleted():
    """反例：validTo 已过 → 今天 inactive（带 valid_to 说明），原始三元组仍可查。"""
    e = _engine()
    _assign(e, "t_b", "junior_dev")
    e.add_literal("t_b", "validTo", "2025-12-31")
    r = e.facts_at(PROP)
    assert not any(f["subject"] == "t_b" for f in r["facts"])
    hit = next((i for i in r["inactive"] if i["subject"] == "t_b"), None)
    assert hit is not None and hit["valid_to"] == "2025-12-31"
    # 失效 ≠ 删除：property_values 仍能读到原始边
    assert "junior_dev" in e.property_values("t_b", PROP)


def test_half_open_interval_boundaries():
    """边界①：半开区间 [from,to)——at==from 活跃、at==to 失效。"""
    e = _engine()
    _assign(e, "t_c", "dev_agent")
    e.add_literal("t_c", "validFrom", "2026-01-01")
    e.add_literal("t_c", "validTo", "2026-12-31")
    assert any(f["subject"] == "t_c" for f in e.facts_at(PROP, "2026-01-01")["facts"])   # at==from 活跃
    assert _has_inactive(e, "t_c", "2026-12-31")                                          # at==to 失效


def test_no_timestamp_always_active():
    """边界②：无时间戳事实 → 任意 at 均活跃（与现状行为一致）。"""
    e = _engine()
    _assign(e, "t_n", "dev_agent")
    for at in ("2025-01-01", "2026-10-23", "2099-01-01"):
        assert any(f["subject"] == "t_n" for f in e.facts_at(PROP, at)["facts"])


def test_invalid_format_warns_and_treats_as_untagged():
    """边界③：非法时间戳格式 → warning 显式返回 + 按未标注处理（诚实降级，不崩）。"""
    e = _engine()
    _assign(e, "t_w", "dev_agent")
    e.add_literal("t_w", "validFrom", "2026/1/1")
    r = e.facts_at(PROP)
    assert any("validFrom" in w for w in r["warnings"])
    assert any(f["subject"] == "t_w" for f in r["facts"])  # 按未标注处理 → 活跃


def test_default_at_is_today():
    """边界④：at 缺省 → 使用今天日期（date.today().isoformat()）。"""
    from datetime import date
    e = _engine()
    _assign(e, "t_d", "dev_agent")
    assert e.facts_at(PROP)["at"] == date.today().isoformat()