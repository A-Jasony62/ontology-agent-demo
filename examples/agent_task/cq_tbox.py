"""CQ 驱动 TBox 建模入口（agent_task 领域包，白名单纪律内、零 LLM 依赖）。

分工：demo 不内置 LLM，承担「prompt 规范器 + 验证工位」——
  - guide_tbox_draft：CQ → 生成指令（prompt）+ 现有 schema 对照 + 自查清单，
    宿主（MCP 调用方的 LLM）据此生成 Turtle 草稿；
  - validate_tbox_draft：服务端校验草稿（L1-L5 分级），返回 verdict 与修复建议。

反例守护：validate 只评 TBox 本身的可加载性/一致性/公理表达力，
不替宿主构造 ABox 断言（与评测 Harness「语料防污染」同一纪律）。

模板与领域术语来自 cq_prompts.json（可编辑，与 config.json / derivation.json 同风格）。
"""

from __future__ import annotations

import json
import os

import owlrl
from rdflib import Graph, Literal, OWL, RDF, RDFS, URIRef

from reasoner.engine import _resolve_ns, local

_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_DIR, "cq_prompts.json"), encoding="utf-8") as _f:
    _P = json.load(_f)

# rdf/rdfs/owl/xsd 元谓词（导出 schema_map 时排除）
_META_PRED = {
    "type", "subClassOf", "subPropertyOf", "label", "comment", "domain", "range",
    "equivalentClass", "equivalentProperty", "disjointWith", "intersectionOf",
    "unionOf", "complementOf", "oneOf", "first", "rest", "someValuesFrom",
    "allValuesFrom", "hasValue", "onProperty", "Cardinality", "Restriction",
}


def _schema_map(engine) -> dict:
    """从现有本体导出类/属性短名与 label（供 guide 参照）。"""
    g = engine.g
    classes = []
    for c in sorted(set(g.subjects(RDF.type, OWL.Class)), key=str):
        if not isinstance(c, URIRef):
            continue
        classes.append({
            "name": local(c),
            "label": engine.label(c) if hasattr(engine, "label") else local(c),
        })
    prop_iris = set()
    for s in g.subjects(RDF.type, OWL.ObjectProperty):
        if isinstance(s, URIRef):
            prop_iris.add(s)
    for s in g.subjects(RDF.type, OWL.DatatypeProperty):
        if isinstance(s, URIRef):
            prop_iris.add(s)
    for _s, p, _o in g:
        if isinstance(p, URIRef) and local(p) not in _META_PRED:
            prop_iris.add(p)
    return {"classes": classes, "properties": sorted(local(x) for x in prop_iris)}


def guide_tbox_draft(engine, cqs) -> dict:
    """把 CQ 清单规范化为宿主生成指令 + schema 对照 + 自查清单。"""
    cq_lines = "\n".join(f"- {c}" for c in cqs) if cqs else "- （未提供，请从领域需求补充）"
    axiom_hints = "\n".join(
        f"  - {k}: {v}" for k, v in _P["axiom_patterns"].items())
    prompt = (
        f"{_P['format_instruction']}\n"
        f"命名空间建议：{_P['namespace_hint']}\n"
        f"公理模式提示：\n{axiom_hints}\n"
        f"待建模能力问题（CQ）：\n{cq_lines}"
    )
    return {
        "prompt": prompt,
        "schema_map": _schema_map(engine),
        "checklist": _P["checklist"],
        "namespace_hint": _P["namespace_hint"],
        "format_instruction": _P["format_instruction"],
    }


def _extract_terms(g: Graph) -> tuple[list, list]:
    """提取 TBox 中的类与属性短名（类=owl:Class 主体；属性=Object/DatatypeProperty 主体或非元谓词）。"""
    classes = [local(c) for c in g.subjects(RDF.type, OWL.Class) if isinstance(c, URIRef)]
    prop_iris = set()
    for s in g.subjects(RDF.type, OWL.ObjectProperty):
        if isinstance(s, URIRef):
            prop_iris.add(s)
    for s in g.subjects(RDF.type, OWL.DatatypeProperty):
        if isinstance(s, URIRef):
            prop_iris.add(s)
    for _s, p, _o in g:
        if isinstance(p, URIRef) and local(p) not in _META_PRED:
            prop_iris.add(p)
    return classes, sorted(local(x) for x in prop_iris)


