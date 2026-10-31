"""MCP 启动期回归：重复工具名 fail-fast、无 mcp.py 的领域可降级启动。"""

from __future__ import annotations

import importlib.util
import os
import types

import pytest

from _helpers import domain_module, submodule

_SERVER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp", "mcp_server.py"
)
_spec = importlib.util.spec_from_file_location("_mcp_server_startup_test", _SERVER_PATH)
mcp_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mcp_server)


class _FakeServer:
    def __init__(self):
        self.tools = {}

    def tool(self, description=None, **kwargs):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def test_tool_name_guard_rejects_duplicate_registration():
    """重复 @server.tool 不再只留一行日志，而是在注册期直接失败。"""
    guard = mcp_server._ToolNameGuard(_FakeServer())

    @guard.tool(description="first")
    def status():
        return 1

    with pytest.raises(ValueError, match="重复注册"):
        @guard.tool(description="second")
        def status():  # noqa: F811 - 故意重名
            return 2


def test_active_domain_mcp_has_no_duplicate_tool_names():
    """当前领域包（agent_task）注册表无重名，防止 merge 残留再次混入。"""
    mod = submodule(domain_module(), "mcp")
    server = _FakeServer()
    mod.register_tools(mcp_server._ToolNameGuard(server), lambda: None)
    assert "status" in server.tools


def test_build_server_allows_domain_without_mcp_module(monkeypatch):
    """mcp.py 是可选文件：缺失时只注册通用工具，不拖垮整个 Server。"""
    monkeypatch.setattr(mcp_server, "load_domain_module", lambda name: types.SimpleNamespace())
    monkeypatch.setattr(
        mcp_server, "importlib",
        types.SimpleNamespace(import_module=lambda name: (_ for _ in ()).throw(
            ModuleNotFoundError(name=name)
        )),
    )
    monkeypatch.setattr(mcp_server, "_register_generic_tools", lambda *a, **k: None)

    adapter = types.SimpleNamespace(NAME="minimal")
    server = mcp_server.build_server(lambda: None, lambda: adapter, "minimal", "最小领域")

    assert server is not None
