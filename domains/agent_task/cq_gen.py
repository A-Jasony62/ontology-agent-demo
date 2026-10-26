"""CQ 自动出题器（agent_task 领域包，白名单纪律内、零 LLM 依赖）。

分工：demo 不内置 LLM，承担「出题指令生成 + 出题质检」两工位——
  - guide_cq_generation：生成宿主 LLM 出题指令（含 schema 对照、四类题型与建议配比、
    措辞规则、输出格式），宿主据此产出 CQ 问题数组；
  - validate_cqs：服务端确定性质检（格式/查重/类型预标/覆盖度），返回 usable /
    revise / duplicate 三档，供挑题人（人或维护者）终审。

设计动机（报告行动 13）：CQ 已从「建模前界定范围」升级为「生成→验收集成的判卷
标尺」（CQ4OE 基准 ★），且 LLM 出题覆盖度弱于领域专家、出题质量成为新瓶颈
（arXiv 2604.16258 ★）——所以出完必须过 validate 质检，不是出完就用。

反例守护：predicted_type 是建议标注（规则式启发，非权威判定）；dedup 仅对
既有的 008 cq_tests.json 题库（文件存在时）；服务端只做确定性质检，不替宿主
编造题目。

模板与题型定义来自 cq_prompts.json 的 cq_generation 段（可编辑，与
cq_prompts.json 既有 schema_terms / checklist 同风格同文件）。
"""

from __future__ import annotations

import json
import os
import re

from reasoner.engine import local

_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_DIR, "cq_prompts.json"), encoding="utf-8") as _f:
    _P = json.load(_f)
_GEN = _P.get("cq_generation", {})

# 008 cq_tests.json 题库文件（存在时作为查重对拍对象；不存在则 dedup.skipped）
_CQ_TESTS = os.path.join(_DIR, "cq_tests.json")

# 规则式类型预标：关键词 → 题型（LLM-free 可复现；中文问句启发匹配）
_TYPE_HINTS: list[tuple[str, str]] = [
    (r"几个|多少|共有|计数", "counting"),
    (r"为什么|如何|谁能|可以执行|能够|依赖|传递|冲突|禁止|合规|推导|由.*得来", "derived"),
    (r"不能|不可以|无法|不允许|哪些.*不", "negative"),
    (r"什么|哪些|是谁|是什么|哪", "retrieval"),
]

# 疑问句式判定（中文问号结尾 + 含疑问标记，二者居其一即视为问题句式）
_QUESTION_END = re.compile(r"[？?]\s*$")
_QUESTION_WORD = re.compile(r"哪些|什么|是谁|谁|几个|多少|能不能|可不可以|如何|怎样|怎么|是否")


def _normalize(text: str) -> str:
    """题干归一化（查重用：去空白与全部中英文标点、全小写）。

    「仅空格/标点差异」即视为同题（如『…能力？』vs『…能力！』），对齐
    方案验收口径：题干相同或仅空格/标点差异 → duplicate。
    """
    t = re.sub(r"[\s\u3000，。！？；：、,.!?;:'\"（）()\[\]【】]+", "", text.strip())
    return t.lower()


def _anchor_terms(cq: str) -> list[str]:
    """从题干提取 schema 中的类/属性术语锚点（命中即算锚点，用于过宽题判定）。"""
    terms = set(_P.get("schema_terms", {}).get("classes", []))
    terms |= set(_P.get("schema_terms", {}).get("properties", []))
    return sorted(t for t in terms if t.lower() in cq.lower())


def _predicted_type(cq: str) -> str:
    """规则式类型预标：按关键词命中次序给建议题型（retrieval 兜底）。"""
    for pattern, kind in _TYPE_HINTS:
        if re.search(pattern, cq):
            return kind
    return "retrieval"


def _is_question(cq: str) -> bool:
    """疑问句式判定：中文问号结尾 或 含疑问代词（二者满足其一即判疑问句式）。"""
    return bool(_QUESTION_END.search(cq) or _QUESTION_WORD.search(cq))


