"""通用语义配置（引擎配套，与任何领域无关）。

领域适配器用「类名 / 属性名 / 展示项」参数化对本体做语义查询；
本模块提供承载这些键值配置的通用容器与 JSON 加载器，不含任何领域词汇
（没有 Agent / Task / can_execute 等默认值——那些属于领域数据，见
`domains/<领域>/config.json`）。

用法：
    from ontology_plugin_sdk import load_domain_config, load_derivation_config

    cfg = load_domain_config("<领域包目录>/config.json")
    cfg.config.agent_class        # 语义配置（属性访问）

    der = load_derivation_config("<领域包目录>/derivation.json")
    der.templates                 # 推导链静态文案模板
    der.derivations               # 推导链展开规则

    # 运行时按需覆盖（返回新实例，原配置不可变）：
    alt = cfg.config.update(compliance_constraint_class="SecurityRequirement")

中文名（类/个体展示标签）统一由本体自带的 rdfs:label 提供（引擎 label()），
不再在配置中重复维护——owl 是中文名的唯一事实源。

领域包数据文件约定（均为独立 JSON）：
    config.json      语义配置（类角色映射 + 结构数据）→ load_domain_config
    derivation.json  推导链配置（templates 文案 + derivations 展开规则）→ load_derivation_config
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping


class SemanticConfig:
    """不可变的键值语义配置容器：属性 / 下标 / get 访问，支持整体覆盖。

    任意领域词汇均可承载（agent_class、task_class、has_capability……），
    字段集合由调用方（领域 config.json 或代码）决定，本类零预置字段。
    """

    __slots__ = ("_data",)

    def __init__(self, **kwargs: Any):
        object.__setattr__(self, "_data", dict(kwargs))

    def __getattr__(self, key: str) -> Any:
        data = object.__getattribute__(self, "_data")
        try:
            return data[key]
        except KeyError:
            raise AttributeError(
                f"SemanticConfig 中没有键 {key!r}（可用字段：{sorted(data)}）"
            ) from None

    def __setattr__(self, key: str, value: Any) -> None:
        raise AttributeError("SemanticConfig 不可变；如需覆盖请用 update() 返回新实例")

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def resolve(self, key: str) -> Any:
        """取配置值；未配置时返回键名本身（本体短名与语义名恰好同名的常见约定）。

        用于「属性名」这类恒等映射：本体属性短名 == 语义名时无需写配置，
        换本体（属性名不同）时在 config.json 覆盖即可，代码与机制均不变。
        """
        return self._data.get(key, key)

    def to_dict(self) -> dict:
        return dict(self._data)

    def update(self, **kwargs: Any) -> "SemanticConfig":
        """返回一个并入覆盖项的新配置（原实例保持不变）。"""
        data = dict(self._data)
        data.update(kwargs)
        return SemanticConfig(**data)

    def __repr__(self) -> str:
        return f"SemanticConfig({self._data!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SemanticConfig) and self._data == other._data


@dataclass(frozen=True)
class DomainConfig:
    """领域语义配置包（加载自领域 config.json）。"""

    config: SemanticConfig          # 语义配置（类角色映射 / 结构数据）


def load_domain_config(json_path: str | os.PathLike) -> DomainConfig:
    """从领域 config.json 加载语义配置包。

    文件缺失 / 格式错误直接抛异常（领域包内数据缺失属错误状态，不做静默兜底）。
    JSON 结构：
        {"semantic": {...}}
    中文标签统一从本体 rdfs:label 读取（reasoner.engine.label），不在此配置。
    """
    with open(json_path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, Mapping):
        raise ValueError(f"领域配置文件应为 JSON 对象: {json_path}")

    semantic = raw.get("semantic")
    if not isinstance(semantic, Mapping):
        raise ValueError(f"领域配置文件缺少 semantic 块: {json_path}")

    return DomainConfig(config=SemanticConfig(**dict(semantic)))


@dataclass(frozen=True)
class DerivationConfig:
    """领域推导链配置包（加载自领域 derivation.json）。"""

    templates: dict                 # 推导链静态文案模板
    derivations: dict               # 推导链展开规则（声明式步骤规则，见 reasoner.derivation）


def load_derivation_config(json_path: str | os.PathLike) -> DerivationConfig:
    """从领域 derivation.json 加载推导链配置包（templates + derivations）。

    文件缺失 / 格式错误直接抛异常（推导链配置是领域包必需部分，不做静默兜底）。
    JSON 结构：
        {"templates": {...}, "derivations": {...}}
    """
    with open(json_path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, Mapping):
        raise ValueError(f"推导链配置文件应为 JSON 对象: {json_path}")

    templates = raw.get("templates")
    derivations = raw.get("derivations")
    if not isinstance(templates, Mapping) or not isinstance(derivations, Mapping):
        raise ValueError(f"推导链配置文件缺少 templates / derivations 块: {json_path}")

    return DerivationConfig(
        templates=dict(templates),
        derivations=dict(derivations),
    )
