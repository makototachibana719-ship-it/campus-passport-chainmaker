# 配置与数据保留

原工程目录为 `/home/makoto/zuodequandui-lab/campus-assets`，端口 5001。更新源码时保留原 `settings.json`、`users.json`、`config/`、`shop.sqlite3`、`results/` 及外部证书目录，不能用新空数据库替换已运行的商城数据库。

| 项目 | 实际用途 |
|---|---|
| `settings.json` 的 `cmc_dir` | 含可执行文件 cmc 的绝对目录，也是 CMC 子进程工作目录 |
| `contracts.ft/nft/task` | 三个已经部署的合约名称 |
| `config/admin.yml` | 原校园管理员链上身份配置 |
| `config/alice.yml` | 原学生 A 链上身份配置 |
| `config/bob.yml` | 原学生 B 链上身份配置 |
| `users.json` | admin/alice/bob 对应的 Werkzeug 密码哈希映射 |
| `results/` | 本地操作记录与支付回查证据输出目录 |
| `shop.sqlite3` | 已兑换订单、核验状态和外观偏好 |

源码包不含实际 YAML、证书及私钥，不能仅凭源码推断节点、组织、TLS 证书路径或账户证书路径。复现时使用原已验证配置，或由自己有权限管理的长安链环境生成相应配置。三个身份应正确且不同。

新应用目录私下配置合法身份及证书引用，保留原 TLS 验证方式。`settings.example.json` 仅定义源码读取的键，不包含完整网络配置或默认身份。已有网络不重新部署和绑定。

已有环境继续使用原 `users.json`。新环境安装运行依赖后可执行 `python tools/create_users.py`，交互生成密码哈希，不覆盖已有文件、不生成链上账户。生成文件不得提交版本库。

原 app.py 每次启动重新生成会话密钥，因此重启后需登录；启动还会读取链上身份。`tools/check_package.py` 不导入应用、不连接链，适合离线检查。

`requirements.txt` 提取了原环境记录中的 Flask 运行依赖版本，未采用猜测的最新版。原完整记录含 ROS 包，仍保留以便追溯。应用没有 Node 构建步骤，也没有 Joi 依赖。

本次使用已有本地 Jinja 环境检查模板，不等于在全新 Linux 环境完整安装全部依赖。Go 编译以现有 go.mod、go.sum 为准。
