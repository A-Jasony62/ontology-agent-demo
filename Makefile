PY := .venv/bin/python
PIP := .venv/bin/pip
UVICORN := .venv/bin/uvicorn

.PHONY: help setup run mcp test demo build-ontology docs

help: ## 查看可用命令
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## 首次：创建虚拟环境并安装依赖
	python3 -m venv .venv
	$(PIP) install -r requirements.txt

run: ## 启动推理 API + Demo 页面（http://127.0.0.1:8000）
	$(UVICORN) api.main:app --host 127.0.0.1 --port 8000 --reload

mcp: ## 启动 MCP Server（streamable-http，端口 9000）
	$(PY) mcp/mcp_server.py --domain agent_task --port 9000

test: ## 运行全部测试
	$(PY) -m pytest tests/ -v

demo: ## 一键演示（需先 make run 或 scripts/start.sh）
	bash scripts/demo.sh

build-ontology: ## 重建示例本体（含结构自检）
	$(PY) scripts/build_ontology.py

docs: ## 本地构建指南站点（需 Python 3.10-3.12 已装 mkdocs；CI 会自动构建 Pages）
	@command -v .venv/bin/mkdocs >/dev/null 2>&1 || { \
	  echo "未找到 .venv/bin/mkdocs。请先用 3.10-3.12 的解释器安装："; \
	  echo "  python3.12 -m venv .venv-docs && .venv-docs/bin/pip install mkdocs mkdocs-material"; \
	  echo "（注意：当前机器 Python 3.14 暂无 watchdog 预编译轮子，mkdocs 装不上；CI 在 3.12 上已验证）"; \
	  exit 1; }
	.venv/bin/mkdocs build
