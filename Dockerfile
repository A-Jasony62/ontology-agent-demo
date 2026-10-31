# ---------- 阶段 1：构建前端（Vite + React） ----------
FROM node:20-slim AS frontend

WORKDIR /frontend

# 国内 npm 源加速（可覆盖）：
#   docker build --build-arg NPM_REGISTRY=https://registry.npmjs.org ...
ARG NPM_REGISTRY=https://registry.npmmirror.com

COPY frontend/app/package.json frontend/app/package-lock.json ./
RUN npm ci --registry="$NPM_REGISTRY"

COPY frontend/app/ ./
RUN npm run build

# ---------- 阶段 2：Python 运行时 ----------
FROM python:3.11-slim

WORKDIR /app

# 国内 pip 源加速（可覆盖）：
#   docker build --build-arg PIP_INDEX_URL=https://pypi.org/simple ...
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 先装依赖（利用构建缓存）
# SDK 是本仓库 workspace 包，requirements.txt 用 -e ./packages/ontology-plugin-sdk
# 引用它——必须在 pip install 之前把 packages/ 拷进来，否则 editable 路径不存在。
COPY requirements.txt .
COPY packages ./packages
RUN pip install --no-cache-dir -r requirements.txt -i "$PIP_INDEX_URL"

# 再拷代码（dist/node_modules/data 均已被 .dockerignore 排除）
COPY . .
# 运行态领域包不入镜像：构建期从随仓库分发的 examples/ 安装默认领域，
# 避免镜像内容取决于构建机本地是否装过领域。
RUN python scripts/ontologyctl.py domain ensure --from ./examples/agent_task
# 覆盖为阶段 1 构建出的新前端（dist 在 .gitignore 中，不依赖本地构建产物）
COPY --from=frontend /frontend/dist ./frontend/app/dist

EXPOSE 8000 9000

# 默认启动推理 API + Demo 页面；MCP 服务用 docker compose 的 mcp 服务
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
