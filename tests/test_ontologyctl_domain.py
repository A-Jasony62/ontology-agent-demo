"""`ontologyctl domain` 子命令测试：list / uninstall / use。

安装（install）由 `tests/test_installer.py` 覆盖，这里只测运维侧的三件事：
    - list：已安装清单要能回答"装的是哪份、本体与形状文件在哪"；
    - list --scan：候选目录只读盘点，且能区分"装过"与"装的是这份"；
    - uninstall：先备份再移除，且拒绝把当前默认领域卸掉（否则服务起不来）；
    - use：写的是配置文件而不是内存——三个进程（API/MCP/CLI）都读它。

全部使用 tmp_path，不碰真实运行态 domains/。
"""

import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

AGENT_TASK = os.path.join(ROOT, "examples", "agent_task")
MINIMAL = os.path.join(ROOT, "examples", "_minimal")


def _load_ctl():
    """按路径加载 scripts/ontologyctl.py（scripts/ 不是包）。"""
    path = os.path.join(ROOT, "scripts", "ontologyctl.py")
    spec = importlib.util.spec_from_file_location("ontologyctl_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ctl(tmp_path, monkeypatch):
    """CLI 模块 + 隔离的项目根（backups / config 都落在 tmp 里）。

    CI 干净检出时 `tests/conftest.py` 会设置 ONTOLOGY_DOMAINS_ROOT 指向临时
    领域副本；这里测的是 CLI 自己的配置解析，必须摘掉这两个环境变量，否则
    `_load_cfg` 会优先读 conftest 的临时 root。
    """
    mod = _load_ctl()
    monkeypatch.setattr(mod, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("ONTOLOGY_DOMAINS_ROOT", raising=False)
    monkeypatch.delenv("ONTOLOGY_DOMAIN", raising=False)
    return mod


@pytest.fixture
def runtime(tmp_path):
    """两个领域已安装的运行态 root。"""
    root = tmp_path / "domains"
    root.mkdir()
    for src, name in ((AGENT_TASK, "agent_task"), (MINIMAL, "minimal")):
        shutil.copytree(src, root / name, ignore=shutil.ignore_patterns("__pycache__"))
    return root


def _args(**kw):
    return argparse.Namespace(**kw)


# ---------------------------------------------------------------- list

def test_list_reports_paths_and_default(ctl, runtime):
    r = ctl._domain_list(_args(to=str(runtime), scan=None))

    assert r["ok"] is True
    names = {d["name"] for d in r["domains"]}
    assert names == {"agent_task", "minimal"}
    entry = next(d for d in r["domains"] if d["name"] == "agent_task")
    assert entry["onto_file"].endswith("agent_task_ontology.owl")
    # 形状文件随领域包走（P3-1）：list 要能直接回答它在哪
    assert entry["shapes_file"].endswith(os.path.join("shapes", "agent_task.ttl"))
    # 没有配置默认领域时（临时 root），谁都不是默认
    assert r["default"] is None
    assert all(d["is_default"] is False for d in r["domains"])


def test_list_scan_marks_candidates(ctl, runtime, tmp_path):
    scan_src = tmp_path / "candidates"
    scan_src.mkdir()
    shutil.copytree(AGENT_TASK, scan_src / "agent_task",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(MINIMAL, scan_src / "brand_new",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (scan_src / "not_a_package").mkdir()          # 没有 __init__.py → 不算候选

    r = ctl._domain_list(_args(to=str(runtime), scan=str(scan_src)))
    cands = {c["name"]: c for c in r["scan"]["candidates"]}

    assert set(cands) == {"agent_task", "brand_new"}
    assert cands["agent_task"]["installed"] is True
    assert cands["agent_task"]["up_to_date"] is True    # 内容一致
    assert cands["brand_new"]["installed"] is False


def test_scan_detects_stale_copy(ctl, runtime, tmp_path):
    """装过 ≠ 装的是这份：内容变了要能看出来（重新装是最常见的需求）。"""
    scan_src = tmp_path / "candidates"
    scan_src.mkdir()
    shutil.copytree(AGENT_TASK, scan_src / "agent_task",
                    ignore=shutil.ignore_patterns("__pycache__"))
    with open(scan_src / "agent_task" / "config.json", "a", encoding="utf-8") as f:
        f.write("\n")

    r = ctl._domain_list(_args(to=str(runtime), scan=str(scan_src)))
    cand = next(c for c in r["scan"]["candidates"] if c["name"] == "agent_task")
    assert cand["installed"] is True
    assert cand["up_to_date"] is False


def test_scan_missing_dir_is_reported(ctl, runtime):
    r = ctl._domain_list(_args(to=str(runtime), scan="/nonexistent/dir"))
    assert "error" in r["scan"]["candidates"][0]


# ---------------------------------------------------------------- uninstall

def test_uninstall_backs_up_before_removing(ctl, runtime):
    r = ctl._domain_uninstall(_args(name="minimal", to=str(runtime), force=False))

    assert r["ok"] is True
    assert not (runtime / "minimal").exists()
    # 备份不是"删掉"而是"挪走"：装错了还能拿回来
    assert os.path.isdir(r["backup"])
    assert os.path.isfile(os.path.join(r["backup"], "__init__.py"))
    assert r["installed_domains"] == ["agent_task"]


def test_uninstall_refuses_default_domain(ctl, runtime, tmp_path):
    """默认领域卸掉会让服务起不来——默认拒绝，--force 才放行。"""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "domain.json").write_text(
        json.dumps({"domains": {"root": str(runtime), "default": "agent_task"}}),
        encoding="utf-8",
    )

    blocked = ctl._domain_uninstall(_args(name="agent_task", to=str(runtime), force=False))
    assert blocked["ok"] is False
    assert "当前默认领域" in blocked["error"]
    assert (runtime / "agent_task").is_dir()

    forced = ctl._domain_uninstall(_args(name="agent_task", to=str(runtime), force=True))
    assert forced["ok"] is True


def test_uninstall_unknown_domain(ctl, runtime):
    r = ctl._domain_uninstall(_args(name="nope", to=str(runtime), force=False))
    assert r["ok"] is False
    assert "未安装" in r["error"]


# ---------------------------------------------------------------- use

def test_use_writes_default_to_config(ctl, runtime):
    r = ctl._domain_use(_args(name="minimal", to=str(runtime)))

    assert r["ok"] is True
    written = json.loads(open(r["config"], encoding="utf-8").read())
    assert written["domains"]["default"] == "minimal"
    # 以模板为基线：不能只写 default 一个字段，把 root/watch 顺手丢掉
    assert "root" in written["domains"]
    assert "MCP" in r["note"]                    # 明确告知 MCP 需重启


def test_use_rejects_unknown_domain(ctl, runtime):
    r = ctl._domain_use(_args(name="nope", to=str(runtime)))
    assert r["ok"] is False
    assert "未安装" in r["error"]


def test_use_preserves_existing_config_fields(ctl, runtime, tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    cfg = cfg_dir / "domain.json"
    cfg.write_text(json.dumps({
        "domains": {"root": str(runtime), "default": "agent_task",
                    "watch": {"enabled": True, "interval": 5.0}},
        "servers": {"api_port": 8123},
    }), encoding="utf-8")

    ctl._domain_use(_args(name="minimal", to=str(runtime)))
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["domains"]["default"] == "minimal"
    assert data["domains"]["watch"] == {"enabled": True, "interval": 5.0}
    assert data["servers"]["api_port"] == 8123


# ---------------------------------------------------------------- ensure / 首次安装默认

def test_ensure_installs_first_domain_and_sets_default(ctl):
    """干净运行态：ensure 安装来源并写默认，后续启动不再需要手工 use。"""
    r = ctl._domain_ensure(_args(
        src=AGENT_TASK, name=None, to=None, force=False, no_default=False,
    ))

    assert r["ok"] is True, r
    assert r["action"] == "installed"
    assert (Path(ctl.PROJECT_ROOT) / "domains" / "agent_task" / "__init__.py").is_file()
    cfg = json.loads(
        (Path(ctl.PROJECT_ROOT) / "config" / "domain.json").read_text(encoding="utf-8")
    )
    assert cfg["domains"]["default"] == "agent_task"

    # 第二次执行是 no-op，不会重复安装
    again = ctl._domain_ensure(_args(
        src=AGENT_TASK, name=None, to=None, force=False, no_default=False,
    ))
    assert again["ok"] is True
    assert again["action"] == "none"


def test_ensure_ambiguous_multiple_domains_fails_with_actionable_hint(ctl, runtime):
    """多个领域 + 无 default：明确报歧义，不静默挑一个。"""
    r = ctl._domain_ensure(_args(
        src=AGENT_TASK, name=None, to=str(runtime), force=False, no_default=False,
    ))

    assert r["ok"] is False
    assert r["action"] == "ambiguous"
    assert "domain use" in r["error"]
    assert "未指定默认领域" in r["error"]


def test_second_install_does_not_override_existing_default(ctl):
    """首次安装写默认；再装第二个领域时不能把用户已有的默认改掉。"""
    first = ctl._domain_install(_args(
        src=AGENT_TASK, name=None, to=None, force=False, no_default=False,
    ))
    assert first["ok"] is True
    cfg_path = Path(ctl.PROJECT_ROOT) / "config" / "domain.json"
    assert json.loads(cfg_path.read_text(encoding="utf-8"))["domains"]["default"] == "agent_task"

    second = ctl._domain_install(_args(
        src=MINIMAL, name=None, to=None, force=False, no_default=False,
    ))
    assert second["ok"] is True
    assert second.get("default") is None
    assert json.loads(cfg_path.read_text(encoding="utf-8"))["domains"]["default"] == "agent_task"


def test_ensure_repairs_stale_default(ctl):
    """配置里的 default 指向已删除领域：ensure 安装后要改回可用领域。"""
    cfg_dir = Path(ctl.PROJECT_ROOT) / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "domain.json").write_text(
        json.dumps({"domains": {"root": "domains", "default": "gone"}}),
        encoding="utf-8",
    )

    r = ctl._domain_ensure(_args(
        src=AGENT_TASK, name=None, to=None, force=False, no_default=False,
    ))

    assert r["ok"] is True, r
    assert r["default"] == "agent_task"
    cfg = json.loads((cfg_dir / "domain.json").read_text(encoding="utf-8"))
    assert cfg["domains"]["default"] == "agent_task"
