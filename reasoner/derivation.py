"""兼容层：实现已迁至 `ontology_plugin_sdk.derivation`。

`expand` / `render_step` / `resolve` 三个纯函数现由 SDK 提供。它们与具体领域
无关、不碰任何状态，是这次搬迁里最没有争议的部分。

新代码请从 SDK 导入（`from ontology_plugin_sdk import expand`）。
"""

from ontology_plugin_sdk.derivation import expand, render_step, resolve  # noqa: F401

__all__ = ["expand", "render_step", "resolve"]
