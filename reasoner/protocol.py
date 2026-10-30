"""兼容层：实现已迁至 `ontology_plugin_sdk.protocol`。

为什么留这个文件而不是删掉：
    `api/main.py`、`domains/registry.py`、若干测试都在
    `from reasoner.protocol import ...`。删掉文件等于要求所有调用点在同一次
    改动里完成迁移，而"迁移对不对"无法在同一次提交里被独立验证。留 shim 后
    可以迁一个验一个：领域包先走 SDK（新路），框架内部再慢慢跟。

为什么是 re-export 而不是复制：
    `AdapterBase` 在全进程只有一个对象。任何"再定义一遍同名类"的写法都会让
    子类判定、`isinstance` 与注册表里的类型检查悄悄分裂成两套。

P4 之后 `reasoner.protocol` 不再是权威——新代码请从 SDK 导入。
"""

from ontology_plugin_sdk.protocol import *          # noqa: F401,F403
from ontology_plugin_sdk.protocol import __all__    # noqa: F401
