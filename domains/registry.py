"""领域适配器注册表：运行时动态加载独立目录 domains/ 下的领域包。

约定（插件式）：
    - 每个领域一个子目录/包，如 domains/agent_task/；
    - 包内必须暴露：
        NAME          str   领域标识（默认取目录名）
        DESCRIPTION   str   领域说明（展示给智能体/用户）
        create_adapter(engine, config=None) -> 适配器实例
    - 适配器实例包装通用引擎（reasoner.engine.OntologyEngine），
      用通用原语实现该领域的查询语义；引擎本身不包含任何领域知识。

用法:
    from domains import list_domains, load_domain
    list_domains()                        # [{"name","description","module"}, ...]
    adapter = load_domain("agent_task", engine, config=None)
"""

import importlib
import os

_DOMAINS_DIR = os.path.dirname(os.path.abspath(__file__))


def list_domains() -> list[dict]:
    """枚举 domains/ 下所有可用领域包（约定式发现，运行时动态）。"""
    out = []
    for entry in sorted(os.listdir(_DOMAINS_DIR)):
        if entry.startswith("_") or not os.path.isdir(os.path.join(_DOMAINS_DIR, entry)):
            continue
        mod = importlib.import_module(f"domains.{entry}")
        out.append({
            "name": getattr(mod, "NAME", entry),
            "description": getattr(mod, "DESCRIPTION", ""),
            "module": entry,
        })
    return out


def load_domain(name: str, engine, config=None):
    """按标识加载领域适配器：domains.<name>.create_adapter(engine, config)。"""
    mod = importlib.import_module(f"domains.{name}")
    return mod.create_adapter(engine, config)
