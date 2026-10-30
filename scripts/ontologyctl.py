#!/usr/bin/env python3
"""本体服务运维 CLI（003 批次 REQ-04/REQ-07：统一管理命令）。

聚合 REST API（正式变更入口）+ git（版本管理/回滚）+ MCP（进程探测/热重载触发）。

用法（在项目根执行）:
    .venv/bin/python scripts/ontologyctl.py status                  # 服务 + 本体 + MCP 状态
    .venv/bin/python scripts/ontologyctl.py reload                  # API reload + MCP kill -HUP
    .venv/bin/python scripts/ontologyctl.py commit -m "新增合规任务" # 本体变更入 git + tag
    .venv/bin/python scripts/ontologyctl.py diff                    # 未提交变更预览
    .venv/bin/python scripts/ontologyctl.py rollback [tag]          # 回滚本体文件并 reload
    .venv/bin/python scripts/ontologyctl.py log                     # git log + changelog
所有子命令支持 --json（纯结构化输出）。

约定：
    API_BASE          环境变量 DOUBAO_API_BASE（默认 http://127.0.0.1:8000）
    权威源            ONTOLOGY_GIT_ROOT（git 仓库根，默认 = 脚本所在目录的上级 = 项目根）
    MCP 进程          pgrep -f mcp/mcp_server.py + 端口 9000 探测（只读，不依赖服务）
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
API_BASE = os.environ.get("DOUBAO_API_BASE", "http://127.0.0.1:8000").rstrip("/")
GIT_ROOT = os.environ.get("ONTOLOGY_GIT_ROOT", PROJECT_ROOT)

# 直接以脚本方式运行时，项目根不在 sys.path 上（脚本目录才是），
# 这里补上，domain 子命令需要 import config / domains.installer。
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 本体相关文件（git add / rollback 范围）
ONTO_FILES = [
    "domains/*/agent_task_ontology.owl",
    "domains/*/extensions/",
    "domains/*/config.json",
    "domains/*/derivation.json",
    "domains/*/semantic.json",
]
MCP_MARKER = "mcp/mcp_server.py"
MCP_PORT = 9000


def _http(method: str, path: str, payload: dict | None = None) -> dict:
    import urllib.request

    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url, method=method)
    data = None
    if payload is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(payload).encode()
    try:
        with urllib.request.urlopen(req, data=data, timeout=5) as r:
            return {"status": r.status, "body": json.loads(r.read() or b"{}")}
    except Exception as exc:
        return {"status": 0, "error": f"{exc}"}


def _run(cmd: list, cwd=GIT_ROOT) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return p.returncode, (p.stdout or p.stderr).strip()


def _mcp_probe() -> dict:
    """MCP 进程与端口状态（只读探测）。"""
    rc, out = _run(["pgrep", "-f", MCP_MARKER])
    pids = out.splitlines() if rc == 0 and out else []
    port_rc, _ = _run(["lsof", "-iTCP:%d" % MCP_PORT, "-sTCP:LISTEN"])
    return {"running": bool(pids), "pids": pids[:5], "port": MCP_PORT, "port_listening": port_rc == 0}


def _git_tags() -> list:
    rc, out = _run(["git", "tag", "-l", "*本体*"])
    return out.splitlines() if rc == 0 and out else []


# ---------------- 子命令 ----------------

def cmd_status(args) -> dict:
    api = _http("GET", "/api/health")
    ont = _http("GET", "/api/ontology/status")
    mcp = _mcp_probe()
    result = {"api": api.get("body") or {"error": api.get("error")},
              "ontology_status": ont.get("body") or {"error": ont.get("error")},
              "mcp": mcp}
    # 两端一致性（REQ-02）：同一基线哈希 + 相同 dirty/pending_changes
    if api.get("body") and ont.get("body"):
        a, o = api["body"], ont["body"]
        result["consistency"] = {
            "consistent": o.get("baseline_file_hash") is not None
                           and a.get("dirty") == o.get("dirty")
                           and a.get("pending_changes") == o.get("pending_changes"),
            "api_dirty": a.get("dirty"),
            "mcp_or_api_pending": o.get("pending_changes"),
            "baseline_file_hash": o.get("baseline_file_hash"),
        }
    return result


def cmd_reload(args) -> dict:
    api = _http("POST", "/api/ontology/reload")
    mcp = _mcp_probe()
    mcp_hup = "skipped"
    if mcp["running"]:
        for pid in mcp["pids"]:
            try:
                os.kill(int(pid), 1)          # SIGHUP
                mcp_hup = "sent"
            except Exception as exc:
                mcp_hup = f"failed: {exc}"
    return {"api_reload": api.get("body") or {"error": api.get("error")},
            "mcp": {**mcp, "sighup": mcp_hup}}


def cmd_commit(args) -> dict:
    files = []
    for pat in ONTO_FILES:
        rc, out = _run(["git", "status", "--short", "--", pat])
        if rc == 0 and out:
            files += [l[3:] for l in out.splitlines() if l.strip()]
    if not files:
        return {"committed": False, "reason": "本体相关文件无变更", "files": []}
    add = _run(["git", "add", "--"] + files)
    if add[0] != 0:
        return {"committed": False, "reason": f"git add 失败: {add[1]}"}
    tag = f"v0.1.x-本体-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    cm = _run(["git", "commit", "-m", args.message])
    if cm[0] != 0:
        return {"committed": False, "reason": f"git commit 失败: {cm[1]}"}
    tg = _run(["git", "tag", tag])
    return {"committed": True, "files": files, "commit": cm[1].splitlines()[-1] if cm[1] else "",
            "tag": tag if tg[0] == 0 else f"tag 失败: {tg[1]}"}


def cmd_diff(args) -> dict:
    ont = _http("GET", "/api/ontology/status")
    rc, out = _run(["git", "status", "--short", "--"] + ONTO_FILES)
    return {
        "pending_changes": (ont.get("body") or {}).get("pending_changes", 0),
        "changelog": (ont.get("body") or {}).get("changelog", []),
        "git_status": out.splitlines() if rc == 0 and out else [],
    }


def cmd_rollback(args) -> dict:
    tag = args.tag or (_git_tags()[-1] if _git_tags() else None)
    if not tag:
        return {"rolled_back": False, "reason": "未提供 tag 且无历史本体 tag"}
    files = ["domains/agent_task/agent_task_ontology.owl"]
    co = _run(["git", "checkout", tag, "--"] + files)
    if co[0] != 0:
        return {"rolled_back": False, "reason": f"git checkout 失败: {co[1]}"}
    api = _http("POST", "/api/ontology/reload")
    return {"rolled_back": True, "tag": tag,
            "files": files,
            "api_reload": api.get("body") or {"error": api.get("error")}}


def cmd_log(args) -> dict:
    rc, out = _run(["git", "log", "--oneline", "-10", "--", "domains/agent_task/"])
    ont = _http("GET", "/api/ontology/status")
    return {
        "git_log": out.splitlines() if rc == 0 and out else [],
        "tags": _git_tags()[-5:],
        "service_changelog": (ont.get("body") or {}).get("changelog", []),
    }


def _config_dir():
    """部署配置文件所在目录（domain.json 写在这里）。独立函数便于测试替换。"""
    from pathlib import Path

    return Path(PROJECT_ROOT) / "config"


def _load_cfg(args):
    """按 CLI 参数加载运行态配置，且**固定使用本项目的 config 目录**。

    不加 config_dir 的话 `load_config` 会按自身模块位置推导配置目录，
    `domain use` 写下的默认领域与 `domain uninstall / list` 读到的就不是
    同一份文件——两个命令对"当前默认是谁"给出不同答案。
    """
    from config import load_config

    return load_config(cli_root=getattr(args, "to", None), config_dir=_config_dir())


def _installed_meta(root, name: str) -> dict:
    """读安装记录 root/.installed/<name>.json（缺失/损坏 → 空 dict）。"""
    from pathlib import Path

    path = Path(root) / ".installed" / f"{name}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 记录损坏不该让 list 失败
        return {}


def _scan_dir(scan_root, installed_root) -> list:
    """扫描一个目录下的候选领域包，标注是否已安装、是否与已安装版本一致。

    只读：不安装、不修改任何东西。`up_to_date` 用内容哈希判断，
    因为"装过"不等于"装的是这份"——重新装一次是最常见的需求。
    """
    from pathlib import Path

    from domains.installer import tree_hash

    out = []
    base = Path(scan_root).expanduser()
    if not base.is_dir():
        return [{"error": f"目录不存在：{base}"}]
    for pkg in sorted(base.iterdir()):
        if not pkg.is_dir() or not (pkg / "__init__.py").is_file():
            continue
        target = Path(installed_root) / pkg.name
        installed = target.is_dir()
        same = False
        if installed:
            try:
                same = tree_hash(pkg) == tree_hash(target)
            except OSError:
                same = False
        out.append({
            "name": pkg.name,
            "path": str(pkg),
            "installed": installed,
            "up_to_date": same,
        })
    return out


def _domain_list(args) -> dict:
    from domains import package_onto_path, package_shapes_path

    cfg = _load_cfg(args)
    current = cfg.effective_default()
    items = []
    for name in cfg.installed():
        meta = _installed_meta(cfg.root, name)
        items.append({
            "name": name,
            "is_default": name == current,
            "source": meta.get("source"),
            "installed_at": meta.get("installed_at"),
            "onto_file": package_onto_path(name, settings=cfg),
            "shapes_file": package_shapes_path(name, settings=cfg),
        })
    result = {"ok": True, "root": str(cfg.root), "default": current, "domains": items}
    if getattr(args, "scan", None):
        result["scan"] = {
            "dir": args.scan,
            "candidates": _scan_dir(args.scan, cfg.root),
        }
    return result


def _domain_uninstall(args) -> dict:
    """卸载：先整体移到 backups/ 再删记录——装错了还能拿回来。"""
    import shutil
    from pathlib import Path

    cfg = _load_cfg(args)
    name = args.name
    pkg = Path(cfg.root) / name
    if not pkg.is_dir():
        return {"ok": False, "error": f"未安装：{name}；已安装：{cfg.installed() or '（空）'}"}
    if cfg.effective_default() == name and not args.force:
        return {
            "ok": False,
            "error": (f"{name} 是当前默认领域，直接卸载会让服务起不来。"
                      "请先 `domain use <其他领域>`，或加 --force 确认。"),
        }

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = Path(PROJECT_ROOT) / "backups" / "domains" / f"{name}-{stamp}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pkg), str(backup))
    meta = Path(cfg.root) / ".installed" / f"{name}.json"
    if meta.is_file():
        meta.unlink()
    return {
        "ok": True,
        "uninstalled": name,
        "backup": str(backup),
        "default": cfg.effective_default(),
        "installed_domains": cfg.installed(),
    }


def _domain_use(args) -> dict:
    """把默认领域写进 config/domain.json（本地部署配置，已 gitignore）。

    为什么不直接改内存：默认领域是**部署决策**，要跨进程生效——
    API 重启、MCP 重启、CLI 内嵌引擎都读同一份配置。写配置文件是唯一
    能让这三者同时改主意的地方。
    """
    from pathlib import Path

    cfg = _load_cfg(args)
    name = args.name
    if name not in cfg.installed():
        return {"ok": False,
                "error": f"未安装：{name}；已安装：{cfg.installed() or '（空）'}"}

    cfg_dir = Path(_config_dir())
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "domain.json"
    data: dict = {}
    # 以模板为基线：只写 {"domains":{"default":...}} 会把 root/watch 等字段
    # 连带覆盖成缺省值，等于顺手改了别的配置。
    template = cfg_dir / "domain.example.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            return {"ok": False, "error": f"现有 domain.json 不是合法 JSON：{exc}"}
    elif template.is_file():
        data = json.loads(template.read_text(encoding="utf-8"))
        data.pop("_readme", None)
    domains = data.setdefault("domains", {})
    domains.setdefault("root", "domains")      # 与内置默认一致；模板缺失时也保持完整
    domains["default"] = name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "default": name,
        "config": str(path),
        "note": ("API 可立即切换：POST /api/domains/{name}/activate；"
                 "MCP 的领域在启动时注册工具，需重启进程才会生效"),
    }


def cmd_domain(args) -> dict:
    """领域包管理：install / list / uninstall / use。"""
    from config import ConfigError
    from domains.installer import install

    action = getattr(args, "domain_action", None)
    try:
        if action == "list":
            return _domain_list(args)
        if action == "uninstall":
            return _domain_uninstall(args)
        if action == "use":
            return _domain_use(args)
        if action != "install":
            return {"ok": False, "error": f"不支持的 domain 操作：{action}"}
        cfg = _load_cfg(args)
        result = install(args.src, root=cfg.root, name=args.name, force=args.force)
    except ConfigError as exc:
        return {"ok": False, "error": str(exc)}

    result["root"] = str(cfg.root)
    result["installed_domains"] = cfg.installed()
    return result


SUBCOMMANDS = {
    "status": (cmd_status, "聚合 health + 本体状态 + MCP 探测（--json 输出结构化结果）"),
    "reload": (cmd_reload, "API reload + MCP kill -HUP 热重载"),
    "commit": (cmd_commit, "本体变更入 git 并打 tag（需 -m 提交信息）"),
    "diff": (cmd_diff, "未提交变更预览（服务 changelog + git status）"),
    "rollback": (cmd_rollback, "git checkout 本体文件并 reload（可指定 tag）"),
    "log": (cmd_log, "git log（本体相关）+ 服务 changelog + tags"),
    "domain": (cmd_domain, "领域包管理：install --from <path> / list [--scan DIR] / uninstall N / use N"),
}


def _add_domain_actions(parser, common) -> None:
    dsub = parser.add_subparsers(dest="domain_action", required=True)
    inst = dsub.add_parser(
        "install", help="从指定路径安装领域包到运行态 root", parents=[common]
    )
    inst.add_argument(
        "--from", dest="src", required=True,
        help="领域包源目录（相对当前目录或绝对路径）",
    )
    inst.add_argument("--name", default=None, help="安装名（缺省取源目录名）")
    inst.add_argument("--to", default=None, help="目标 root（缺省取配置 domains.root）")
    inst.add_argument("--force", action="store_true", help="覆盖已安装版本（先备份）")

    lst = dsub.add_parser("list", help="列出已安装领域（可扫描候选目录）", parents=[common])
    lst.add_argument("--to", default=None, help="目标 root（缺省取配置 domains.root）")
    lst.add_argument("--scan", default=None,
                     help="扫描该目录下的候选领域包，标注是否已安装 / 是否最新（只读）")

    rm = dsub.add_parser("uninstall", help="卸载领域包（先整体备份）", parents=[common])
    rm.add_argument("name", help="领域标识")
    rm.add_argument("--to", default=None, help="目标 root（缺省取配置 domains.root）")
    rm.add_argument("--force", action="store_true",
                    help="允许卸载当前默认领域（默认拒绝，避免服务起不来）")

    use = dsub.add_parser("use", help="把某领域写为配置默认领域", parents=[common])
    use.add_argument("name", help="领域标识")
    use.add_argument("--to", default=None, help="目标 root（缺省取配置 domains.root）")


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="纯 JSON 输出")
    ap = argparse.ArgumentParser(description="本体服务运维 CLI（REQ-04/REQ-07）", parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, (_, help_) in SUBCOMMANDS.items():
        p = sub.add_parser(name, help=help_, parents=[common])
        if name == "commit":
            p.add_argument("-m", "--message", required=True, help="提交信息")
        if name == "rollback":
            p.add_argument("tag", nargs="?", default=None, help="回滚目标 tag（缺省最近本体 tag）")
        if name == "domain":
            _add_domain_actions(p, common)
    args = ap.parse_args()

    fn = SUBCOMMANDS[args.cmd][0]
    result = fn(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))   # 结构化文本（默认也输出 JSON）
    return 0


if __name__ == "__main__":
    sys.exit(main())
