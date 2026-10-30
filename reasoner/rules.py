"""自定义业务规则引擎 apply_rules：JSON IF-THEN 单步匹配 + 派生三元组导出（通用引擎层）。

把「报销超 1 万且无发票 → 需总监审批」这类散在制度文档里的 IF-THEN 条款机器化：

    when：条件模式列表（AND 语义）
        - 三元组模式 {s, p, o}：s 支持 ?变量 / 短名常量，p 为短名常量，
          o 支持 ?变量 / {gte|lte|eq: 数值} 算子 / 常量（短名 IRI 或字面量双匹配）
        - 反条件 {not_exists: {s, p, o}}：该模式在当前绑定下无任何匹配才成立
    then：结论模板列表：用绑定变量组装派生三元组（对象为字面量或变量值）

MVP 边界（显式声明）：
  - **单步执行**：所有规则对当前图各执行一轮，规则产物不作为其他规则的输入
    （天然规避规则环；多轮连锁列未来工作）；
  - **只读推导**：派生三元组仅导出不写回主图（物化基线 / diff_materialized
    语义 / facts_at 行为零影响）；
  - 新派生谓词可为本体未声明的新属性——报告显式标 `declared: false`（诚实提示）。

证明联动：派生结论附 proof 结构（mode / rule / axioms / premises / conclusion），
与 `reasoner.proof.build_proof` 键级对齐——`custom_rule:*` 是三类原生推理规则
（property_chain / transitive / class_membership）之外的第四类来源标识，
宿主 Agent 可用同一消费逻辑解析。

与既有能力的分工：validate_shapes 管「数据合不合格」（校验），本模块管「推出
新结论」（推导）；query_sparql 的 CONSTRUCT 是即席查询（写完即弃），本模块是
资产化规则（可复用 + 依据链自动附带 + 变量绑定）——三者互补不冲突。

规则文件惯例：领域包 `rules.json`（JSON 零依赖，与 config / derivation /
access_policy / cq_prompts 同风格）；加载入口 load_rules_from_domain()。
"""

from __future__ import annotations

import json
import os

from rdflib import OWL, Literal, RDF, URIRef

_OPERATORS = {"gte", "lte", "eq"}

# None = 按运行态配置解析 root（与 mcp/policy.py 同判据）；测试可显式赋值为具体目录
_DOMAINS_DIR: str | None = None


def _domains_dir() -> str:
    """领域包根目录：优先显式覆盖，否则取运行态配置（与 mcp/policy.py 同判据）。"""
    if _DOMAINS_DIR:
        return _DOMAINS_DIR
    try:
        from config import load_config

        return str(load_config().root)
    except Exception:  # noqa: BLE001 —— 配置不可用时退回历史位置，保持可诊断
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "domains")


def _short(x) -> str:
    s = str(x)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


# ---------------- 校验（fail-fast，指明规则 ID 与字段） ----------------

def _validate_pattern(pattern, where: str) -> None:
    if not isinstance(pattern, dict):
        raise ValueError(f"{where}：模式应为 JSON 对象，当前 {type(pattern).__name__}")
    if set(pattern) == {"not_exists"}:
        _validate_pattern(pattern["not_exists"], f"{where}.not_exists")
        return
    if not {"s", "p", "o"} <= set(pattern):
        raise ValueError(f"{where}：模式须含 s/p/o 三键（反条件用 not_exists 包裹）")
    for key in ("s", "p"):
        if not isinstance(pattern[key], str) or not pattern[key]:
            raise ValueError(f"{where}：{key} 须为非空字符串（?变量或短名）")
    if pattern["p"].startswith("?"):
        raise ValueError(f"{where}：谓词不支持变量绑定（p 须为短名常量）")
    o = pattern["o"]
    if isinstance(o, dict):
        ops = set(o) & _OPERATORS
        if not ops:
            raise ValueError(f"{where}：对象算子仅支持 {sorted(_OPERATORS)}，当前键 {sorted(o)}")
        if len(o) != 1:
            raise ValueError(f"{where}：对象算子一次只能一个（当前 {sorted(o)}）")


