"""PluginContext 与领域-框架边界。

边界断言是这一批的验收核心：它把"领域不许 import 宿主模块"从口头约定
变成可执行断言——否则下次赶工时又会有人写
`from reasoner.engine import local`，然后边界悄悄消失。

P4 起这条线又挪了一次：门面本身搬进了 `ontology_plugin_sdk`（领域包唯一
允许依赖的包），所以断言也跟着从"只许 import reasoner.plugin"改成"不许
import 任何 reasoner.*"。
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

# 领域运行时核心：只允许 import ontology_plugin_sdk（P4 起）。
# 其余 .py（mcp.py / cq.py）是工具接线层，绑在宿主上跑，口径见对应测试。
DOMAIN_CORE_FILES = {"__init__.py", "adapter.py"}

# 工具接线层唯一被容忍的宿主依赖，理由写在该测试的 docstring 里。
ALLOWED_TOOL_LAYER_IMPORTS = {"reasoner.cq"}


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


def _all_domain_packages() -> list[Path]:
    """examples/ 下所有领域包（含 _minimal：它是零复制验收物，边界一样要守）。"""
    return sorted(p for p in (ROOT / "examples").iterdir()
                  if p.is_dir() and (p / "__init__.py").exists())


def test_domain_core_imports_only_sdk():
    """领域运行时核心（`__init__` / `adapter`）不得 import 任何 `reasoner.*`。

    P4 起领域包的唯一入口是 `ontology_plugin_sdk`。这条断言比 P1 那版
    （"只许 import reasoner.plugin"）更严——后者仍把领域锁在主仓库里，
    只是锁得文明一点：只要门面还在 `reasoner/` 下，领域就永远搬不出去。
    """
    offenders = {}
    for pkg in _all_domain_packages():
        for py in sorted(pkg.glob("*.py")):
            if py.name not in DOMAIN_CORE_FILES:
                continue
            for mod in _imported_modules(py):
                if mod == "reasoner" or mod.startswith("reasoner."):
                    offenders.setdefault(f"{pkg.name}/{py.name}", []).append(mod)

    assert not offenders, (
        f"领域核心文件 import 了宿主模块 {offenders}；"
        f"请改从 ontology_plugin_sdk 取（契约 / 配置 / 推导链 / ABox / 上下文）"
    )


def test_domain_core_actually_uses_sdk():
    """反向断言：核心文件必须真从 SDK 拿东西。

    只守"没有 reasoner.*"是不够的——把 import 全删了也能通过，但领域包
    显然不会因此变好。这条断言要求解耦是"换成 SDK"而不是"删掉不要"。
    """
    for pkg in _all_domain_packages():
        mods: set[str] = set()
        for py in sorted(pkg.glob("*.py")):
            if py.name in DOMAIN_CORE_FILES:
                mods |= _imported_modules(py)
        assert any(m == "ontology_plugin_sdk" or m.startswith("ontology_plugin_sdk.")
                   for m in mods), (
            f"{pkg.name} 的核心文件没有 import ontology_plugin_sdk——"
            f"领域包还是靠什么跑起来的？"
        )


def test_domain_tool_layer_only_extra_imports_cq():
    """工具接线层（`mcp.py` / `cq.py`）只允许再碰 `reasoner.cq` 一个宿主模块。

    为什么留这个口子而不是顺手搬走：CQ 生成是**建模期**工具（581 行，含
    prompts 拼装与 TBox 草稿校验），不是适配器运行时的依赖——`create_adapter`
    这条路径完全不碰它。塞进 SDK 会把"最小契约"变成"工具箱"，而领域真正
    该提供的只是 `cq_prompts.json` 这份数据。

    下一步（独立立项）：把 CQ 工具注册整体上移为宿主能力，领域只留数据文件，
    这个口子随之关闭。在那之前，用断言把它限制在"一个模块、且有理由"。
    """
    offenders = {}
    for pkg in _all_domain_packages():
        for py in sorted(pkg.glob("*.py")):
            if py.name in DOMAIN_CORE_FILES:
                continue
            for mod in _imported_modules(py):
                if (mod == "reasoner" or mod.startswith("reasoner.")) \
                        and mod not in ALLOWED_TOOL_LAYER_IMPORTS:
                    offenders.setdefault(f"{pkg.name}/{py.name}", []).append(mod)

    assert not offenders, (
        f"领域工具接线层 import 了 {offenders}；只允许 reasoner.cq"
        f"（领域自有工具应改用 ontology_plugin_sdk）"
    )
