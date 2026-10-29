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
    在线编辑（v1.4.0：编辑模型 / 保存写回 / 下载）：
        GET  /api/ontology/edit-model   当前本体 → 结构化编辑模型 JSON（rdflib 全量提取）
        POST /api/ontology/save         编辑模型 → RDF/XML 写盘 + 重建引擎 + 重推理（new/overwrite）
        GET  /api/ontology/download     下载 data/uploads/ 内保存的本体文件（防路径穿越）
"""

import hashlib
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from rdflib import RDF, OWL


class LazyStaticFiles(StaticFiles):
    """允许挂载目录在运行时才出现（API 先于前端构建启动）。

    Starlette 的 StaticFiles(check_dir=False) 仅跳过【构造期】目录检查；
    lifespan 启动时仍会执行 check_config() 并 os.stat 目录，目录不存在会抛
    RuntimeError 导致服务启动失败。覆盖 check_config 为 no-op，使挂载
    真正延迟生效：目录出现后请求即自动可服务，无需重启。
    """

    async def check_config(self) -> None:
        pass

import reasoner.engine as engine_mod
from reasoner.engine import get_engine, OntologyEngine
from reasoner.protocol import missing_methods, supports
from domains import get_config, load_domain
from .schemas import (
    ReasonRequest, ClassifyRequest, RevokeRequest, ImportRequest,
    SparqlRequest, IndividualsRequest, TypesRequest, PropertyRequest,
    SaveOntologyRequest,
)

ENGINE = get_engine()
# 领域适配器：领域名由配置决定（domain.json / 环境变量 / --domain），不再写死
_DOMAIN_CONFIG = get_config()
DOMAIN_NAME = _DOMAIN_CONFIG.effective_default()
if DOMAIN_NAME is None:
    raise RuntimeError(
        f"未确定默认领域：{_DOMAIN_CONFIG.root} 下已安装 "
        f"{_DOMAIN_CONFIG.installed() or '（空）'}。\n"
        "请安装领域包：python scripts/ontologyctl.py domain install --from <path>；"
        "或在 config/domain.json 里设置 domains.default。"
    )
ADAPTER = load_domain(DOMAIN_NAME, ENGINE)
# 契约探测（P0-0）：启动时报告缺失方法，对应端点在请求时返 501 而不是 500
_ADAPTER_MISSING_AT_BOOT = missing_methods(ADAPTER)
if _ADAPTER_MISSING_AT_BOOT:
    print(
        f"[contract] 领域适配器 {getattr(ADAPTER, 'NAME', '?')} 未实现契约方法："
        f"{', '.join(_ADAPTER_MISSING_AT_BOOT)}（对应端点将返回 501）",
        file=sys.stderr,
    )
# 引擎加载时刻（reload 时更新；REQ-03 health 字段）
ENGINE_LOADED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")

app = FastAPI(
    title="本体 × 智能体协作 Demo API",
    description="智能体任务编排本体的推理 API：能力匹配 / 编排 / 冲突检测 / 推导链 + 通用本体查询 + 本体管理",
    version="1.4.0",
)

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


def _require_capability(capability: str):
    """领域端点门禁（P0-0）：适配器契约缺失返 501，能力未声明返 400。

    契约见 reasoner/protocol.py。此前的行为是直接调用方法——
    领域漏实现时抛 AttributeError → 500，错误信息对集成方毫无指引。
    """
    missing = missing_methods(ADAPTER)
    if capability in missing:
        raise HTTPException(
            status_code=501,
            detail=f"当前领域「{getattr(ADAPTER, 'NAME', '?')}」未实现契约方法 "
                   f"{capability}；缺失清单：{', '.join(missing)}",
        )
    if not supports(ADAPTER, capability):
        raise HTTPException(
            status_code=400,
            detail=f"当前领域「{getattr(ADAPTER, 'NAME', '?')}」未声明能力 {capability}",
        )


@app.get("/", include_in_schema=False)
def index():
    # 优先返回新前端（frontend/app/dist，Vite 构建产物）；
    # 未构建时给出明确提示，避免「静默回退旧页 → 误以为仍停在 demo 页」的误解
    if APP_DIST.exists() and (APP_DIST / "index.html").exists():
        return FileResponse(str(APP_DIST / "index.html"))
    return {
        "message": "工作台前端未构建：请先运行 cd frontend/app && npm install && npm run build，然后刷新页面",
        "hint": "API 已运行；前端构建完成后无需重启服务，直接刷新即可加载 /assets/*",
    }


def _baseline_hash() -> str:
    """本体基线（核心 .owl + extensions/ 全部文件）内容哈希——两端一致性判据。"""
    files = [engine_mod.ONTO_PATH]
    if ENGINE.extensions_dir and os.path.isdir(ENGINE.extensions_dir):
        files += [os.path.join(ENGINE.extensions_dir, f)
                  for f in sorted(os.listdir(ENGINE.extensions_dir))]
    h = hashlib.sha256()
    for f in files:
        with open(f, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


def _ontology_version() -> str:
    """本体版本：优先 owl:versionInfo，未配置时回退文件 mtime（REQ-03）。"""
    for obj in ENGINE.g.objects(None, OWL.versionInfo):
        return str(obj)
    return datetime.fromtimestamp(os.path.getmtime(engine_mod.ONTO_PATH)).isoformat(timespec="seconds")


@app.get("/api/health")
def health():
    # 顶层保留 v1.x 的 agents/tasks/assignments 字段（既有调用方兼容）；
    # 新增 REQ-03 字段：version / loaded_at / dirty / pending_changes / changelog / counts
    return {
        "status": "ok",
        "ontology": "agent_task_ontology.owl",
        "version": _ontology_version(),
        "loaded_at": ENGINE_LOADED_AT,
        "reasoner": "OWL 2 RL (owlrl) + 业务规则 R2/R4",
        "domain": ADAPTER.NAME,
        # P0-0 契约探针：空列表 = 适配器实现了全部框架要求的方法
        "contract": {
            "missing": missing_methods(ADAPTER),
            "declared": list(getattr(ADAPTER, "CAPABILITIES", [])) or None,
        },
        "dirty": ADAPTER.change_count > 0,
        "pending_changes": ADAPTER.change_count,
        "changelog": ADAPTER.changelog[-5:],
        "agents": len(ADAPTER.agents()),
        "tasks": len(ADAPTER.tasks()),
        "assignments": len(ADAPTER.assignments),
        "counts": {
            "agents": len(ADAPTER.agents()),
            "tasks": len(ADAPTER.tasks()),
            "capabilities": len(ADAPTER.engine.individuals_of(ADAPTER.c.capability_class)),
            "constraints": len(ADAPTER.engine.individuals_of(ADAPTER.c.constraint_class)),
            "assignments": len(ADAPTER.assignments),
            "inferred_triples": len(ENGINE.g) - len(ENGINE.raw),
        },
    }


@app.get("/api/ontology")
def ontology():
    _require_default_ontology()
    _require_capability("graph_export")
    return ADAPTER.graph_export()


@app.post("/api/reason")
def reason(req: ReasonRequest):
    _require_default_ontology()
    if req.type == "capability_match":
        _require_capability("capability_match")
        return ADAPTER.capability_match(_uri(req.task))
    if req.type == "orchestrate":
        _require_capability("orchestrate")
        return ADAPTER.orchestrate(_uri(req.task))
    if req.type == "assign":
        _require_capability("assign")
        return ADAPTER.assign(_uri(req.task), _uri(req.agent), persist=req.persist)
    raise HTTPException(status_code=400, detail=f"不支持的推理类型: {req.type}")


@app.post("/api/classify")
def classify(req: ClassifyRequest):
    _require_default_ontology()
    _require_capability("classify")
    return ADAPTER.classify(req.name, req.capabilities, req.constraints,
                            req.risk_level, persist=req.persist)


@app.post("/api/explain")
def explain():
    _require_default_ontology()
    _require_capability("explain")
    return ADAPTER.explain()


@app.post("/api/consistency")
def consistency():
    _require_default_ontology()
    _require_capability("consistency")
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
    """当前本体原始 RDF/XML 文本。

    本体文件缺失（如通用模式下文件被清理）时返回 404 + 结构化中文提示，
    避免前端误判"后端未启动"。
    """
    try:
        return {"filename": Path(ENGINE.onto_path).name, "content": ENGINE.source_xml()}
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=(
                f"当前本体文件不存在：{ENGINE.onto_path}。"
                "请重新加载本体（POST /api/ontology/load）或重启服务恢复默认本体。"
            ),
        )


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


# ---------------- 在线编辑（v1.4.0：编辑模型 / 保存写回 / 下载） ----------------

@app.get("/api/ontology/edit-model")
def edit_model():
    """当前本体 → 结构化编辑模型 JSON（任意 OWL 可提取，默认本体完整可编辑）。"""
    return ENGINE.edit_model()


@app.post("/api/ontology/save")
def save_ontology(req: SaveOntologyRequest):
    """保存编辑结果：编辑模型 → RDF/XML 写盘 → 重建引擎 + 重推理。

    mode=new    另存到 data/uploads/（进入通用模式，领域推理降级）；
    mode=overwrite  覆盖当前已加载本体（默认本体覆盖后领域推理保留）。
    """
    global ENGINE, ADAPTER
    try:
        content = ENGINE.model_to_rdf(req.model.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"编辑模型非法：{exc}")

    # 文件名安全：仅 basename + 白名单扩展名（防路径穿越 / 任意文件写入）
    if req.mode == "overwrite":
        target = Path(ENGINE.onto_path)
    else:
        raw_name = os.path.basename(req.filename or "")
        if not raw_name.lower().endswith((".owl", ".rdf", ".xml")):
            raw_name = f"{raw_name.rsplit('.', 1)[0] if '.' in raw_name else raw_name or 'edited'}.owl"
            if not raw_name.endswith(".owl"):
                raw_name = "edited.owl"
        stem, _, ext = raw_name.rpartition(".")
        safe_name = f"{stem}-{uuid.uuid4().hex[:8]}.{ext.lower()}"
        target = UPLOAD_DIR / safe_name

    try:
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"保存失败：{exc}")

    # 重建引擎（绕过单例缓存：直接构造新实例）并重绑定模块级引用
    try:
        new_engine = OntologyEngine(str(target), extensions_dir=None)
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"保存后加载失败（已回滚文件）：{exc}")

    engine_mod._engine = new_engine
    ENGINE = new_engine
    if new_engine.onto_path == engine_mod.ONTO_PATH:
        # 覆盖默认本体：重建领域适配器，R1–R4 领域推理保留
        ADAPTER = load_domain("agent_task", new_engine)

    materialized = new_engine.materialized()
    return {
        "status": "ok",
        "path": str(target),
        "filename": Path(target).name,
        "mode": req.mode,
        "stats": {
            "triples_before": materialized["stats"]["triples_asserted"],
            "triples_after": materialized["stats"]["triples_materialized"],
            "inferred_added": materialized["stats"]["inferred_added"],
            "classes": len(new_engine.classes()),
            "individuals": len(set(new_engine.g.subjects(RDF.type, OWL.NamedIndividual))),
        },
        "materialized": materialized,
    }


@app.get("/api/ontology/download")
def download_ontology(name: str):
    """下载 data/uploads/ 内保存的本体文件（仅允许该目录，防路径穿越）。"""
    safe = os.path.basename(name)
    path = UPLOAD_DIR / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在：{safe}")
    return FileResponse(
        path,
        media_type="application/rdf+xml",
        filename=safe,
    )


# ---------------- 本体管理（002 批次：热重载 / 状态 / 一致性） ----------------

@app.post("/api/ontology/reload")
def reload_ontology():
    """热重载（REQ-01.1）：重新加载核心 + extensions/ 全部增量并推理。

    原子性：新引擎构造 + 推理全部成功后才替换模块级 ENGINE / 重建 ADAPTER；
    失败返回 400，旧状态继续可用（Python 全局引用替换即原子，在途查询不受影响）。
    """
    global ENGINE, ADAPTER, ENGINE_LOADED_AT
    import time as _time
    t0 = _time.monotonic()
    try:
        new_engine = OntologyEngine(onto_path=engine_mod.ONTO_PATH,
                                    extensions_dir=ENGINE.extensions_dir)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"重载失败（旧状态保持可用）：{exc}")
    elapsed = round((_time.monotonic() - t0) * 1000, 2)
    # 全部成功 → 原子替换
    ENGINE = new_engine
    ADAPTER = load_domain("agent_task", new_engine)
    ENGINE_LOADED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "status": "ok",
        "loaded": os.path.basename(new_engine.onto_path),
        "triples": len(new_engine.g),
        "individuals": len(set(new_engine.g.subjects(RDF.type, OWL.NamedIndividual))),
        "elapsed_ms": elapsed,
    }


@app.get("/api/ontology/status")
def ontology_status():
    """本体状态与两端一致性（REQ-02/REQ-03）。

    判据：基线文件哈希（核心 .owl + extensions/）+ 内存变更计数。
    同一份基线哈希 + 相同 dirty/pending_changes 即两端一致
    （MCP 端由只读 status 工具 / CLI 探测，见批次二文档）。
    """
    return {
        "ontology": os.path.basename(engine_mod.ONTO_PATH),
        "mode": "default" if ENGINE.onto_path == engine_mod.ONTO_PATH else "generic",
        "extensions_dir": ENGINE.extensions_dir,
        "baseline_file_hash": _baseline_hash(),
        "dirty": ADAPTER.change_count > 0,
        "pending_changes": ADAPTER.change_count,
        "changelog": ADAPTER.changelog[-5:],
        "last_commit": ADAPTER.last_commit,
        "assignments": len(ADAPTER.assignments),
        "loaded_at": ENGINE_LOADED_AT,
    }


# ---------------- CRUD（003 批次 REQ-09：删除 / 撤回 / 批量导入） ----------------

@app.delete("/api/ontology/individual/{name}")
def delete_individual(name: str, persist: bool = False, cascade: bool = False):
    """删除个体（A-box 断言）。被引用时拒绝（除非 cascade=true）。

    删除后重推理：capability_match / consistency 随图断言同步更新；
    persist=true 写删除增量（-del- 文件），reload 可恢复删除状态。
    """
    _require_default_ontology()
    try:
        return ADAPTER.delete_individual(name, persist=persist, cascade=cascade)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ontology/revoke")
def revoke_assignment(req: RevokeRequest):
    """撤回分配：移除 assigned_to 图边，consistency 不再含该分配。"""
    _require_default_ontology()
    try:
        return ADAPTER.revoke(req.task, req.agent, persist=req.persist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ontology/import")
def import_individuals(req: ImportRequest):
    """批量导入任务个体（事务）：先全量校验（名称冲突/引用完整），
    全部通过才应用，部分失败整体回滚——不产生半套数据。
    """
    _require_default_ontology()
    try:
        return ADAPTER.import_individuals(
            [i.model_dump() for i in req.individuals], persist=req.persist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# 新前端静态资源（frontend/app/dist/assets）——始终挂载，不依赖启动时目录是否存在：
# API 先于前端构建启动时，LazyStaticFiles 跳过启动期目录检查；构建完成后请求即自动
# 可服务，无需重启（与 index() 的请求期动态判断保持一致）。
_assets_dir = APP_DIST / "assets"
app.mount(
    "/assets",
    LazyStaticFiles(directory=str(_assets_dir), check_dir=False),
    name="app-assets",
)
