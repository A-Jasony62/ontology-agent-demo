"""通用推导链规则解释器（引擎配套，与任何领域无关）。

把「查询结果 → 可解释步骤序列」的展开规则声明式地放在外部数据
（领域包 config.json 的 `derivations` 块），本模块只负责解释执行——
不含任何领域词汇，不依赖任何具体查询结果结构。

规则结构（JSON，步骤列表，每元素为以下三种之一）：
    - 生成步骤: {"step": {"kind": "fact|section|rule|conclusion",
                           "tpl": "模板key 或 $path引用",
                           "params": {"占位": "字面量 或 $path引用"}}}
    - 循环:     {"loop": "$path.list", "var": "x", "steps": [子步骤...]}
    - 条件:     {"if": "$path", "then": [子步骤...], "else": [子步骤...]}

值引用语法：以 `$` 开头的字符串按上下文点路径解析（如 `$m.i`、`$m.shared_capability_labels`），
            其余按字面量处理。循环的当前项通过 `var` 注入子上下文（可嵌套）。
模板插值：templates[tpl].format(**params)；tpl 也可为 `$path`（动态模板 key）。

用法：
    from ontology_plugin_sdk import expand
    steps = expand(derivations["capability_match"], ctx, templates)
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def resolve(path_or_literal: Any, ctx: Mapping[str, Any]) -> Any:
    """解析值：`$a.b.c` 按上下文点路径取值；其余原样返回。"""
    if isinstance(path_or_literal, str) and path_or_literal.startswith("$"):
        node: Any = ctx
        for part in path_or_literal[1:].split("."):
            try:
                node = node[part]
            except (KeyError, TypeError, IndexError):
                raise KeyError(
                    f"推导链规则引用 {path_or_literal!r} 无法解析（上下文键：{sorted(ctx)}）"
                ) from None
        return node
    return path_or_literal


def render_step(spec: Mapping[str, Any], ctx: Mapping[str, Any], templates: Mapping[str, str]) -> dict:
    """按步骤定义生成一条 {kind, content} 步骤。"""
    kind = resolve(spec["kind"], ctx)
    tpl_key = resolve(spec["tpl"], ctx)
    tmpl = templates.get(tpl_key)
    params = {k: resolve(v, ctx) for k, v in (spec.get("params") or {}).items()}
    return {
        "kind": kind,
        "content": tmpl.format(**params) if tmpl else f"[template:{tpl_key}]",
    }


def expand(rules: Sequence[Mapping[str, Any]], ctx: Mapping[str, Any],
           templates: Mapping[str, str]) -> list[dict]:
    """把声明式步骤规则展开为推导链步骤序列。"""
    out: list[dict] = []
    for rule in rules:
        if "step" in rule:
            out.append(render_step(rule["step"], ctx, templates))
        elif "loop" in rule:
            items = resolve(rule["loop"], ctx) or []
            for item in items:
                sub = dict(ctx)
                sub[rule["var"]] = item
                out.extend(expand(rule["steps"], sub, templates))
        elif "if" in rule:
            branch = resolve(rule["if"], ctx)
            out.extend(expand(rule["then"] if branch else rule.get("else", []), ctx, templates))
        else:
            raise ValueError(f"无法识别的推导链规则: {rule!r}")
    return out
