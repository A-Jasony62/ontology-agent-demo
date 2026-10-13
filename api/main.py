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
    本体管理（v1.3.0 起，通用层扩展）：
        POST /api/ontology/load         上传 .owl/.rdf 并加载到推理引擎（通用模式）
        GET  /api/ontology/materialized 物化 diff：原始断言 / 推理新增 / 统计
        GET  /api/ontology/source       当前本体原始 RDF/XML 文本
        GET  /api/ontology/export       导出物化后完整本体（turtle / rdfxml / n3）
"""

import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from rdflib import RDF, OWL

import reasoner.engine as engine_mod
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
    description="智能体任务编排本体的推理 API：能力匹配 / 编排 / 冲突检测 / 推导链 + 通用本体查询 + 本体管理",
    version="1.3.0",
)

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
APP_DIST = Path(__file__).resolve().parent.parent / "frontend" / "app" / "dist"
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _uri(name: str):
    if not name:
        raise HTTPException(status_code=400, detail="缺少参数：task / agent 不能为空")
    return ENGINE.NS[name]


def _require_default_ontology():
    """领域推理端点守卫：加载了自定义本体后进入通用模式，领域端点不可用。"""
    if ENGINE.onto_path != engine_mod.ONTO_PATH:
        raise HTTPException(
            status_code=400,
            detail="当前为通用模式（已加载自定义本体），领域推理仅默认本体可用；"
                   "图谱/物化/SPARQL 等通用能力不受影响。重启服务可恢复默认本体。",
        )


@app.get("/", include_in_schema=False)
def index():
    # 优先返回新前端（frontend/app/dist，Vite 构建产物）；未构建时回退旧单页
    if APP_DIST.exists() and (APP_DIST / "index.html").exists():
        return FileResponse(str(APP_DIST / "index.html"))
    if FRONTEND.exists():
        return FileResponse(str(FRONTEND))
    return {"message": "frontend 未构建，请先运行 frontend/app 下的 npm run build"}


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
    _require_default_ontology()
    return ADAPTER.graph_export()


@app.post("/api/reason")
def reason(req: ReasonRequest):
    _require_default_ontology()
    if req.type == "capability_match":
        return ADAPTER.capability_match(_uri(req.task))
    if req.type == "orchestrate":
        return ADAPTER.orchestrate(_uri(req.task))
    if req.type == "assign":
        return ADAPTER.assign(_uri(req.task), _uri(req.agent))
    raise HTTPException(status_code=400, detail=f"不支持的推理类型: {req.type}")


@app.post("/api/classify")
def classify(req: ClassifyRequest):
    _require_default_ontology()
    return ADAPTER.classify(req.name, req.capabilities, req.constraints, req.risk_level)


@app.post("/api/explain")
def explain():
    _require_default_ontology()
    return ADAPTER.explain()


@app.post("/api/consistency")
def consistency():
    _require_default_ontology()
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


# ---------------- 本体管理（v1.3.0：加载 / 物化 / 源码 / 导出） ----------------

@app.post("/api/ontology/load")
async def load_ontology(file: UploadFile = File(...)):
    """上传 .owl/.rdf 并加载到推理引擎（进入通用模式，领域推理降级）。"""
    global ENGINE
    filename = (file.filename or "").lower()
    if not filename.endswith((".owl", ".rdf", ".xml")):
        raise HTTPException(status_code=400, detail="仅支持 .owl / .rdf / .xml 文件")
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}.owl"
    try:
        dest.write_bytes(await file.read())
        engine = get_engine(str(dest))
        # 同步模块级单例引用：后续通用端点（查询/物化/源码）指向新本体
        ENGINE = engine
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"本体加载失败：{exc}")
    return {
        "status": "ok",
        "path": str(dest),
        "triples_before": len(engine.raw),
        "classes": len(engine.classes()),
        "individuals": len(set(engine.g.subjects(RDF.type, OWL.NamedIndividual))),
    }


@app.get("/api/ontology/materialized")
def materialized():
    """物化 diff：原始断言图 + 推理新增图 + 统计（通用，与领域无关）。"""
    return ENGINE.materialized()


@app.get("/api/ontology/source")
def ontology_source():
    """当前本体原始 RDF/XML 文本。"""
    return {"filename": Path(ENGINE.onto_path).name, "content": ENGINE.source_xml()}


@app.get("/api/ontology/export")
def export_ontology(format: str = "turtle"):
    """导出推理后完整本体（含物化三元组）。format: turtle / rdfxml / n3。"""
    try:
        content = ENGINE.export_graph(format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    media = "text/turtle" if format == "turtle" else "application/rdf+xml"
    suffix = "ttl" if format == "turtle" else "rdf"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="ontology.{suffix}"'},
    )


# 新前端静态资源（frontend/app/dist/assets）——存在时挂载
_assets_dir = APP_DIST / "assets"
if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="app-assets")
