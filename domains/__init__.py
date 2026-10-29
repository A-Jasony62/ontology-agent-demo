"""领域适配器注册表（domains 包）。

业务逻辑见 `registry.py`；本文件只做导出，保证
`from domains import load_domain` 等既有调用方式不变。

新增导出：
    load_domain_module  返回模块本身（conftest 别名 / 需要包内子模块时）
    get_config          当前运行态配置（root / default / watch）
    refresh_config      重新读取配置
    DomainNotFoundError / DomainContractError  加载失败的明确分类
"""

from .registry import (
    DomainContractError,
    DomainNotFoundError,
    get_config,
    list_domains,
    load_domain,
    load_domain_module,
    refresh_config,
)

__all__ = [
    "DomainContractError",
    "DomainNotFoundError",
    "get_config",
    "list_domains",
    "load_domain",
    "load_domain_module",
    "refresh_config",
]