def validate_tbox_draft(ttl: str, cqs: list[str] | None = None) -> dict:
    """服务端校验草稿（L1-L5 分级），返回 verdict（pass / fixable / reject）。

    cqs 可选：提供时 L4 按 CQ 关键词推断「期望公理」，缺失则 fixable；不提供时
    L4 只做类层次成形检查（宽松）。
    """
    g = Graph()
    try:
        g.parse(data=ttl, format="turtle")
    except Exception as exc:  # L1 语法
        return {
            "verdict": "reject", "level": "L1", "valid_syntax": False,
            "error": f"语法解析失败：{exc}",
        }

    # L2 命名空间与最小结构
    try:
        ns = _resolve_ns("", g, use_xml_base=False)
    except Exception as exc:
        return {"verdict": "reject", "level": "L2", "valid_syntax": True,
                "valid_ns_resolved": False, "error": f"默认命名空间推导失败：{exc}"}
    classes, props = _extract_terms(g)
    if not classes or not props:
        return {"verdict": "fixable", "level": "L2", "valid_syntax": True,
                "valid_ns_resolved": True, "ns": ns, "classes": classes, "properties": props,
                "consistent": None, "issues": ["缺少 owl:Class 或 owl:ObjectProperty（至少各 1 个）"]}

    # L4 公理素材采集（必须在 owlrl 物化前：expand 会重写 propertyChainAxiom 的列表结构）
    chains = []
    for _s, _p, lst in g.triples((None, OWL.propertyChainAxiom, None)):
        cur = lst
        seq = []
        while cur is not None and cur != RDF.nil:
            f = g.value(cur, RDF.first)
            if f is None:
                break
            seq.append(local(f))
            cur = g.value(cur, RDF.rest)
        chains.append(seq)
    trans = [local(p) for p in g.subjects(RDF.type, OWL.TransitiveProperty)]
    subclass_count = len(list(g.triples((None, RDFS.subClassOf, None))))

    # L3 一致性：owlrl 物化无异常 + 显式 TBox 冲突检测
    #（owlrl 对 disjointWith ∧ subClassOf 矛盾不推 Nothing——需显式比对；Nothing 自反不计）
    consistent = True
    consistency_err = None
    try:
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
    except Exception as exc:
        consistent = False
        consistency_err = f"物化异常：{exc}"
    if consistent:
        nothing_sub = sorted(
            local(s) for s, _p, _o in g.triples((None, RDFS.subClassOf, OWL.Nothing))
            if isinstance(s, URIRef) and s != OWL.Nothing
        )
        disjoint_conflict = [
            f"{local(x)} ⊑/⊒ {local(y)} 与 disjointWith 冲突"
            for x, _p, y in g.triples((None, OWL.disjointWith, None))
            if (x, RDFS.subClassOf, y) in g or (y, RDFS.subClassOf, x) in g
        ]
        if nothing_sub:
            consistent = False
            consistency_err = f"一致性问题：类被推出为 ⊑ owl:Nothing：{nothing_sub}"
        elif disjoint_conflict:
            consistent = False
            consistency_err = "一致性问题：" + "；".join(disjoint_conflict)

    # L4 判定（公理表达力，CQ 感知：提供 cqs 时按关键词期望对应公理）
    axiom_smoke = {
        "property_chain_axioms": chains,
        "transitive_properties": trans,
        "subclass_edges": subclass_count,
    }
    smoke_issue = None
    if subclass_count == 0:
        smoke_issue = "类层次缺失：没有任何 rdfs:subClassOf 关系"
    elif cqs:
        joined = "".join(cqs)
        wanted = []
        if any(k in joined for k in ("谁能", "谁来", "can_execute", "可以执行")):
            wanted.append(("property_chain", bool(chains)))
        if any(k in joined for k in ("依赖", "传递", "depends", "传播")):
            wanted.append(("transitive", bool(trans)))
        if any(k in joined for k in ("约束", "认证", "冲突", "disjoint", "禁止", "合规")):
            wanted.append(("disjoint", bool(list(g.subjects(OWL.disjointWith, None)))))
        missing = [name for name, present in wanted if not present]
        if missing:
            smoke_issue = "公理缺失（对照 CQ 期望）：" + "、".join(missing)

    # L5 术语覆盖（对照 schema_terms，缺项列表化）
    covered, missing = [], []
    for tc in _P["schema_terms"]["classes"]:
        if tc in classes:
            covered.append(tc)
        else:
            missing.append(f"class:{tc}")
    for tp in _P["schema_terms"]["properties"]:
        if tp in props:
            covered.append(tp)
        else:
            missing.append(f"property:{tp}")

    issues = []
    if not consistent:
        issues.append(f"一致性问题：{consistency_err}")
    if smoke_issue:
        issues.append(smoke_issue)
    if missing:
        issues.append("术语覆盖缺失（建议补齐）：" + "、".join(missing))

    verdict, level = "pass", "L5"
    if not consistent:
        verdict, level = "fixable", "L3"
    elif smoke_issue:
        verdict, level = "fixable", "L4"
    # L5 术语覆盖缺失仅作建议提示，不单独阻断（coverage 报告供宿主补齐）

    return {
        "verdict": verdict, "level": level,
        "valid_syntax": True, "valid_ns_resolved": True,
        "consistent": consistent, "ns": ns,
        "classes": classes, "properties": props,
        "reasoning_smoke": {
            "property_chain_axioms": chains, "transitive_properties": trans,
            "subclass_edges": subclass_count,
        },
        "cq_coverage": {
            "covered_terms": sorted(covered), "missing_terms": missing,
        },
        "issues": issues,
        "suggestions": _fix_suggestions(issues),
    }


def _fix_suggestions(issues: list) -> list[str]:
    """模板化修复建议（供宿主 LLM 迭代）。"""
    out = []
    if any("类层次缺失" in i for i in issues):
        out.append("补充 rdfs:subClassOf 类层次（如 SimpleTask ⊑ Task）。")
    if any("公理表达力不足" in i for i in issues):
        out.append("按 CQ 补高阶公理：能力匹配用 propertyChainAxiom，依赖传递用 TransitiveProperty。")
    if any("术语覆盖" in i for i in issues):
        out.append("补齐缺失类/属性短名，保持命名空间一致。")
    if any("一致性" in i for i in issues):
        out.append("检查属性定义是否冲突（domain/range/互斥）。")
    return out