def _is_too_broad(cq: str, anchor_terms: list) -> bool:
    """过宽题判定：无 schema 术语锚点（无类/属性名词可答题）。"""
    return not anchor_terms


def _dedup_against_items(items: list) -> dict:
    """对既有题库（cq_tests.json 存在时）查重；不存在时如实跳过。

    items 可为 str 或 dict（含 cq 键）混合列表——与 validate_cqs 输入同型。
    撞题记录指向题库既有 case id（id / case_id 字段，缺省 None）。
    """
    cqs = [str(x) if not isinstance(x, dict) else str(x.get("cq", x))
           for x in items]
    if not os.path.exists(_CQ_TESTS):
        return {"against": "cq_tests.json", "skipped": True, "duplicates": []}
    try:
        with open(_CQ_TESTS, encoding="utf-8") as _f:
            bank = json.load(_f)
    except Exception:
        return {"against": "cq_tests.json", "skipped": True,
                "duplicates": [], "error": "题库解析失败，已跳过查重"}
    norm_bank: dict[str, str | None] = {}
    if isinstance(bank, list):
        for item in bank:
            if isinstance(item, dict):
                cq_text = str(item.get("cq", ""))
                case_id = item.get("id") or item.get("case_id")
            else:
                cq_text, case_id = str(item), None
            norm = _normalize(cq_text)
            if norm:
                norm_bank.setdefault(norm, case_id)
    dup = []
    for i, cq in enumerate(cqs):
        n = _normalize(cq)
        if n and n in norm_bank:
            dup.append({"cq": cq, "index": i, "against_id": norm_bank[n]})
    return {"against": "cq_tests.json", "skipped": False, "duplicates": dup}


def guide_cq_generation(engine=None, focus: str | None = None) -> dict:
    """生成宿主 LLM 出题指令（含 schema 对照、四类题型、建议配比、措辞规则、输出格式）。

    focus 可选：提供全新领域描述时降级为 from_description 模式（无既有 schema 对照，
    指令从领域描述出发仍完整可用）；未提供时为 schema_anchored 模式（engine 提供时
    导出真实 schema 术语对照）。
    """
    if focus:  # 全新领域：focus 描述即锚点来源，不对照既有 schema
        schema_terms: dict = {}
        mode = "from_description"
    else:
        schema_terms = {}
        if engine is not None and hasattr(engine, "g"):
            from .cq_tbox import _schema_map  # 复用既有 schema 导出（同风格）
            sm = _schema_map(engine)
            schema_terms = {
                "classes": [c["name"] for c in sm["classes"]],
                "properties": sm["properties"],
            }
        mode = ("schema_anchored"
                if schema_terms.get("classes") or schema_terms.get("properties")
                else "from_description")

    taxonomy_lines = "\n".join(
        f"  - {k}（{v}）" for k, v in _GEN["type_taxonomy"].items())
    mix_lines = "\n".join(f"  - {k}: {n} 题" for k, n in _GEN["suggested_mix"].items())
    rules_lines = "\n".join(f"  - {r}" for r in _GEN["phrasing_rules"])

    if mode == "schema_anchored":
        anchor_text = (
            "已有 schema 术语（题干必须至少用到其中 1 个）：\n"
            f"  - 类：{', '.join(schema_terms['classes'])}\n"
            f"  - 属性：{', '.join(schema_terms['properties'])}"
        )
    else:
        anchor_text = (
            f"全新领域（focus）：{focus or '未提供'}\n"
            "  无既有 schema 对照，请从领域描述出发提炼 6-8 个核心类与属性作为题干锚点，"
            "并在输出 JSON 的 anchor_terms 中显式声明。"
        )

    prompt = (
        f"你是在为『{_P.get('description', '')}』出能力问题（CQ）。请产出 {sum(_GEN['suggested_mix'].values())} 道\n"
        f"覆盖四类题型的 CQ（可直接用于本体能力评估）：\n\n"
        f"{anchor_text}\n\n"
        f"四类题型定义：\n{taxonomy_lines}\n\n"
        f"建议配比：\n{mix_lines}\n\n"
        f"措辞规则：\n{rules_lines}\n\n"
        f"输出格式：只输出 JSON 数组，元素为 {{'cq': 问题文本, 'expected_type': 题型, "
        f"'anchor_terms': [命中的类/属性短名]}}；严禁输出 JSON 以外的任何文字。"
    )

    return {
        "prompt": prompt,
        "schema_terms": schema_terms,
        "suggested_mix": _GEN["suggested_mix"],
        "mode": mode,
        "next_step": "将 LLM 输出的问题数组交给 validate_cqs 质检后再入题库",
    }


