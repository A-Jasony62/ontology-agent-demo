# 示例领域包

这里的领域包是**随仓库分发的模板，不会自动生效**。

运行态加载位置由 `config/domain.json`（或环境变量 `ONTOLOGY_DOMAINS_ROOT`）决定，
默认是仓库根的 `domains/`。示例必须安装后才参与加载：

```bash
python scripts/ontologyctl.py domain install --from ./examples/agent_task
```

安装后 `domains/agent_task/` 是本地副本（已在 `.gitignore` 中），可以直接修改：
它是运行态，不是示例源码。重新安装会覆盖，`--force` 时旧版本先备份到
`backups/domains/<name>-<时间戳>/`。

## 两个示例的分工

| 包 | 定位 | 用来证明什么 |
|---|---|---|
| `agent_task/` | 完整业务领域（智能体任务编排） | 框架能承载真实规模的领域：7 个能力、R2/R4 规则、ABox 写入、MCP 工具 |
| `fault_diag/` | **异构**业务领域（设备故障诊断） | 框架的抽象是不是真通用：不实现任务编排四件套、声明自定义能力 `diagnose`、三级类层次、用 `owl:hasValue` 推出故障等级 |
| `_minimal/` | 零复制验收物 | 新领域最少要写多少东西（1 类 + 3 个体 + 0 业务方法） |

`agent_task` 和 `_minimal` 都是"顺着框架形状长"的——前者功能全，后者什么都不做。
两者都证明不了通用性：一个领域只能证明"框架没把它搞坏"。`fault_diag` 是
第一个形状对不上的领域，它照出过三处框架默认实现的真实缺陷（匿名类、
多级类层次被压平、只展开两代），回归用例在 `tests/test_contract.py`。

`fault_diag` 的测试里有一类标着【通用性】的用例，问的都是同一个问题：
"这条抽象是真的通用，还是恰好对 agent_task 成立"。

## 新增示例的约定

一个领域包最小需要：

| 文件 | 必需 | 作用 |
|---|---|---|
| `__init__.py` | 是 | 暴露 `NAME` / `DESCRIPTION` / `ONTO_FILE` / `create_adapter`（或 `create_adapter_ctx`） |
| `*.owl` | 是 | 本体定义（文件名由 `ONTO_FILE` 指向，或包内唯一的 `.owl`） |
| `config.json` | 否 | 语义配置（类角色映射、图谱分组） |
| `derivation.json` | 否 | 推导链展示模板 |
| `adapter.py` | 否 | 业务规则实现（被 `__init__.py` 引用） |
| `shapes/*.ttl` | 否 | SHACL 形状（G4 闸门按 `@domain` 哨兵从包内解析） |
| `mcp.py` | 否 | 该领域的 MCP 工具注册器 |

契约细节见 `reasoner/protocol.py`，扩展步骤见 `docs/guide/08-扩展新领域.md`。
