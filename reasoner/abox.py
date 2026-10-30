"""兼容层：实现已迁至 `ontology_plugin_sdk.abox`。

`AboxStore` 是 P1-2 从领域适配器上移到框架的那部分能力（事务、落盘、变更
计数、增量文件命名），本身不含任何领域词汇——所以它天然属于 SDK，而不是
某个具体应用。

注意这是**同一个类对象**的 re-export：`reasoner.abox.AboxStore` 与
`ontology_plugin_sdk.AboxStore` 指向同一处定义。任何复制式搬迁都会让
`isinstance` 在两侧给出不同答案。

新代码请从 SDK 导入（`from ontology_plugin_sdk import AboxStore`）。
"""

from ontology_plugin_sdk.abox import AboxStore  # noqa: F401

__all__ = ["AboxStore"]
