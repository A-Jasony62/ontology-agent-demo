FROM python:3.11-slim

WORKDIR /app

# 使用国内 pip 源加速依赖安装（默认清华 TUNA，可覆盖）：
#   docker build --build-arg PIP_INDEX_URL=https://pypi.org/simple ...
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 先装依赖（利用构建缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i "$PIP_INDEX_URL"

# 再拷代码
COPY . .

EXPOSE 8000 9000

# 默认启动推理 API + Demo 页面；MCP 服务用 docker compose 的 mcp 服务
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
