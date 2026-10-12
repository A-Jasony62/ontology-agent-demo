#!/usr/bin/env python3
"""本体推理 MCP Server（内嵌引擎，零服务依赖）——通用出口层。

架构：通用引擎（reasoner.engine，与本体无关） + 领域适配器（domains/，运行时动态加载）。
本模块不包含任何领域词汇；领域工具随领域包走（domains/<name>/mcp.py 注册），
启动时按 --domain 动态加载——换领域无需改动本文件。

    领域工具（domains/<name>/mcp.py，默认 domains/agent_task）：
        capability_match  能力匹配（R1/R2）：哪些智能体可执行该任务，附推导链
        orchestrate       任务编排（R3）：拆解依赖链并逐环节匹配执行者
        assign            任务分配 + R4 合规冲突检测
        classify          新增任务个体、重推理、自动分类
        consistency       全量一致性 / 合规冲突检查
        explain           最近一次查询的推导链（中文）
        ontology          本体结构（类/个体/边）
        entities          可用实体短名清单（辅助智能体正确选参）
    通用工具（引擎直接提供，与本体定义无关，任意 .owl 可用）：
        query_sparql / individuals / classes / types_of / property_values / infer

领域包约定（domains/<name>/ 必须暴露）：
    NAME / DESCRIPTION / ONTO_FILE / create_adapter(engine, config=None) / mcp.register_tools(server, adapter)

传输：
    默认 streamable-http（豆包连接器：填 http://127.0.0.1:9000/mcp）；
    --transport stdio 供本地 MCP client / Claude Desktop 使用。

用法（在项目根执行）:
    .venv/bin/python mcp/mcp_server.py                                # 默认领域 agent_task，HTTP
    .venv/bin/python mcp/mcp_server.py --domain agent_task --port 9000
    .venv/bin/python mcp/mcp_server.py --transport stdio              # stdio
"""

import argparse
import importlib
import os
import sys

# 项目根 = mcp/ 的父目录；加载 reasoner 包、domains 包与领域本体（领域包自包含）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from reasoner.engine import OntologyEngine
from domains import load_domain
from mcp.server.mcpserver import MCPServer


def build_server(engine: OntologyEngine, adapter, domain_name: str, description: str) -> MCPServer:
    """组装 MCP Server：领域工具（随领域包）+ 通用工具（引擎直接提供）。"""
    server = MCPServer(
        name="ontology-reasoning",
        title=f"本体推理服务（{adapter.NAME} 领域）",
        description=f"基于 OWL 2 本体的确定性推理：{description}；通用查询（SPARQL/个体/类/类型/属性/重推理）",
        version="1.2.0",
    )

    # 领域工具：动态加载领域包的 MCP 注册器（领域相关代码随领域包走）
    mod = importlib.import_module(f"domains.{domain_name}.mcp")
    mod.register_tools(server, adapter)

    # 通用工具（L1：与本体定义无关，任意 .owl 可用）
    _register_generic_tools(server, engine)
    return server


def _register_generic_tools(server: MCPServer, engine: OntologyEngine) -> None:
    @server.tool(description="SPARQL 查询（通用）：执行 SPARQL SELECT 并返回结果行，IRI 值自动转为短名。适用于任何本体，不依赖领域语义。")
    def query_sparql(sparql: str) -> dict:
        return {"results": engine.query_sparql(sparql)}

    @server.tool(description="个体查询（通用）：返回指定类（短名，含其子类）的全部个体短名。如 individuals('Agent')。")
    def individuals(class_name: str) -> dict:
        return {"class": class_name, "individuals": engine.individuals(class_name)}

    @server.tool(description="类层次（通用）：返回本体全部类的 name/label/direct_parent。")
    def classes() -> dict:
        return {"classes": engine.classes()}

    @server.tool(description="个体类型（通用）：返回指定个体推理后的全部类型短名（含子类推理结论）。如 types_of('dev_agent')。")
    def types_of(individual: str) -> dict:
        return {"individual": individual, "types": engine.types_of(individual)}

    @server.tool(description="属性取值（通用）：返回主体-属性 的取值列表。如 property_values('dev_agent', 'has_capability')。")
    def property_values(subject: str, property_name: str) -> dict:
        return {"subject": subject, "property": property_name,
                "values": engine.property_values(subject, property_name)}

    @server.tool(description="重新推理（通用）：重新执行 OWL 2 RL 推理与 R2 规则，返回三元组数量统计与个体数。")
    def infer() -> dict:
        return engine.infer()


def main() -> int:
    parser = argparse.ArgumentParser(description="本体推理 MCP Server（内嵌引擎，领域工具随领域包动态加载）")
    parser.add_argument("--domain", default="agent_task",
                        help="领域包标识（domains/<name>，默认 agent_task）")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="streamable-http",
                        help="传输协议（默认 streamable-http，供豆包连接器；stdio 供本地 Client）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000,
                        help="streamable-http 端口（默认 9000，避免与推理 API 8000 冲突）")
    args = parser.parse_args()

    # 领域包自声明本体文件；按领域加载引擎与适配器
    domain_mod = importlib.import_module(f"domains.{args.domain}")
    engine = OntologyEngine(onto_path=domain_mod.ONTO_FILE)
    adapter = load_domain(args.domain, engine)
    server = build_server(engine, adapter, args.domain, domain_mod.DESCRIPTION)

    if args.transport == "stdio":
        print(f"[info] 本体推理 MCP Server（{adapter.NAME} 领域）已启动（stdio）", file=sys.stderr)
        server.run(transport="stdio")
    else:
        print(f"[info] 本体推理 MCP Server（{adapter.NAME} 领域）已启动（streamable-http）: "
              f"http://{args.host}:{args.port}/mcp", file=sys.stderr)
        server.run(transport="streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
