"""兼容层：实现已迁至 `ontology_plugin_sdk.semantic`。

`SemanticConfig` / `DomainConfig` / `DerivationConfig` 与两个加载器现由 SDK
提供，本模块只做 re-export——不是复制。复制会让"配置对象是哪个类"在框架与
领域两侧分裂成两套，`isinstance` 判定随之失效。

新代码请从 SDK 导入；保留本模块是为了让框架内部与历史调用点不必在一次
改动里同步迁移（迁一个验一个，而不是一次性赌全部）。
"""

from ontology_plugin_sdk.semantic import (          # noqa: F401
    DerivationConfig,
    DomainConfig,
    SemanticConfig,
    load_derivation_config,
    load_domain_config,
)

__all__ = [
    "SemanticConfig",
    "DomainConfig",
    "DerivationConfig",
    "load_domain_config",
    "load_derivation_config",
]
