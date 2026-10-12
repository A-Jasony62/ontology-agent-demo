"""API 请求/响应模型。"""

from typing import Literal

from pydantic import BaseModel


class ReasonRequest(BaseModel):
    """结构化推理查询。"""

    type: Literal["capability_match", "orchestrate", "assign"]
    task: str = ""
    agent: str = ""


class ClassifyRequest(BaseModel):
    """新增任务个体并自动分类。"""

    name: str = ""
    capabilities: list[str] = []
    constraints: list[str] = []
    risk_level: int = 3


# ---------------- 通用查询接口（L1：与本体定义无关） ----------------

class SparqlRequest(BaseModel):
    """SPARQL SELECT 查询。"""

    sparql: str


class IndividualsRequest(BaseModel):
    """指定类（短名）的个体列表。"""

    class_name: str


class TypesRequest(BaseModel):
    """个体的推理后类型列表。"""

    individual: str


class PropertyRequest(BaseModel):
    """主体-属性 取值列表。"""

    subject: str
    property: str