def validate_rules(rules) -> list:
    """结构校验：规则为 JSON 数组，每条含 id / when（非空）/ then（非空）。"""
    if isinstance(rules, dict) and "rules" in rules:
        rules = rules["rules"]
    if not isinstance(rules, list):
        raise ValueError(f"规则集应为 JSON 数组（或含 rules 键的对象），当前 {type(rules).__name__}")
    for i, rule in enumerate(rules):
        where = f"规则[{i}] {rule.get('id', '<未命名>') if isinstance(rule, dict) else '<非对象>'}"
        if not isinstance(rule, dict):
            raise ValueError(f"{where}：规则应为 JSON 对象")
        if not isinstance(rule.get("id"), str) or not rule["id"]:
            raise ValueError(f"{where}：缺 id（规则依据链引用它）")
        when = rule.get("when")
        if not isinstance(when, list) or not when:
            raise ValueError(f"{where}：when 须为非空模式列表")
        for j, pat in enumerate(when):
            _validate_pattern(pat, f"{where}.when[{j}]")
        then = rule.get("then")
        if not isinstance(then, list) or not then:
            raise ValueError(f"{where}：缺 then（结论模板列表，至少 1 条）")
        for j, tpl in enumerate(then):
            if not isinstance(tpl, dict) or not {"s", "p", "o"} <= set(tpl):
                raise ValueError(f"{where}.then[{j}]：结论模板须含 s/p/o 三键")
            if not isinstance(tpl.get("p"), str) or tpl["p"].startswith("?"):
                raise ValueError(f"{where}.then[{j}]：结论谓词须为非 ?变量字符串")
    return rules


