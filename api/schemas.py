"""API 请求/响应模型。"""

from typing import Literal

from pydantic import BaseModel


class ReasonRequest(BaseModel):
    """结构化推理查询。"""

    type: Literal["capability_match", "orchestrate", "assign"]
    task: str = ""
    agent: str = ""
    persist: bool = False      # assign 增量落盘（REQ-05，001 批次能力经 API 暴露）


class ClassifyRequest(BaseModel):
    """新增任务个体并自动分类。"""

    name: str = ""
    capabilities: list[str] = []
    constraints: list[str] = []
    risk_level: int = 3
    persist: bool = False      # 增量落盘（REQ-05，001 批次能力经 API 暴露）


# ---------------- CRUD（003 批次 REQ-09） ----------------

class RevokeRequest(BaseModel):
    """撤回分配。"""

    task: str
    agent: str
    persist: bool = False


class ImportItem(BaseModel):
    """批量导入的单个任务个体（与 ClassifyRequest 同构）。"""

    name: str
    capabilities: list[str] = []
    constraints: list[str] = []
    risk_level: int = 3


class ImportRequest(BaseModel):
    """批量导入（事务：先全量校验，全部通过才应用）。"""

    individuals: list[ImportItem]
    persist: bool = False


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


# ---------------- 在线编辑（v1.4.0：编辑模型 / 保存写回） ----------------

class EditModelClass(BaseModel):
    """类：id / label / parent（直接父类短名）/ description。"""

    id: str
    label: str = ""
    parent: str | None = None
    description: str = ""


class EditModelObjectProp(BaseModel):
    """对象属性：id / label / domain / range / characteristics。"""

    id: str
    label: str = ""
    domain: str | None = None
    range: str | None = None
    characteristics: list[str] = []


class EditModelDataProp(BaseModel):
    """数据属性：id / label / domain / range（标量类型短名）。"""

    id: str
    label: str = ""
    domain: str | None = None
    range: str | None = None


class EditModelAssertion(BaseModel):
    """个体断言：属性取值（对象属性 → IRI 短名；数据属性 → 字面量）。"""

    prop: str
    value: str
    isObject: bool = False


class EditModelIndividual(BaseModel):
    """个体：id / label / types（类型断言）/ assertions（属性断言）。"""

    id: str
    label: str = ""
    types: list[str] = []
    assertions: list[EditModelAssertion] = []


class EditModel(BaseModel):
    """结构化编辑模型（后端 rdflib 提取 / 重建）。"""

    ontologyName: str = ""
    namespace: str = ""
    classes: list[EditModelClass] = []
    objectProps: list[EditModelObjectProp] = []
    dataProps: list[EditModelDataProp] = []
    individuals: list[EditModelIndividual] = []


class SaveOntologyRequest(BaseModel):
    """保存编辑结果：mode=new 另存（data/uploads/，通用模式）；mode=overwrite 覆盖当前本体。"""

    model: EditModel
    filename: str = ""
    mode: Literal["new", "overwrite"] = "new"
