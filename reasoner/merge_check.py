"""模块合并冲突预检 merge_check：合并前的「冲突扫描仪」（通用引擎层，与任何领域无关）。

两个本体（团队词表 / 领域包）合并前先扫一遍三类冲突，把「上线后数据串味、
审计翻车才被发现」消灭在合并之前：

    ① 同 URI 异定义（conflict）—— 同一 IRI 在两边都声明为类/属性，但
      subClassOf / domain / range 签名存在差异（最危险：静默串数据）；
    ② 名称冲突（warning）—— 同 rdfs:label 或解除前缀后同短名，但 IRI 不同
      （两个「客户」各说各话，人看不出来机器会当同一个；需人工确认语义）；
    ③ 公理矛盾（conflict）—— incoming 中 X ⊑ B，current 中 X ⊑ A 且
      A disjointWith B（含对称）——合并即不相容。

MVP 边界（只体检、不合并）：处置决策（rename / align / skip）本质是人的语义
判断，工具只输出分级清单 + 动作化建议。实例级（ABox）冲突、SHACL shapes 冲突、
OWL 等价/传递链深扫、自动消歧列未来工作。

与 owlrl 物化的关系（互补层）：物化只暴露逻辑不相容（①③之外的语义矛盾），
暴露不了「同名不同义」（语义错位非逻辑矛盾）——三类扫描是物化覆盖不了的
合并方向检查。

用法：
    from reasoner.merge_check import compare, run_merge_check
    report = compare(current_graph, incoming_graph)      # 纯函数（两侧已解析）
    report = run_merge_check(engine.g, ttl_text)         # 解析 + 纯函数
"""

from __future__ import annotations

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef

# 参与签名比较的实体类型（元建模词汇；RDFS.Property 作超类兜底）
_ENTITY_KINDS = (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, RDF.Property)


def _short(x) -> str:
    s = str(x)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _entity_signatures(g: Graph) -> dict:
    """提取图中全部类/属性的实体签名：{iri: {kinds, parents, domains, ranges}}。"""
    sig: dict[URIRef, dict] = {}
    for kind in _ENTITY_KINDS:
        for s in g.subjects(RDF.type, kind):
            if not isinstance(s, URIRef):
                continue
            bucket = sig.setdefault(s, {"kinds": set(), "parents": set(),
                                        "domains": set(), "ranges": set()})
            bucket["kinds"].add(_short(kind))
    for iri, ent in sig.items():
        for o in g.objects(iri, RDFS.subClassOf):
            if isinstance(o, URIRef):
                ent["parents"].add(_short(o))
        for o in g.objects(iri, RDFS.domain):
            if isinstance(o, URIRef):
                ent["domains"].add(_short(o))
        for o in g.objects(iri, RDFS.range):
            if isinstance(o, URIRef):
                ent["ranges"].add(_short(o))
    return sig


def _view(ent: dict) -> dict:
    """签名的可读视图（集合 → 排序列表，输出友好）。"""
    return {k: sorted(v) for k, v in ent.items()}


def _signatures_differ(a: dict, b: dict) -> bool:
    return any(a[k] != b[k] for k in ("kinds", "parents", "domains", "ranges"))


def parse_rdf(content: str, format: str = "turtle") -> Graph:
    """解析外部本体文本（语法错误时异常信息来自 rdflib，含行列位置）。"""
    g = Graph()
    g.parse(data=content, format=format)
    return g


