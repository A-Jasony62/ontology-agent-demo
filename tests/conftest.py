"""pytest 全局配置：把领域包按旧路径 `domains.<name>` 暴露给测试。

背景：P0 把示例领域从 `domains/` 移到 `examples/`，运行态由
`ontologyctl domain install` 重建。测试里 8 个文件共 13 行
`from domains.agent_task import ...`，要等 P2-4 才改成 fixture；
在那之前用**进程内别名**保持零改动 —— 不落盘、不产生磁盘 shim、
`domain list` 也看不见，pytest 进程结束即消失。

运行态准备（`_prepare_runtime`）：
  1. 已安装领域 → 直接用（本地按 README 走过 install 的常规情形）；
  2. 未安装（CI 干净检出）→ 把 `examples/<默认示例>` 复制到临时 root，
     用 `ONTOLOGY_DOMAINS_ROOT` 指向它。
  这样做同时满足两件事：干净检出可跑；测试的写操作落在临时副本上，
  不会污染 `examples/` 或运行态 `domains/`（P2-5 的隔离要求）。
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import load_config                        # noqa: E402
from domains import (                                 # noqa: E402
    DomainNotFoundError,
    load_domain_module,
    refresh_config,
)

DEFAULT_EXAMPLE = "agent_task"
_ALIAS_INFO = "(未初始化)"
_RUNTIME_ROOT: str | None = None


def _prepare_runtime() -> str:
    """确保存在可用的运行态 root；未安装时以临时副本兜底。"""
    global _RUNTIME_ROOT
    cfg = load_config()
    if cfg.effective_default() is not None:
        _RUNTIME_ROOT = str(cfg.root)
        return f"已安装（{_RUNTIME_ROOT}）"

    src = ROOT / "examples" / DEFAULT_EXAMPLE
    if not src.is_dir():
        _RUNTIME_ROOT = str(cfg.root)
        return f"未安装且无示例可回退（{cfg.root}）"

    root = Path(tempfile.mkdtemp(prefix="oat-test-domains-"))
    shutil.copytree(
        src,
        root / DEFAULT_EXAMPLE,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    os.environ["ONTOLOGY_DOMAINS_ROOT"] = str(root)
    refresh_config()                       # 清掉进程内配置缓存，重新按 env 解析
    _RUNTIME_ROOT = str(root)
    return f"未安装 → 临时副本（{root}）"


def _alias_domain_for_tests() -> str:
    cfg = load_config()
    name = cfg.effective_default() or DEFAULT_EXAMPLE
    try:
        module = load_domain_module(name, settings=cfg)
    except DomainNotFoundError:
        module = load_domain_module(name, root=ROOT / "examples")
    sys.modules[f"domains.{name}"] = module
    return f"{name} ← {module.__file__}"


def pytest_configure(config):
    global _ALIAS_INFO
    # 形状文件是仓库级资产（pipeline/shapes/），领域包被复制到临时 root 后
    # “上溯三级”已不等于仓库根，显式指路最稳。
    shapes = ROOT / "pipeline" / "shapes" / f"{DEFAULT_EXAMPLE}.ttl"
    if shapes.is_file():
        os.environ.setdefault("ONTOLOGY_SHAPES_FILE", str(shapes))

    state = _prepare_runtime()
    _ALIAS_INFO = f"{state} | {_alias_domain_for_tests()}"
    # 引擎的引导路径在 import 时按配置解析；此处只做一致性校验提示
    import reasoner.engine as engine_mod

    if not os.path.isfile(engine_mod.ONTO_PATH):
        _ALIAS_INFO += f" | !! ONTO_PATH 不可用：{engine_mod.ONTO_PATH}"


def pytest_report_header(config):
    return f"ontology domain: {_ALIAS_INFO}"
