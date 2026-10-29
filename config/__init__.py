"""运行态配置包。

对外只暴露 loader 的三个入口；配置内容见 config/domain.json（本地）与
config/domain.example.json（模板）。
"""

from .loader import ConfigError, DomainConfig, check_domain_name, load_config

__all__ = ["ConfigError", "DomainConfig", "check_domain_name", "load_config"]
