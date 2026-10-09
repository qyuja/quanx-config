# Quantumult X 个人配置与全量规则镜像

本仓库完整同步 [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) 的 `rule/`、`rewrite/`，并保留其全部 `script/` 文件作为重写依赖。各平台的原文、README、作者和来源说明均保留。

## 配置与使用

主配置沿用原地址：

```text
https://raw.githubusercontent.com/qyuja/quanx-config/master/20250723-self.conf
```

仓库公开提供完整规则、重写、脚本和不含个人凭据的配置模板。模板中的 `https://example.invalid/quanx/nodes.conf` 只是订阅占位地址，直接导入时须替换为自己的节点订阅。

个人使用的完整配置由服务器从仓库模板、仓库外的私有配置和实际节点生成；真实节点地址、连接凭据、订阅域名、访问密钥、SSH 文件及 MITM 证书不提交到 GitHub。部署示例见 [subscription/README.md](subscription/README.md)。

先在 Quantumult X 备份当前配置，再通过「配置文件」导入模板或自己的私有发布地址。主配置列出了全部圈 X 分流和重写资源，默认开启常用分流，其余资源设为 `enabled=false`；需要时在资源列表启用并调整对应策略。
HTTPS 重写需要在客户端开启重写与 MITM、生成并信任本机证书。远程模块里的 `hostname` 随资源导入；主配置已有的排除域名会影响对应模块，不要随意取消排除。客户端证书和节点凭据不要复制到新增文件或公开评审材料。

需要分别导入资源时，可复制以下文件中的条目到对应的配置段；这些是配置片段，不能作为完整 VPN 配置导入：

- [完整分流资源片段](quantumultx/filter_remote.conf)
- [完整重写资源片段](quantumultx/rewrite_remote.conf)
- [全部资源、实际条数、默认策略和脚本依赖索引](quantumultx/catalog.md)

分流片段使用现有的 `美国节点`、`声田音乐`、`哔哩哔哩`、`国际媒体`、`苹果服务`、`全球加速` 和 `兜底分流` 策略；用于其他配置时需先建立这些策略，或修改 `force-policy`。

## 节点订阅与解析

主配置通过 `[server_remote]` 获取节点，`[server_local]` 不保存个人节点。私有发布工具输出圈 X 原生 VLESS/REALITY 和 AnyTLS 条目，因此使用 `opt-parser=false`，每小时更新一次。AnyTLS 保留证书验证；自签名证书可使用证书公钥固定验证。

以下是通用占位结构，真实订阅地址只保存在客户端和服务器私有文件中：

```ini
[server_remote]
https://example.invalid/quanx/nodes.conf, tag=自建节点, update-interval=3600, opt-parser=false, enabled=true
```

## 默认分流

常用规则按以下顺序配置：局域网与规则修正 → 防劫持与去广告 → 微信直连 → Google Voice 和 AI 服务 → Spotify、哔哩哔哩、YouTube、Telegram、国际媒体 → Apple → 全球代理 → 国内直连。原有本地分流仍保留，具体匹配结果还受 Quantumult X 本地规则和匹配设置影响。

广告分流采用 `AdvertisingLite`；完整 `Advertising`、`AdvertisingTest` 和其他全部规则同样保存在仓库中，可按需选择。`ChinaMax_No_IPv6` 与原配置的 `no-ipv6` 设置一致。未指定专用策略的可选资源沿用 `兜底分流`，启用某个国内服务、广告或其他专用资源前应明确设置 `force-policy`。

## 全量重写与避免冲突

圈 X 原生模块全部收录；blackmatrix7 模块默认仅开启 `AdvertisingLite`。主配置另保留 BoxJS 和 app2smile 的 Spotify 重写，使用各自的原地址。

