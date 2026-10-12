"""领域适配器注册表（domains 包）。

业务逻辑见 `registry.py`（list_domains / load_domain）；本文件只做导出，
保证 `from domains import load_domain` 等既有调用方式不变。
"""

from .registry import list_domains, load_domain

__all__ = ["list_domains", "load_domain"]
