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

## 新增示例的约定

一个领域包最小需要：

| 文件 | 必需 | 作用 |
|---|---|---|
| `__init__.py` | 是 | 暴露 `NAME` / `DESCRIPTION` / `ONTO_FILE` / `create_adapter` |
| `*_ontology.owl` | 是 | 本体定义（`ONTO_FILE` 指向的文件） |
| `config.json` | 否 | 语义配置（命名空间、类映射等） |
| `derivation.json` | 否 | 推导链展示模板 |
| `adapter.py` | 否 | 业务规则实现（被 `__init__.py` 引用） |
| `mcp.py` | 否 | 该领域的 MCP 工具注册器 |

契约细节见 `reasoner/protocol.py`，扩展步骤见 `docs/guide/08-扩展新领域.md`。