| 模块 | 功能 | 默认 |
| --- | --- | --- |
| Advertising | 全量 URL 去广告 | 关闭 |
| AdvertisingLite | 减少宽泛匹配的 URL 去广告 | 开启 |
| AdvertisingScript | 通过脚本去广告 | 关闭 |
| AllInOne | 汇总 Advertising、AdvertisingScript、Redirect | 关闭 |
| BlockHTTPDNS | 拦截应用内 HTTPDNS | 关闭 |
| GetCookie | 为签到脚本获取 Cookie | 关闭 |
| Redirect | URL 重定向 | 关闭 |
| SafeRedirect | 上游维护的安全重定向列表 | 关闭 |
| Upgrade | 屏蔽部分应用升级提示 | 关闭 |

`AllInOne` 与 Advertising、AdvertisingLite、AdvertisingScript、Redirect、SafeRedirect 选择其一套；Advertising 与 AdvertisingLite、Redirect 与 SafeRedirect 分别互斥。AdvertisingLite、AdvertisingScript、AllInOne、BlockHTTPDNS 各自有配套 `.list`，启用对应重写时还需在分流资源中启用它，策略为 `reject`。启用脚本版去广告时，检查原有对应应用重写，避免同一响应被多个脚本重复修改。

`rewrite/` 保存上游原文；`quantumultx/rewrite/` 是本仓库订阅版本，把上游仓库内的脚本地址替换成本仓库地址。两个仍可访问的 Gist 脚本保留原地址，详见资源索引里的依赖列表。

上游 rewrite 仍引用 5 个已被作者作为过时代码删除的脚本。本仓库从删除前的 `f26b88d5cfa0e3740be246c4c9021cd5619eb766` 提交恢复原文，存放于 `dependencies/blackmatrix7/`；[依赖清单](dependencies/manifest.json) 记录固定来源、Git blob 和 SHA-256。恢复文件不代表旧签到接口仍可用；涉及这些脚本的模块默认关闭。

另外，AllInOne 引用的 DivineEngine `bstar.js` 返回 404，原作者仓库已经不可访问（见[上游问题记录](https://github.com/blackmatrix7/ios_rule_script/issues/1293)）。订阅版本注释其两条脚本规则；完整原条目仍保存在 `rewrite/`，未用无法核实的替代脚本覆盖。

## 同步与验证

GitHub Actions 每天北京时间 05:00 同步上游 `master`，也可以在 [Actions](https://github.com/qyuja/quanx-config/actions/workflows/sync-upstream.yml) 点击 **Run workflow** 手动同步。定时触发时间由 GitHub 调度，可能延后。

本地使用 Python 3.9+ 和 Git，无需安装 Python 第三方依赖：

```bash
python3 -m unittest discover -s tests -v
python3 tools/sync_upstream.py
python3 tools/sync_upstream.py --check
```

已有干净的上游 Git checkout 时可以跳过下载：

```bash
python3 tools/sync_upstream.py --upstream /absolute/path/to/ios_rule_script
```

`profiles/blackmatrix7.json` 决定启用顺序、策略、标签和重写模块。同步仅替换主配置中两个 `BEGIN/END blackmatrix7` 区块；首次接入时将旧远程分流替换为本仓库规则。两个区块外可保留自己的资源，原有其他配置段保持原文。

[UPSTREAM.json](UPSTREAM.json) 记录来源 commit、全部文件数量、大小与 SHA-256。同步时先核对每个上游文件的 Git blob，再检查全量快照、原生分流格式、默认策略是否存在、脚本路径、重写互斥关系和配套分流。重复同步相同 commit 不产生内容差异。

这些检查确认仓库内容与引用一致；Quantumult X 的实际导入、匹配、应用去广告效果和代理出口需在 iPhone 上验证。

## 来源与许可

上游作者为 blackmatrix7，原仓库为 [ios_rule_script](https://github.com/blackmatrix7/ios_rule_script)。上游资源的 GPL-2.0 许可全文保存于 [LICENSES/blackmatrix7-GPL-2.0.txt](LICENSES/blackmatrix7-GPL-2.0.txt)，完整上游声明保存于 [UPSTREAM_README.md](UPSTREAM_README.md)。各规则的具体来源和作者说明保留在对应目录的 README 内；本仓库镜像和生成订阅中的上游内容遵循原许可及声明。

策略组仅保留有自建节点的美国和日本，国际媒体默认自动选择；应用分流和直连规则继续使用现有策略。
