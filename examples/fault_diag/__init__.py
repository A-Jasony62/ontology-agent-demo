"""「设备故障诊断」领域包（examples/fault_diag）。

第二个异构领域——用途是**证伪框架的通用性假设**，不是补充功能。
与 agent_task 的结构差异、以及本包照出来的框架缺口，见 adapter.py 顶部
的对照表与 docs/ 下的记录。

    fault_diag.owl   本体：Asset 层级 + 因果链 + CriticalFault 的 owl:hasValue 定义
    config.json      语义配置：类角色映射 + 图谱分组
    derivation.json  推导链文案与展开规则（与 agent_task 同格式）
    shapes/          SHACL 形状（维护手册完整性约束）
    adapter.py       业务逻辑：diagnose / consistency
"""

from .adapter import (
    CAPABILITIES,
    DESCRIPTION,
    NAME,
    ONTO_FILE,
    FaultDiagnosisAdapter,
    create_adapter,
    create_adapter_ctx,
)

# 声明按哪一版领域插件 API 编写（P4）：加载器比对主版本，不匹配即拒绝。
PLUGIN_API = "1"

__all__ = [
    "NAME",
    "PLUGIN_API",
    "DESCRIPTION",
    "ONTO_FILE",
    "CAPABILITIES",
    "FaultDiagnosisAdapter",
    "create_adapter",
    "create_adapter_ctx",
]
