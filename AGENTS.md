# quanx-config

本仓库保存不含个人凭据的 Quantumult X 配置模板，以及 blackmatrix7/ios_rule_script 的完整 rule、rewrite 和脚本依赖快照。

- 主配置继续使用 `20250723-self.conf`，节点使用通用订阅占位地址，保留 DNS、应用分流策略、本地分流、任务和 MITM 设置的模板；修改受管理的资源选择时编辑 `profiles/blackmatrix7.json`。
- `rule/`、`rewrite/`、`script/`、`UPSTREAM_README.md` 和 `LICENSES/blackmatrix7-GPL-2.0.txt` 是上游原文，禁止直接修改。
- `quantumultx/` 和 `UPSTREAM.json` 由 `tools/sync_upstream.py` 生成。`quantumultx/rewrite/` 把上游仓库内的脚本地址替换成本仓库地址；删除的脚本使用 `dependencies/manifest.json` 固定的历史原文，无法核实恢复的失效脚本条目注释保留。保留作者和原仓库声明。
- 全量收录与默认启用分开：聚合规则有重叠，AllInOne 与其组成模块不能同时启用；有配套 `.list` 的 rewrite 必须同时配置对应分流。
- 不在日志、新文件或评审材料中复制节点订阅凭据，不提交实际节点地址、订阅域名、SSH 配置、客户端私钥、MITM 证书和本机配置。
- 验证命令：`python3 -m unittest discover -s tests -v`、`python3 tools/sync_upstream.py --check`。
- 同步命令：`python3 tools/sync_upstream.py`；已有上游 checkout 时使用 `--upstream /absolute/path`。
- 哈希、格式、资源路径和 CI 检查不能代替 iPhone 上 Quantumult X 的实际导入、代理出口或 rewrite 验收。
- 主配置的自建订阅使用不含访问密钥的占位地址；实际可导入版本由 `tools/publish_subscription.py` 从仓库模板和仓库外的 `private_config` 在订阅服务器生成。部署和凭据规则见 `subscription/AGENTS.md`。

## Compact Log

- 2026-10-09：完成上游全量镜像和自动同步；默认启用模块与全量收录分开维护。
- 2026-10-09：按用户要求准备公开仓库；主配置保留通用订阅占位符，个人完整配置、节点来源和部署设置移到仓库外私有文件。公开前检查提交历史、Actions 记录和匿名可读范围，订阅地址保持原值。
- 2026-10-09：上下文压缩后继续已获用户批准的同名公开仓库重建；完整旧历史已私下备份，发布前验证新仓库历史、匿名访问和私有订阅自动更新。
