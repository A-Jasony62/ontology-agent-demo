"""「智能体任务编排」领域包（domains/agent_task）。

业务逻辑见 `adapter.py`（AgentTaskAdapter / create_adapter / 领域数据常量）；
本文件只做导出，保证 `load_domain("agent_task", ...)` 与
`from domains.agent_task import AgentTaskAdapter, DEFAULT_CONFIG` 等既有调用方式不变。
"""

from .adapter import (
    NAME,
    DESCRIPTION,
    ONTO_FILE,
    EXTENSIONS_DIR,
    DEFAULT_CONFIG,
    TEMPLATES,
    DERIVATIONS,
    AgentTaskAdapter,
    create_adapter,
    # P1-4 起加载器优先探测 create_adapter_ctx。这里不导出它，加载器就永远
    # 读不到（getattr(module,...) 查的是本文件），于是悄悄退回老签名——
    # ctx 路径形同虚设，且 AgentTaskAdapter 拿到的 base_dir 是 None。
    create_adapter_ctx,
)

# 声明按哪一版领域插件 API 编写（P4）。加载器比对主版本，不匹配直接拒绝——
# 这项声明的意义不是"证明我兼容"，而是让版本冲突在加载时暴露，而不是在
# 某个请求进来时变成 AttributeError。
PLUGIN_API = "1"

__all__ = [
    "NAME",
    "PLUGIN_API",
    "DESCRIPTION",
    "ONTO_FILE",
    "EXTENSIONS_DIR",
    "DEFAULT_CONFIG",
    "TEMPLATES",
    "DERIVATIONS",
    "AgentTaskAdapter",
    "create_adapter",
    "create_adapter_ctx",
]
