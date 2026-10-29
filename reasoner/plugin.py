"""领域插件上下文：框架交给领域包的**唯一**入口。

为什么需要它：
    P1 之前领域包直接 `from reasoner.engine import local`、
    `from reasoner.semantic import load_domain_config`、`from reasoner.derivation import
    expand`、`from reasoner.abox import AboxStore`——四个内部模块各引一遍。
    于是框架每挪一次内部实现（比如 P1-2 把 ABox 从领域搬到框架），
    领域包就得跟着改 import。边界画在"包"上等于没画。

现在领域只 import 本模块（门面），用到什么从 ctx 上取：
    from reasoner.plugin import PluginContext

    def create_adapter_ctx(ctx: PluginContext):
        cfg = ctx.load_domain_config(ctx.path("config.json"))
        return MyAdapter(ctx, cfg)

    adapter.engine            # 通用引擎
    adapter.NS                # 命名空间
    ctx.local(iri)            # IRI → 短名
    ctx.expand(...)           # 推导链展开
    ctx.abox(...)             # ABox 事务仓库（业务谓词由领域声明）

兼容性：加载器优先调 `create_adapter_ctx(ctx)`，没有再退回
`create_adapter(engine, config)`。老领域包不用改就能继续加载
（见 domains/registry.load_domain）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from reasoner.abox import AboxStore
from reasoner.derivation import expand
from reasoner.engine import local, resolve_ns
from reasoner.protocol import AdapterBase
from reasoner.semantic import (
    SemanticConfig,
    load_derivation_config,
    load_domain_config,
)

__all__ = [
    "PluginContext",
    "AdapterBase",
    # 转发：领域常用、但不想为此 import 四个不同内部模块
    "AboxStore",
    "SemanticConfig",
    "load_domain_config",
    "load_derivation_config",
    "local",
    "resolve_ns",
    "expand",
]


class PluginContext:
    """框架能力的一次性交付：引擎 + 包目录 + 配置 + 原语 + 日志。"""

    def __init__(self, engine, *, base_dir: str | Path | None = None,
                 config: SemanticConfig | None = None, name: str | None = None,
                 logger: logging.Logger | None = None):
        self.engine = engine
        self.base_dir = Path(base_dir) if base_dir else None
        self.config = config
        self.name = name
        self.logger = logger or logging.getLogger(f"domain.{name or 'unknown'}")

    # ---------------- 构造入口 ----------------

    @classmethod
    def for_engine(cls, engine, config=None, **kw) -> "PluginContext":
        """没有包目录时的最小上下文（测试 / 旧式 create_adapter(engine, config)）。"""
        return cls(engine, config=config, **kw)

    @classmethod
    def for_module(cls, module, engine, config=None) -> "PluginContext":
        """从已加载的领域模块推导包目录与领域名。"""
        base = Path(module.__file__).parent if getattr(module, "__file__", None) else None
        return cls(engine, base_dir=base, config=config,
                   name=getattr(module, "NAME", None) or (base.name if base else None))

    # ---------------- 路径与配置 ----------------

    def path(self, *parts: str) -> str:
        """包内资源路径（base_dir 未知时抛错，不静默退化到 CWD）。"""
        if self.base_dir is None:
            raise ValueError("PluginContext 未绑定 base_dir，无法解析包内路径")
        return str(self.base_dir.joinpath(*parts))

    def load_domain_config(self, *parts: str):
        return load_domain_config(self.path(*parts))

    def load_derivation_config(self, *parts: str):
        return load_derivation_config(self.path(*parts))

    # ---------------- 引擎原语 ----------------

    @property
    def NS(self):
        return self.engine.NS

    def local(self, iri) -> str:
        return local(iri)

    def resolve_ns(self, g=None, **kw) -> str:
        return resolve_ns("", self.engine.raw if g is None else g, **kw)

    def expand(self, *args, **kw):
        return expand(*args, **kw)

    # ---------------- 事务仓库 ----------------

    def abox(self, *, resolve_predicate, reference_predicates=(),
             assignment_predicate=None) -> AboxStore:
        """ABox 事务仓库（P1-2）：框架管事务与落盘，领域声明哪些谓词算引用。"""
        return AboxStore(
            self.engine,
            resolve_predicate=resolve_predicate,
            reference_predicates=reference_predicates,
            assignment_predicate=assignment_predicate,
        )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<PluginContext {self.name!r} base_dir={self.base_dir}>"
