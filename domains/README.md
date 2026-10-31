# 运行态领域目录

本目录存放**实际生效**的领域包，由 `ontologyctl domain install` 创建。

目录下的子目录**不入库**（`.gitignore` 中的 `domains/*/`），因为它们是可重建的
安装产物；本文件与 `__init__.py`、`registry.py`、`installer.py` 属于框架代码，正常入库。

## 常用命令

```bash
# 安装示例领域到运行态
python scripts/ontologyctl.py domain install --from ./examples/agent_task

# 覆盖已安装版本（旧版本先备份到 backups/domains/）
python scripts/ontologyctl.py domain install --from ./examples/agent_task --force

# 从任意路径安装，并指定安装名
python scripts/ontologyctl.py domain install --from ../my-domain --name finance_ops
```

首次安装且尚未配置 `domains.default` 时，`install` 会自动把新领域写为默认；
再安装第二个领域不会覆盖已有默认。`domain ensure --from <path>` 可在启动脚本中
幂等地完成这一步；多领域且无默认时它会返回可操作的错误。

## 加载根如何决定

优先级（高 → 低）：

1. CLI 参数（`--domains-root` / `--domain`）
2. 环境变量 `ONTOLOGY_DOMAINS_ROOT` / `ONTOLOGY_DOMAIN`
3. `config/domain.json`（本地部署配置，不入库）
4. `config/domain.example.json`（随仓库分发的模板）
5. 内置默认（`root=domains`，`default=null`）

`domains.default` 为 `null` 时：本目录下恰好一个已安装领域则自动选用，
零个或多个则要求显式指定。

## 安装记录

每次安装会在 `domains/.installed/<name>.json` 写入来源、时间与内容哈希，
用于判断本地副本是否被改动过。