def validate_cqs(cqs: list) -> dict:
    """服务端确定性质检：格式 / 查重 / 类型预标 / 覆盖度报告。

    返回三档标注（usable / revise / duplicate）与覆盖度统计。predicted_type 为
    建议标注（非权威判定，终审是挑题的人）。
    """
    if not cqs:
        return {
            "total": 0, "usable": 0, "revise": 0, "duplicate": 0,
            "results": [], "coverage": {},
            "error": "空 CQ 列表：请先出题再质检（先调 guide_cq_generation 拿指令）。",
        }

    items = cqs if isinstance(cqs, list) else list(cqs)
    dedup = _dedup_against_items(items)
    dup_norm = {_normalize(d["cq"]) for d in dedup["duplicates"]}

    results = []
    seen: dict[str, int] = {}  # 本次输入内的同义去重（normalized -> index）
    for i, raw in enumerate(items):
        cq = str(raw) if not isinstance(raw, dict) else str(raw.get("cq", raw))
        cq = cq.strip()
        if not cq:
            results.append({"cq": cq, "status": "revise", "reason": "空题干"})
            continue
        anchor = _anchor_terms(cq)
        norm = _normalize(cq)

        # 内部重复 / 题库撞题
        if norm in seen:
            results.append({"cq": cq, "status": "duplicate",
                            "reason": f"与本次输入第 {seen[norm]+1} 题重复"})
            continue
        if norm in dup_norm:
            dup_id = next((d.get("against_id") for d in dedup["duplicates"]
                           if _normalize(d["cq"]) == norm), None)
            results.append({"cq": cq, "status": "duplicate",
                            "reason": "与既有题库撞题", "against_id": dup_id})
            continue

        # 句式 / 过宽
        if not _is_question(cq):
            results.append({"cq": cq, "status": "revise", "reason": "非问题句式：应为疑问句"})
            continue
        if _is_too_broad(cq, anchor):
            results.append({"cq": cq, "status": "revise", "reason": "过宽题：无 schema 术语锚点"})
            continue

        results.append({"cq": cq, "status": "usable",
                        "predicted_type": _predicted_type(cq),
                        "anchor_terms": anchor})
        seen.setdefault(norm, len(results) - 1)

    usable = [r for r in results if r["status"] == "usable"]
    revise = [r for r in results if r["status"] == "revise"]
    dup_list = [r for r in results if r["status"] == "duplicate"]

    # 覆盖度：按 usable 题目的 predicted_type 统计 + 缺口提醒
    coverage = {}
    if usable:
        dist = {}
        for r in usable:
            dist[r["predicted_type"]] = dist.get(r["predicted_type"], 0) + 1
        coverage = {"by_type": dist, "total": len(usable)}
        mix = _GEN["suggested_mix"]
        gaps = []
        for kind, want in mix.items():
            got = dist.get(kind, 0)
            if got < want:
                gaps.append(f"{kind} 偏少（建议 {want}，现有 {got}）")
        coverage["gaps"] = gaps if gaps else []

    return {
        "total": len(results),
        "usable": len(usable),
        "revise": len(revise),
        "duplicate": len(dup_list),
        "results": results,
        "coverage": coverage,
        "dedup": dedup,
    }