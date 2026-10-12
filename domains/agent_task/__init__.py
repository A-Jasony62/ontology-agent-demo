"""「智能体任务编排」领域包（domains/agent_task）。

业务逻辑见 `adapter.py`（AgentTaskAdapter / create_adapter / 领域数据常量）；
本文件只做导出，保证 `load_domain("agent_task", ...)` 与
`from domains.agent_task import AgentTaskAdapter, DEFAULT_CONFIG` 等既有调用方式不变。
"""

from .adapter import (
    NAME,
    DESCRIPTION,
    ONTO_FILE,
    DEFAULT_CONFIG,
    TEMPLATES,
    DERIVATIONS,
    AgentTaskAdapter,
    create_adapter,
)

__all__ = [
    "NAME",
    "DESCRIPTION",
    "ONTO_FILE",
    "DEFAULT_CONFIG",
    "TEMPLATES",
    "DERIVATIONS",
    "AgentTaskAdapter",
    "create_adapter",
]
