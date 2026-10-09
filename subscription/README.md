# 公开资源与私有订阅

GitHub 只保存公开资源、通用配置模板和发布工具。个人完整配置、实际节点来源、域名、访问密钥、SSH 私钥与证书均存放在服务器或客户端，不能提交到仓库。

## 运行目录

示例目录为 `/opt/projects/quanx-subscription`：

- `settings.json`：私有运行设置，参考仓库中的 `settings.example.json`，权限 `0600`。
- `private/main.conf`：个人配置，位于 Git checkout 之外，权限 `0600`。使用与模板相同的订阅占位符和两个 `BEGIN/END blackmatrix7` 资源区块。
- `keys/`、`ssh.conf`、`known_hosts`：节点导出所需的 SSH 文件，保存在 Git 之外。远端导出 key 使用来源 IP 限制、`restrict` 和固定命令。
- `repository/`：公开仓库 checkout，不直接作为 Web 根目录。
- `bin/`：审核后安装的运行脚本和校验器；Git 拉取只更新资源，不替换这里的代码。
- `releases/`、`current`：独立发布快照与原子切换入口，保留最近三个版本。

`settings.example.json` 中的域名、IP 和 SSH 别名均为示例。真实设置必须在仓库外填写。`private_config` 可省略，此时直接发布公共模板；指定时保留个人配置的其他段，只从公共模板刷新两个受管理资源区块。

## 自动更新

GitHub Actions 每天北京时间 05:00 同步上游，push 执行检查。服务器的 `quanx-subscription-update.timer` 约每五分钟执行一次 `update.sh`：

1. 拉取仓库 `master`。
2. 从私有设置的 `local_node` 读取本机 sing-box 配置并导出节点；通过 `remote_node` SSH 别名取得远端节点。未配置的来源跳过。
3. 合并节点和个人配置、校验仓库资源，生成独立发布快照。
4. 全部成功后切换 `current`；失败保留上一版，相同输入不重复发布。

修改个人 DNS、任务等设置时编辑仓库外的 `private/main.conf`；修改资源选择时编辑仓库的 `profiles/blackmatrix7.json` 并重新生成。修改运行工具时，审核后另行更新服务器 `bin/`。

## 导出与发布

`tools/export_nodes.py` 只读实际 sing-box 配置，导出原生 VLESS/REALITY 和 AnyTLS 节点，不改代理服务。REALITY 私钥只用于推导客户端公钥，TLS 私钥不进入输出。节点条目含连接凭据，只能写到私有文件或经加密 SSH 传输。

AnyTLS 保留证书验证；自签名证书使用 `--pin-anytls` 固定证书公钥 SHA-256。不要通过关闭证书验证解决连接问题，也不要复制个人 SSH 私钥到发布服务器。

公共模板固定使用 `https://example.invalid/quanx/nodes.conf`。发布工具将此占位符及本仓库资源地址替换为 `public_base/访问密钥/`，提供完整配置、`nodes.conf`、上游原文及圈 X 资源。订阅地址在自动更新时保持不变。

`--nginx-output` 可生成含访问密钥的 Nginx snippet，权限 `0600`，仅 include 到订阅专用 HTTPS server。该 server 整体关闭访问日志和带 URL 的错误日志，防止异常路径泄露密钥；发布目录只给 Nginx 只读权限，不暴露 Git 元数据和运行设置。

更换密钥时先禁用旧 location 并 reload Nginx，再生成新配置和入口、检查并 reload，避免旧入口读取新密钥。此步骤与日常自动发布分开执行。

验证应分别覆盖匿名/错误密钥拒绝、资源下载、穿越请求拒绝、自动更新和真实节点出口；圈 X 真机导入与应用分流另行验收。验证记录及实际地址保存在仓库外。
