"""兼容层：领域门面已迁至 `ontology_plugin_sdk`。

P1 时这个文件是"领域包唯一允许 import 的宿主模块"，但它本身住在主仓库里——
领域要脱离主仓库就必须连门面一起搬。P4 把它搬进 SDK，这里只做 re-export。

为什么 `local` / `resolve_ns` 仍从 `reasoner.engine` 取：
    引擎的两个版本行为不同——`reasoner.engine.resolve_ns` 推导不出命名空间时
    兜底 `DEFAULT_NS`（本应用的常量），而 SDK 版本把它做成参数、兜底空串。
    门面按历史语义暴露引擎版本，避免"迁了 import 却变了行为"。
    新代码请直接用 `from ontology_plugin_sdk import ...`。

`PluginContext` 等其余符号与 SDK 是同一对象，不存在两套定义。
"""

from ontology_plugin_sdk.context import PluginContext, ToolRegistrar
from ontology_plugin_sdk.protocol import AdapterBase
from ontology_plugin_sdk.abox import AboxStore
from ontology_plugin_sdk.semantic import SemanticConfig, load_derivation_config, load_domain_config
from ontology_plugin_sdk.derivation import expand

from reasoner.engine import local, resolve_ns

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
    # P4 新增：MCP 工具注册面的最小契约
    "ToolRegistrar",
]
