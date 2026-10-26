# 03 前端工作台与 MCP 接入

## 3.1 图谱工作台（前端）

生产构建后由 FastAPI 托管，打开 `http://127.0.0.1:8000` 即可使用；开发模式见 [04 运维](04-运维与本体管理.md) 或 README。

| 功能 | 说明 |
|---|---|
| **图谱三视图** | Cytoscape 交互图谱：原始断言 / 物化后（并集）/ 仅差异；推理新增边以虚线+独立色标注 |
| **OWL 源码** | RDF/XML 源码语法高亮查看与编辑（保存时解析校验回读） |
| **导入 / 导出** | 拖拽上传 `.owl`/`.rdf`；导出当前模型（RDF/XML）或物化后本体（Turtle / RDF/XML） |
| **可视化编辑** | 实体 / 属性 / 关系 CRUD，改动即时反映到图谱 |
| **在线编辑本体定义** | 四栏编辑器：类层次 / 对象属性 / 数据属性 / 实例断言；撤销/重做/脏标记/实时校验；保存由后端序列化 OWL 并自动重推理，三视图联动刷新 |
| **另存 / 覆盖 / 下载** | 另存为新本体（进入通用模式）或覆盖当前本体（默认本体覆盖后领域推理保留，需二次确认）；保存后可下载 OWL 文件 |
| **物化统计** | 统计卡片显示三元组数量变化（原始断言 ∪ 推理新增） |

**在线编辑边界**：编辑模型仅覆盖类 / 属性 / 个体子集——restriction、属性链等复杂公理不进入编辑模型；「覆盖当前本体」会重建 OWL 文件，含复杂公理的原文件覆盖后不保留（另存可保留）。校验规则刻意宽松（开放世界假设）：id 仅要求非空且无 IRI 危险字符，中文/下划线短名合法，对象断言可指向未声明实体。

**安全边界**：`/api/upload` 是单机演示功能，接收任意 `.owl` 写入 `data/uploads/`，**无鉴权、无输入隔离——请勿将服务直接暴露公网**；如需公网部署请自行加鉴权与上传校验。

## 3.2 MCP Server（智能体接入）

把本体推理封装为标准 MCP Server，智能体（豆包等）一行配置接入。

### 启动

```bash
# 方式一：Docker（与 API 同栈）
docker compose up -d mcp

# 方式二：手动
.venv/bin/python mcp/mcp_server.py --domain agent_task --port 9000    # streamable-http
.venv/bin/python mcp/mcp_server.py --transport stdio                  # stdio（本地 Client / Claude Desktop）
# --watch 参数可开启文件监听热重载
```

### 接入豆包（连接器）

1. 豆包电脑版 → 侧边栏「技能 / 连接器」→ 右上角「添加」→「新建自定义连接器」；
2. 传输类型选 **HTTP**，MCP 服务器 URL 填 `http://127.0.0.1:9000/mcp`；
3. 保存后即可在对话中直接调用本体推理工具。

### 工具清单（实测握手 serverInfo：ontology-reasoning v1.3.0）

| 类别 | 工具 | 说明 |
|---|---|---|
| 通用 | `query_sparql` / `individuals` / `classes` / `types_of` / `property_values` / `infer` | 与本体无关的查询（SPARQL/个体/类/类型/属性/重推理） |
| 通用 | `explain_proof` | 结构化证明导出：给定结论三元组 → `{mode, rule, axioms, premises, conclusion}`（asserted/derived/unproven），支持属性链/传递/子类三类规则 |
| 通用 | `predefined_queries` / `run_predefined_query` | 受控预定义查询：启用语义白名单后按名调用，结果只含白名单字段 |
| 通用 | `active_facts` | 时序事实查询：按 `validFrom/validTo` 半开区间 `[from,to)` 过滤活跃事实，失效事实进 inactive，非法时间戳进 warnings |
| 领域 | 能力匹配 / 编排 / 分配 / 分类 / 一致性 / 图谱 / 实体清单 | 绑定默认领域包（agent_task），语义配置化 |

**受控语义接口（v0.2.3+）**：配置领域包 `access_policy.json` 语义白名单后，MCP 只暴露允许的类/谓词（含子类继承），白名单外查询被拒并返回诚实提示；策略激活时 `query_sparql` 禁用。
