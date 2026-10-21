# Changelog

本项目所有重要变更记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)（SemVer）。

## [Unreleased]

### Added

- **本体定义可维护（001 批次）**：
  - `OntologyEngine` 支持 `extensions_dir` 多文件加载：核心 `.owl` + `extensions/`
    增量块按文件名排序解析（turtle / rdf-xml），新增、回滚本体定义不再触碰核心文件；
    未配置 `extensions_dir` 时自动按"核心文件同目录 `extensions/`"推导
  - `OntologyEngine.reload()` 原子热重载：新图完成全部加载与推理后才整体替换
    内存状态，失败时旧状态保持不变（为批次二热重载端点打基础）
  - `AgentTaskAdapter.classify/assign` 支持 `persist=true` 增量持久化：断言级 RDF
    写 `extensions/YYYYMMDD-HHMMSS-<op>-<name>.ttl`（临时文件 + 原子替换），
    重启后可恢复；`change_count` / `changelog` 变更留痕就绪（供批次二 health dirty 使用）
  - `scripts/build_ontology.py` 新增 `--clean`：显式声明仅重建核心定义，
    `extensions/` 增量文件不触碰
  - MCP 领域工具 `assign` / `classify` 新增 `persist` 参数（默认 false，行为与 v0.1.0 一致）

### Changed

- `AgentTaskAdapter.assign` 由"仅内存 dict"改为**图断言 + 兼容缓存**：分配写入
  `assigned_to` 边（覆盖式重新分配，保持 v0.1.0 语义），`consistency` / `graph_export`
  以图断言为权威读取——分配成为可持久化、可 reload 恢复的本体状态
- 多文件模式下默认命名空间推导不再依赖核心文件头 `xml:base`（改走 IRI 高频前缀分支）；
  单文件模式行为不变

### Fixed

- `engine.classes()` 不再输出 owlrl 物化混入的 BNode 匿名空节点（「幽灵类」），
  类层次 / `/api/classes` / MCP `entities()` 结果更干净

## [0.1.0] - 2026-10-20

首个公开发布版本：本体推理能力打包为开箱即用的工具（推理引擎 + REST API + MCP + 图谱工作台 + 学习指南）。

### Added

- **OWL 2 RL 推理引擎**（`reasoner/`）：基于 owlready2，加载 OWL 本体并执行物化推理；
  支持 SPARQL 查询、类层次/个体/属性取值等通用查询
- **领域适配器**（`domains/`）：内置「智能体任务编排」示例本体与业务规则
  - R1 能力匹配（属性链 `has_capability ◦ required_by ⊑ can_execute`）
  - R2 任务聚合（成员聚合 → 复合任务）
  - R3 依赖传递（任务链逐环节匹配）
  - R4 合规冲突检测（未认证 Agent 拒绝分配）
  - 推理推导链（事实 → 规则 → 结论）结构化输出
- **REST API**（`api/`，FastAPI）：`/api/health`、`/api/reason`、`/api/explain`、`/api/consistency`、
  `/api/classify`、`/api/query`（SPARQL）、`/api/ontology`、`/api/individuals`、`/api/classes`、
  `/api/types`、`/api/property`、`/api/infer`、`/api/upload`（OWL 上传进入通用模式）
- **MCP Server**（`mcp/`，Model Context Protocol）：14 个工具（8 领域 + 6 通用），
  智能体（豆包等）经 MCP 接入即可调用本体推理
- **本体图谱工作台**（`frontend/app/`，React 19 + Vite + Cytoscape）：
  - 三种图谱视图：原始断言 / 物化后（并集）/ 仅差异，推理新增边虚线+独立色标注
  - OWL 源码查看与编辑（保存时解析校验回读）
  - 拖拽导入 `.owl`/`.rdf`；导出当前模型或物化后本体（Turtle / RDF/XML）
  - 可视化编辑：实体 / 属性 / 关系 CRUD + 实时校验
  - 物化 diff 统计卡片（原始三元组 / 物化后 / 推理新增）
  - 服务能力说明面板（REST API + MCP 接入引导）
  - 基于 Microsoft [Ontology-Playground](https://github.com/microsoft/Ontology-Playground)（MIT）改造，
    上游许可证见 `frontend/app/LICENSE`
- **命令行工具**（`scripts/query.py`）：与 API 对应的 CLI，自动双通道
  （HTTP 优先，失败回退内嵌引擎，`--local` 可强制零依赖运行）
- **一键体验**：`make run` 起服务、`make demo` 跑核心接口演示、`make mcp` 起 MCP；
  `scripts/start.sh` / `scripts/demo.sh` 等价脚本
- **Docker 支持**：多阶段构建（Node 编译前端 → Python 运行时），
  `docker compose up` 一键起推理 API + MCP；默认国内镜像源（npm/pip）可覆盖
- **工程化**：GitHub Actions CI（后端 pytest 3.10–3.12 + 前端 typecheck/vitest/build）、
  Pages 工作流部署在线指南
- **学习指南**：《本体上手指南》9 篇系列（`docs/guide/`），从概念到实战逐步上手，
  章节与代码一一对应；在线站点 https://jasony62.github.io/ontology-agent-demo/
- **文档**：`docs/DESIGN.md`、`docs/FLOW.md`、`docs/REASONING.md`、
  `docs/KNOWLEDGE_BEYOND_OWL.md`、`docs/DOMAIN_PACKAGE_GENERATION.md`（领域包自动生成路线图）
- **许可证**：MIT（根 LICENSE；前端另附上游 MIT 许可证）

[Unreleased]: https://github.com/jasony62/ontology-agent-demo/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jasony62/ontology-agent-demo/releases/tag/v0.1.0

> AI生成
