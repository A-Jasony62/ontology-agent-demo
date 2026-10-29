"""领域包加载器：从配置指定的 root 加载任意位置的领域包。

与旧实现的差别（旧实现只能加载包内目录）：
    旧：importlib.import_module(f"domains.{name}")——只认 domains/ 下的子目录
    新：spec_from_file_location + submodule_search_locations——可加载任意路径，
        同时保持包语义，`from . import cq_gen` 之类相对导入仍然有效

为什么不直接用 `importlib.util.spec_from_file_location("x", "__init__.py")`：
    缺少 submodule_search_locations 时模块不是合法包，
    包内任何 `from .xxx import` 都会抛
    `ImportError: attempted relative import with no known parent package`。

模块命名约定：
    加载后的全名固定为 `domains.<name>`（无论物理位置在哪），
    这样子模块会自然注册为 `domains.<name>.mcp` 等，
    既有 `from domains.agent_task import mcp` 与 conftest 别名都无需特判。

约定（契约声明见 reasoner/protocol.py）：
    NAME          str    领域标识（缺省取目录名）
    DESCRIPTION   str    领域说明
    ONTO_FILE     str    本体文件名（可选，缺省在包内找 *.owl）
    CAPABILITIES  list   声明本领域提供哪些能力（声明即承诺，见下）
    create_adapter(engine, config=None) -> 适配器实例

CAPABILITIES 的三态语义（P1-1 起强制校验）：
    缺省 / None   视为全量能力 → 7 个契约方法缺一个就在加载时失败
    ("a", "b")    声明即承诺 → 清单内必须实现，清单外视为不提供
    ()            零能力领域（只有通用层端点可用）

用法：
    from domains import list_domains, load_domain, load_domain_module
    list_domains()                          # [{"name","description","module"}, ...]
    adapter = load_domain("agent_task", engine)
    mod = load_domain_module("agent_task")  # 需要模块本身时（conftest/测试）
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

from config import ConfigError, DomainConfig, load_config
from reasoner.protocol import undeclared_missing

__all__ = [
    "DomainContractError",
    "DomainNotFoundError",
    "default_onto_path",
    "get_config",
    "list_domains",
    "load_domain",
    "load_domain_module",
    "refresh_config",
]

_MODULE_PREFIX = "domains"
_cached_config: DomainConfig | None = None


class DomainNotFoundError(ConfigError):
    """root 下找不到指定的领域包。"""


class DomainContractError(ConfigError):
    """领域包存在，但不满足最小契约。"""


# ---------------------------------------------------------------- 配置


def get_config(refresh: bool = False) -> DomainConfig:
    """当前运行态配置（进程内缓存；refresh=True 重新读取文件）。"""
    global _cached_config
    if refresh or _cached_config is None:
        _cached_config = load_config()
    return _cached_config


def refresh_config() -> DomainConfig:
    """强制重新读取配置，返回新配置。"""
    return get_config(refresh=True)


# ---------------------------------------------------------------- 包加载


def _module_name(name: str) -> str:
    return f"{_MODULE_PREFIX}.{name}"


def _ensure_parent_package() -> None:
    """确保 `domains` 父包在 sys.modules 中（相对导入依赖它）。"""
    if _MODULE_PREFIX not in sys.modules:
        importlib.import_module(_MODULE_PREFIX)


def _snapshot(full: str) -> dict[str, ModuleType]:
    """记录某包及其全部子模块的当前模块对象，用于失败回滚。"""
    return {
        key: mod
        for key, mod in list(sys.modules.items())
        if key == full or key.startswith(full + ".")
    }


def _purge(full: str) -> None:
    for key in [
        key
        for key in list(sys.modules)
        if key == full or key.startswith(full + ".")
    ]:
        del sys.modules[key]


def _restore(snapshot: dict[str, ModuleType]) -> None:
    for key, mod in snapshot.items():
        sys.modules[key] = mod


def _package_dir(name: str, settings: DomainConfig | None, root: str | Path | None) -> Path:
    if root is not None:
        base = Path(root).expanduser().resolve()
        candidate = (base / name).resolve()
        try:
            candidate.relative_to(base)
        except ValueError as exc:  # 防御：理论上 name 已过 check_domain_name
            raise ConfigError(f"领域目录越界：{candidate} 不在 {base} 之内") from exc
        return candidate
    return (settings or get_config()).domain_dir(name)


def load_domain_module(
    name: str,
    *,
    settings: DomainConfig | None = None,
    root: str | Path | None = None,
    reload: bool = False,
) -> ModuleType:
    """把领域包加载为合法的 Python 包并返回模块对象。

    - 已从同一路径加载过且未要求 reload 时直接复用，避免类对象身份分裂
      （同一进程里出现两份 `AgentTaskAdapter` 会让 isinstance 判断失效）；
    - reload=True 先移除旧模块再重建，失败则整体回滚到加载前的状态。
    """
    pkg_dir = _package_dir(name, settings, root)
    init_py = pkg_dir / "__init__.py"
    if not init_py.is_file():
        hint = ""
        if root is None:
            installed = (settings or get_config()).installed()
            if installed:
                hint = f"；当前 root 下已安装：{', '.join(installed)}"
        raise DomainNotFoundError(
            f"找不到领域包 {name!r}：{init_py} 不存在{hint}"
        )

    full = _module_name(name)

    existing = sys.modules.get(full)
    if existing is not None and not reload:
        existing_file = getattr(existing, "__file__", None)
        if existing_file and Path(existing_file).resolve() == init_py.resolve():
            return existing

    _ensure_parent_package()
    snapshot = _snapshot(full)
    _purge(full)

    spec = importlib.util.spec_from_file_location(
        full,
        init_py,
        submodule_search_locations=[str(pkg_dir)],  # 缺这行，包内相对导入必炸
    )
    if spec is None or spec.loader is None:
        _restore(snapshot)
        raise DomainContractError(f"无法为领域包 {name!r} 构建导入规格：{init_py}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        _purge(full)
        _restore(snapshot)
        raise

    return module


# ---------------------------------------------------------------- 契约与工厂


def _validate_contract(name: str, module: ModuleType) -> None:
    if not callable(getattr(module, "create_adapter", None)):
        raise DomainContractError(
            f"领域包 {name!r} 未提供 create_adapter(engine, config=None)，"
            f"模块 {getattr(module, '__name__', '?')} 不满足最小契约"
        )


def load_domain(name: str, engine, config=None, *, settings: DomainConfig | None = None):
    """按标识加载领域适配器，并**在加载时**校验契约。

    config 是**领域自己的适配器配置**（原样传给 create_adapter），
    与运行态配置 DomainConfig（settings）不是一回事。

    契约校验（P1-1）：缺方法且未在 CAPABILITIES 里显式排除 →
    DomainContractError。把"漏实现"从"某个请求 500"提前到"启动即失败"，
    代价是新领域第一次跑起来就得把契约说清楚。
    """
    module = load_domain_module(name, settings=settings)
    _validate_contract(name, module)
    adapter = module.create_adapter(engine, config)
    _validate_adapter(name, adapter)
    return adapter


def _validate_adapter(name: str, adapter) -> None:
    missing = undeclared_missing(adapter)
    if not missing:
        return
    declared = getattr(adapter, "CAPABILITIES", None)
    hint = (
        "未声明 CAPABILITIES，视为要求全量能力"
        if declared is None
        else f"已声明 CAPABILITIES={list(declared)!r}，但清单内方法未实现"
    )
    raise DomainContractError(
        f"领域包 {name!r} 的适配器未满足契约：缺 {', '.join(missing)}（{hint}）。"
        f"契约见 reasoner/protocol.py；只想实现部分能力时，用 CAPABILITIES "
        f"把不实现的能力排除，或在 AdapterBase 上继承框架默认实现。"
    )


def list_domains(*, settings: DomainConfig | None = None) -> list[dict]:
    """枚举 root 下已安装的领域包。

    单个包加载失败不拖垮整体：该条带 error 字段，其余照常返回
    （线上排查时"哪个领域坏了"比"整张列表拿不到"有用得多）。
    """
    cfg = settings or get_config()
    out: list[dict] = []
    for entry in cfg.installed():
        item = {"name": entry, "description": "", "module": entry}
        try:
            module = load_domain_module(entry, settings=cfg)
            item["name"] = getattr(module, "NAME", entry)
            item["description"] = getattr(module, "DESCRIPTION", "")
            item["capabilities"] = list(
                getattr(module, "CAPABILITIES", [])
            ) or None
        except Exception as exc:  # noqa: BLE001 —— 单个包坏了不应影响枚举
            item["error"] = f"{type(exc).__name__}: {exc}"
        out.append(item)
    return out


# ---------------------------------------------------------------- 引导路径


def _declared_onto(ddir: Path) -> str | None:
    """读领域包 config.json 的 onto_file（显式声明优先于约定）。"""
    cfg_json = ddir / "config.json"
    if not cfg_json.is_file():
        return None
    try:
        data = json.loads(cfg_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    onto = data.get("onto_file") if isinstance(data, dict) else None
    if not isinstance(onto, str) or not onto.strip():
        return None
    base = ddir.resolve()
    target = (base / onto.strip()).resolve()
    try:
        target.relative_to(base)          # 拒绝 onto_file 把解析指到包外
    except ValueError:
        return None
    return str(target) if target.is_file() else None


def default_onto_path() -> str | None:
    """配置默认领域的核心本体路径（**不执行领域代码**）。

    供 reasoner.engine 解析 ONTO_PATH 的引导值。engine 是通用层，不能
    import 领域适配器——adapter 会反向 `from reasoner.engine import local`，
    形成循环导入。所以这里只做路径级解析：

      1. 领域包 config.json 的 `onto_file`（显式声明，优先）
      2. 包内唯一的 *.owl（约定：一个领域一个核心本体）

    两者都拿不到时返回 None，由调用方兜底并给出可读的错误。
    """
    cfg = get_config()
    name = cfg.effective_default()
    if not name:
        return None
    ddir = cfg.domain_dir(name)
    if not ddir.is_dir():
        return None
    declared = _declared_onto(ddir)
    if declared:
        return declared
    owls = sorted(
        p for p in ddir.glob("*.owl") if not p.name.startswith(".")
    )
    return str(owls[0].resolve()) if len(owls) == 1 else None
