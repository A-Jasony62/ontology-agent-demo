"""推理 API（FastAPI）：暴露本体的查询、推理与解释接口。

架构：通用引擎（reasoner.engine，与本体无关） + 领域适配器（domains/，运行时动态加载）。

端点一览：
    领域层（domains/agent_task 适配器，默认绑定「智能体任务编排」本体）：
        GET  /                 前端 Demo 页面（图谱展示）
        GET  /api/health       健康检查
        GET  /api/ontology     本体结构（图谱渲染数据）
        POST /api/reason       结构化推理（capability_match / orchestrate / assign）
        POST /api/classify     新增任务个体并自动分类
        POST /api/explain      最近一次推理的推导链
        POST /api/consistency  一致性 / 合规冲突检查
    通用层（引擎直接提供，与本体定义无关，任意 .owl 可用）：
        POST /api/query        SPARQL 查询
        POST /api/individuals  指定类的个体列表
        POST /api/classes      全部类层次
        POST /api/types        个体的推理后类型
        POST /api/property     主体-属性取值
        POST /api/infer        重新执行推理并返回统计
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from reasoner.engine import get_engine
from domains import load_domain
from .schemas import (
    ReasonRequest, ClassifyRequest,
    SparqlRequest, IndividualsRequest, TypesRequest, PropertyRequest,
)

ENGINE = get_engine()
# 领域适配器：运行时动态加载（domains/agent_task 为当前默认领域）
ADAPTER = load_domain("agent_task", ENGINE)

app = FastAPI(
    title="本体 × 智能体协作 Demo API",
    description="智能体任务编排本体的推理 API：能力匹配 / 编排 / 冲突检测 / 推导链 + 通用本体查询",
    version="1.2.0",
)

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


def _uri(name: str):
    if not name:
        raise HTTPException(status_code=400, detail="缺少参数：task / agent 不能为空")
    return ENGINE.NS[name]


@app.get("/", include_in_schema=False)
def index():
    if FRONTEND.exists():
        return FileResponse(str(FRONTEND))
    return {"message": "frontend/index.html 未找到，请先构建前端"}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "ontology": "agent_task_ontology.owl",
        "reasoner": "OWL 2 RL (owlrl) + 业务规则 R2/R4",
        "domain": ADAPTER.NAME,
        "agents": len(ADAPTER.agents()),
        "tasks": len(ADAPTER.tasks()),
        "assignments": len(ADAPTER.assignments),
    }


@app.get("/api/ontology")
def ontology():
    return ADAPTER.graph_export()


@app.post("/api/reason")
def reason(req: ReasonRequest):
    if req.type == "capability_match":
        return ADAPTER.capability_match(_uri(req.task))
    if req.type == "orchestrate":
        return ADAPTER.orchestrate(_uri(req.task))
    if req.type == "assign":
        return ADAPTER.assign(_uri(req.task), _uri(req.agent))
    raise HTTPException(status_code=400, detail=f"不支持的推理类型: {req.type}")


@app.post("/api/classify")
def classify(req: ClassifyRequest):
    return ADAPTER.classify(req.name, req.capabilities, req.constraints, req.risk_level)


@app.post("/api/explain")
def explain():
    return ADAPTER.explain()


@app.post("/api/consistency")
def consistency():
    return ADAPTER.consistency()


# ---------------- 通用查询接口（L1：与本体定义无关） ----------------

@app.post("/api/query")
def sparql_query(req: SparqlRequest):
    try:
        return {"results": ENGINE.query_sparql(req.sparql)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"SPARQL 执行失败: {exc}")


@app.post("/api/individuals")
def individuals(req: IndividualsRequest):
    return {"class": req.class_name, "individuals": ENGINE.individuals(req.class_name)}


@app.post("/api/classes")
def classes():
    return {"classes": ENGINE.classes()}


@app.post("/api/types")
def types(req: TypesRequest):
    return {"individual": req.individual, "types": ENGINE.types_of(req.individual)}


@app.post("/api/property")
def property_values(req: PropertyRequest):
    return {"subject": req.subject, "property": req.property,
            "values": ENGINE.property_values(req.subject, req.property)}


@app.post("/api/infer")
def infer():
    return ENGINE.infer()
