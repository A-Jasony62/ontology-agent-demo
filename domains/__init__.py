"""领域适配器注册表（domains 包）。

业务逻辑见 `registry.py` / `manager.py`；本文件只做导出，保证
`from domains import load_domain` 等既有调用方式不变。

加载器（registry）：
    load_domain         取适配器（加载时校验契约）
    load_domain_module  返回模块本身（conftest 别名 / 需要包内子模块时）
    default_onto_path   默认领域的核心本体路径（供 reasoner 引导解析）
    package_onto_path   指定领域包的核心本体路径
    package_shapes_path 指定领域包的 SHACL 形状文件
    get_config          当前运行态配置（root / default / watch）
    refresh_config      重新读取配置
    DomainNotFoundError / DomainContractError  加载失败的明确分类

运行态管理器（manager，P2 起）：
    DomainManager       当前领域的唯一真相源，提供 activate / reload 热切换
    DomainHandle        一个已激活领域的不可变快照

注意：本包属于**引导链**——`reasoner/__init__.py` 会在 import 期固化
ONTO_PATH，而 ONTO_PATH 又依赖 `default_onto_path()`。因此本包任何模块都
不得在顶层 import reasoner.*，否则 CI 干净检出时引擎引导路径会被算错。
"""

from .manager import DomainHandle, DomainManager
from .registry import (
    DomainContractError,
    DomainNotFoundError,
    default_onto_path,
    get_config,
    list_domains,
    load_domain,
    load_domain_module,
    package_onto_path,
    package_shapes_path,
    refresh_config,
)

__all__ = [
    "DomainContractError",
    "DomainHandle",
    "DomainManager",
    "DomainNotFoundError",
    "default_onto_path",
    "get_config",
    "list_domains",
    "load_domain",
    "load_domain_module",
    "package_onto_path",
    "package_shapes_path",
    "refresh_config",
]