def load_rules_from_domain(domain_name: str):
    """从领域包加载 rules.json；文件不存在返回 None（诚实的「未配置」）。"""
    path = os.path.join(_domains_dir(), domain_name, "rules.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"rules.json 解析失败（{path}）：{exc}") from exc
    return validate_rules(data)


# ---------------- 匹配（单步、只读） ----------------

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _py(obj):
    return obj.toPython() if isinstance(obj, Literal) else obj


def _operator_match(op: dict, obj) -> bool:
    """gte/lte/eq 算子判定：布尔严格相等；数值统一 float 比较；其余按字符串。"""
    (kind, want), = op.items()
    got = _py(obj)
    if isinstance(got, bool) or isinstance(want, bool):
        return got is want if kind == "eq" else False
    a, b = _num(got), _num(want)
    if a is not None and b is not None:
        return {"gte": a >= b, "lte": a <= b, "eq": a == b}[kind]
    if kind == "eq":
        return str(got) == str(want)
    return False


def _const_match(engine, term, obj) -> bool:
    """常量对象双匹配：短名 IRI（engine.NS）或字面量（str/bool/数字相等）。"""
    if isinstance(term, bool) or isinstance(term, (int, float)):
        return isinstance(obj, Literal) and _py(obj) == term
    if not isinstance(term, str):
        return False
    if isinstance(obj, URIRef):
        return str(obj) == str(engine.NS[term])
    if isinstance(obj, Literal):
        got = _py(obj)
        if isinstance(got, bool):
            return term in ("true", "false") and got is (term == "true")
        if _num(got) is not None and _num(term) is not None:
            return _num(got) == _num(term)
        return str(got) == term
    return False


def _iter_matches(engine, pattern: dict, binding: dict):
    """正模式在当前绑定下的全部解：产出 (新绑定, 匹配三元组)。"""
    s_term, p_term, o_term = pattern["s"], pattern["p"], pattern["o"]
    pred = engine.NS[p_term]
    for s, o in engine.g.subject_objects(pred):
        b = dict(binding)
        if isinstance(s_term, str) and s_term.startswith("?"):
            if s_term in b and b[s_term] != s:
                continue
            b[s_term] = s
        else:
            if s != engine.NS[s_term]:
                continue
        if isinstance(o_term, str) and o_term.startswith("?"):
            if o_term in b and b[o_term] != o:
                continue
            b[o_term] = o
        elif isinstance(o_term, dict):
            if not _operator_match(o_term, o):
                continue
        elif not _const_match(engine, o_term, o):
            continue
        yield b, (s, pred, o)


def _exists(engine, inner: dict, binding: dict) -> bool:
    return next(_iter_matches(engine, inner, binding), None) is not None


def _match_rule(engine, rule: dict) -> tuple[list[dict], list[list]]:
    """单规则单步匹配：返回 (全部绑定, 每个绑定对应的正模式事实链)。"""
    patterns = rule["when"]
    bindings: list[dict] = [{}]
    chains: list[list] = [[]]
    for pat in patterns:
        new_b, new_c = [], []
        if "not_exists" in pat:
            inner = pat["not_exists"]
            for b, chain in zip(bindings, chains):
                if not _exists(engine, inner, b):
                    new_b.append(b)
                    new_c.append(chain)  # 反条件不留事实链（absence 在 premises 单列）
        else:
            for b, chain in zip(bindings, chains):
                for nb, triple in _iter_matches(engine, pat, b):
                    new_b.append(nb)
                    new_c.append(chain + [triple])
        bindings, chains = new_b, new_c
        if not bindings:
            break
    return bindings, chains


def _report_value(engine, node) -> str:
    """节点 → 报告值：URIRef → 短名；Literal → Python 值。"""
    if isinstance(node, URIRef):
        return _short(node)
    if isinstance(node, Literal):
        v = node.toPython()
        return v if isinstance(v, (bool, int, float)) else str(v)
    return str(node)


def _declared(engine, pred_iri) -> bool:
    """结论谓词是否在本体声明（Object/DatatypeProperty）。"""
    for t in (OWL.ObjectProperty, OWL.DatatypeProperty, RDF.Property):
        if (pred_iri, RDF.type, t) in engine.raw or (pred_iri, RDF.type, t) in engine.g:
            return True
    return False


def apply_rules(engine, rules) -> dict:
    """对已物化图执行规则集（单步、只读），导出派生三元组报告（含 proof 依据链）。"""
    rules = validate_rules(rules)
    results, derived = [], []
    matched = 0
    for rule in rules:
        bindings, chains = _match_rule(engine, rule)
        # 结论按 (s, p, o) 聚合去重：多绑定命中同一结论时合并依据链
        by_key: dict = {}
        for b, chain in zip(bindings, chains):
            for tpl in rule["then"]:
                s_term, o_term = tpl["s"], tpl["o"]
                # 主体：绑定变量 → 结点；常量 → 短名 IRI
                if isinstance(s_term, str) and s_term.startswith("?"):
                    if s_term not in b:
                        continue  # 未绑定：不产出该结论（诚实，不臆造）
                    s_node = b[s_term]
                else:
                    s_node = engine.NS[s_term]
                pred = engine.NS[tpl["p"]]
                # 客体：绑定变量 → 结点（按图形报告）；字面量 → 原样 Python 值
                if isinstance(o_term, str) and o_term.startswith("?"):
                    if o_term not in b:
                        continue
                    obj_value = _report_value(engine, b[o_term])
                else:
                    obj_value = o_term
                subject_value = (_report_value(engine, s_node)
                                 if isinstance(s_node, URIRef) else str(s_node))
                key = (subject_value, _short(pred), str(obj_value))
                entry = by_key.setdefault(key, {
                    "subject": subject_value,
                    "predicate": _short(pred),
                    "object": obj_value,
                    "declared": _declared(engine, pred),
                    "premises": [],
                })
                # 汇入正模式事实（asserted / derived 分流），按三元组去重
                for ts, tp, to in chain:
                    premise = {
                        "subject": _short(ts), "predicate": _short(tp),
                        "object": _report_value(engine, to),
                        "source": "asserted" if (ts, tp, to) in engine.raw else "derived",
                    }
                    if premise not in entry["premises"]:
                        entry["premises"].append(premise)
                # 反条件以 absence 依据留痕（一条规则各留一次）
                for pat in rule["when"]:
                    if "not_exists" not in pat:
                        continue
                    inner = pat["not_exists"]
                    s_pat, o_pat = inner["s"], inner["o"]
                    abs_subject = (_short(b[s_pat]) if isinstance(s_pat, str)
                                   and s_pat.startswith("?") and s_pat in b else s_pat)
                    abs_object = (_short(b[o_pat]) if isinstance(o_pat, str)
                                  and o_pat.startswith("?") and o_pat in b else o_pat)
                    absence = {"subject": abs_subject, "predicate": inner["p"],
                               "object": abs_object, "source": "absence",
                               "note": "not_exists：图中无匹配事实"}
                    if absence not in entry["premises"]:
                        entry["premises"].append(absence)

        conclusions = sorted(by_key.values(),
                             key=lambda c: (str(c["subject"]), str(c["predicate"])))
        hit = bool(conclusions)
        if hit:
            matched += 1
        results.append({
            "rule_id": rule["id"],
            "description": rule.get("description", ""),
            "matched_bindings": len(bindings),
            "conclusions": [{
                "subject": c["subject"],
                "predicate": c["predicate"],
                "object": c["object"],
                "declared": c["declared"],
                "proof": {
                    "mode": "derived",
                    "rule": f"custom_rule:{rule['id']}",
                    "axioms": [{"id": rule["id"], "when": rule["when"], "then": rule["then"]}],
                    "premises": c["premises"],
                    "conclusion": {"subject": c["subject"], "predicate": c["predicate"],
                                   "object": c["object"]},
                },
            } for c in conclusions],
        })
        derived.extend({"rule_id": rule["id"], "subject": c["subject"],
                        "predicate": c["predicate"], "object": c["object"],
                        "declared": c["declared"]} for c in conclusions)
    return {
        "rules_loaded": len(rules),
        "matched": matched,
        "derived": derived,
        "results": results,
        "notes": "单步执行：规则产物不作为其他规则输入；派生结论不写回主图（只读推导）",
    }