def compare(current: Graph, incoming: Graph) -> dict:
    """纯函数：两张已解析图的三类冲突扫描（只读，不改任何图）。

    返回 {summary, conflicts, warnings, info}：
      - summary.conflicts / warnings / info_additions 分级计数；
      - 每条冲突附 current vs incoming 双侧事实对照 + 动作化 suggestion
        （rename / align / skip 三选一模板）——「两个团队当面对齐一次就够」的
        会议材料直接可打。
    """
    cur = _entity_signatures(current)
    inc = _entity_signatures(incoming)
    overlap = sorted(iri for iri in cur if iri in inc)
    conflicts, warnings, info = [], [], []

    # ① 同 URI 异定义：签名（kinds/parents/domains/ranges）任一差异
    for iri in overlap:
        if _signatures_differ(cur[iri], inc[iri]):
            conflicts.append({
                "type": "same_uri_diff_definition",
                "entity": _short(iri),
                "current": _view(cur[iri]),
                "incoming": _view(inc[iri]),
                "suggestion": "align（两团队对齐语义后再合并）",
            })

    # ② 名称冲突：同 label 异 IRI、同短名异 IRI（warning：需人工确认是否同义）
    for label in sorted({str(l) for l in current.objects(None, RDFS.label)}
                        & {str(l) for l in incoming.objects(None, RDFS.label)}):
        cur_iris = {str(s) for s in current.subjects(RDFS.label, Literal(label))
                    if isinstance(s, URIRef)}
        inc_iris = {str(s) for s in incoming.subjects(RDFS.label, Literal(label))
                    if isinstance(s, URIRef)}
        new_iris = inc_iris - cur_iris   # 同 IRI 实体两侧同名：不是名称冲突（定义差异①已管）
        if not new_iris:
            continue
        warnings.append({
            "type": "same_label_diff_uri",
            "label": label,
            "current_iri": _short(sorted(cur_iris)[0]) if cur_iris else "?",
            "incoming_iri": _short(sorted(new_iris)[0]),
            "suggestion": "rename（消歧命名）或 align（确认是同一概念后对齐 IRI）",
        })
    cur_short: dict[str, str] = {_short(i): str(i) for i in cur}
    inc_short: dict[str, str] = {_short(i): str(i) for i in inc}
    for name in sorted(set(cur_short) & set(inc_short)):
        if cur_short[name] != inc_short[name]:  # 同短名不同 IRI（同 IRI 属 overlap）
            warnings.append({
                "type": "same_shortname_diff_uri",
                "short_name": name,
                "current_iri": _short(cur_short[name]),
                "incoming_iri": _short(inc_short[name]),
                "suggestion": "rename（各用带命名空间前缀的短名）或 align（若是同一概念）",
            })

    # ③ 公理矛盾：incoming X ⊑ B ∧ current X ⊑ A ∧ current (A disjointWith B | B disjointWith A)
    for x, _, b in incoming.triples((None, RDFS.subClassOf, None)):
        if not isinstance(b, URIRef):
            continue
        for a in current.objects(x, RDFS.subClassOf):
            if not isinstance(a, URIRef) or a == b:
                continue
            if (a, OWL.disjointWith, b) in current or (b, OWL.disjointWith, a) in current:
                conflicts.append({
                    "type": "disjoint_axiom_violation",
                    "entity": _short(x),
                    "via": [_short(a), _short(b)],
                    "suggestion": "skip（跳过导入该层级断言）或 align（人工裁定层级归属）",
                })

    # info：纯新增（current 中不存在的实体声明，归信息层不算冲突）
    for iri in sorted(iri for iri in inc if iri not in cur):
        info.append({"type": "addition", "entity": _short(iri), "note": "纯新增，无冲突"})

    return {
        "summary": {
            "incoming_triples": len(incoming),
            "overlap_entities": len(overlap),
            "conflicts": len(conflicts),
            "warnings": len(warnings),
            "info_additions": len(info),
        },
        "conflicts": conflicts,
        "warnings": warnings,
        "info": info,
    }


def run_merge_check(current: Graph, rdf_content: str, format: str = "turtle") -> dict:
    """入口：解析 incoming（语法错 fail-fast 返回 error 报告，不 crash）→ compare。"""
    try:
        incoming = parse_rdf(rdf_content, format)
    except Exception as exc:
        return {
            "error": f"RDF 解析失败（{format}）：{exc}",
            "summary": {"incoming_triples": 0, "overlap_entities": 0, "conflicts": 0,
                        "warnings": 0, "info_additions": 0},
            "conflicts": [], "warnings": [], "info": [],
        }
    return compare(current, incoming)
