"""PluginContext 与领域-框架边界。

第八条用例是这一批的验收核心：它把"领域不许 import 框架内部模块"
从口头约定变成可执行断言——否则下次赶工时又会有人写
`from reasoner.engine import local`，然后边界悄悄消失。
"""

import ast
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reasoner.plugin import AboxStore, PluginContext  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOMAIN_PKG = ROOT / "examples" / "agent_task"

# 领域包允许直接 import 的框架符号（门面 + 可选的框架能力包）
ALLOWED_REASONER_IMPORTS = {"reasoner.plugin", "reasoner.cq"}


class _EngineStub:
    NS = {"x": "http://example.org/x#x"}
    raw = object()

    def __init__(self):
        self.g = object()


# ---------------- PluginContext ----------------

def test_for_module_derives_base_dir_and_name(tmp_path):
    pkg = tmp_path / "probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("NAME = 'probe'\n", encoding="utf-8")
    (pkg / "config.json").write_text("{}", encoding="utf-8")

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "domains.probe", pkg / "__init__.py", submodule_search_locations=[str(pkg)])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    ctx = PluginContext.for_module(mod, _EngineStub())
    assert ctx.base_dir == pkg
    assert ctx.name == "probe"
    assert Path(ctx.path("config.json")).is_file()


def test_path_without_base_dir_raises():
    ctx = PluginContext.for_engine(_EngineStub())
    with pytest.raises(ValueError, match="base_dir"):
        ctx.path("config.json")


def test_ctx_local_delegates_to_engine_primitive():
    from reasoner.plugin import local

    ctx = PluginContext.for_engine(_EngineStub())
    assert ctx.local("http://example.org/x#Widget") == local("http://example.org/x#Widget")


def test_ctx_abox_factory_returns_configured_store():
    ctx = PluginContext.for_engine(_EngineStub())
    store = ctx.abox(resolve_predicate=lambda k: k,
                     reference_predicates=("a", "b"), assignment_predicate="a")
    assert isinstance(store, AboxStore)


def test_ctx_logger_is_namespaced():
    ctx = PluginContext(_EngineStub(), name="probe")
    assert ctx.logger.name == "domain.probe"


# ---------------- 加载器对两种工厂的支持 ----------------

def _make_pkg(root, name, factory_src, extra=""):
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(
        f"NAME = {name!r}\nDESCRIPTION = 'd'\nCAPABILITIES = ()\n"
        + factory_src + "\n" + extra,
        encoding="utf-8")
    return pkg


# 适配器要过 P1-1 的契约校验：显式声明零能力，并带实例属性
_ADAPTER_CLASS = (
    "class _A:\n"
    "    CAPABILITIES = ()\n"
    "    def __init__(self, **kw): self.__dict__.update(kw)\n"
)

_CTX_FACTORY = (
    _ADAPTER_CLASS +
    "def create_adapter_ctx(ctx):\n"
    "    return _A(engine=ctx.engine, base_dir=ctx.base_dir, via='ctx')\n"
)
_OLD_FACTORY = (
    _ADAPTER_CLASS +
    "def create_adapter(engine, config=None):\n"
    "    return _A(engine=engine, via='legacy')\n"
)


def test_loader_prefers_ctx_factory(tmp_path):
    from config.loader import DomainConfig
    from domains import load_domain

    _make_pkg(tmp_path, "both", _CTX_FACTORY + _OLD_FACTORY)
    cfg = DomainConfig(root=tmp_path, default=None, watch_enabled=False,
                      watch_interval=0.0, sources={}, servers={})

    adapter = load_domain("both", _EngineStub(), settings=cfg)
    assert adapter.via == "ctx"
    assert adapter.base_dir == tmp_path / "both"


def test_loader_falls_back_to_legacy_factory(tmp_path):
    from config.loader import DomainConfig
    from domains import load_domain

    _make_pkg(tmp_path, "legacy", _OLD_FACTORY)
    cfg = DomainConfig(root=tmp_path, default=None, watch_enabled=False,
                      watch_interval=0.0, sources={}, servers={})

    assert load_domain("legacy", _EngineStub(), settings=cfg).via == "legacy"


def test_loader_rejects_package_without_any_factory(tmp_path):
    from config.loader import DomainConfig
    from domains import DomainContractError, load_domain

    _make_pkg(tmp_path, "empty", "")
    cfg = DomainConfig(root=tmp_path, default=None, watch_enabled=False,
                      watch_interval=0.0, sources={}, servers={})

    with pytest.raises(DomainContractError, match="create_adapter"):
        load_domain("empty", _EngineStub(), settings=cfg)


def test_installer_accepts_ctx_only_package(tmp_path):
    from domains.installer import validate_package

    pkg = _make_pkg(tmp_path, "ctxonly", _CTX_FACTORY)
    (pkg / "onto.owl").write_text(
        '<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>',
        encoding="utf-8")
    (pkg / "__init__.py").write_text(
        (pkg / "__init__.py").read_text(encoding="utf-8")
        + "ONTO_FILE = __file__.replace('__init__.py', 'onto.owl')\n",
        encoding="utf-8")

    info = validate_package(pkg)
    assert info["name"] == "ctxonly"


# ---------------- 架构约束：领域的 import 面 ----------------

def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


def test_domain_package_only_imports_facade():
    """领域包不得 import 框架内部模块——只能走 reasoner.plugin 门面（或 reasoner.cq）。"""
    offenders = {}
    for py in sorted(DOMAIN_PKG.glob("*.py")):
        for mod in _imported_modules(py):
            if mod.startswith("reasoner") and mod not in ALLOWED_REASONER_IMPORTS:
                offenders.setdefault(mod, []).append(py.name)

    assert not offenders, (
        f"领域包 import 了框架内部模块 {offenders}；"
        f"请改从 reasoner.plugin 取（门面转发了 local / expand / AboxStore / 配置加载器）"
    )
