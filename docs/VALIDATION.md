# 工程验证记录

检查日期：2026-11-27。机器可读结果为 [validation-results.json](validation-results.json)。

| 检查 | 结果 | 说明 |
|---|---|---|
| 源码传输包 CRC 与文件清单 | PASS | 13 个文件与导出清单逐项匹配 |
| 原始源码字节一致性 | PASS | 未修改 13 个导出文件 |
| 截图完整性 | PASS | 38 张原图可解码，SHA-256 一致 |
| Python 语法 | PASS | 四个原 Python 文件及两个新增工具 |
| Jinja 编译 | PASS | base、index、shop、v10_overview、verify |
| 模板渲染 | MOCK ONLY | 17 组：登录、双端、空状态、回执、读取失败、商城状态、公共徽章查验 |
| JavaScript 语法 | PASS | 对渲染后脚本执行 node --check |
| 新环境完整依赖安装 | NOT RUN | requirements.txt 版本提取自原环境记录 |
| Go 合约重编译 | NOT RUN | 本次无 Go；保留原编译、部署截图与 go.sum |
| 原链写入与完整业务回归 | NOT RUN | 本次没有重跑验收或资产操作 |
| 三个精确桌面视口矩阵 | NOT RUN | 有大窗口、长图及新版窄窗口证据 |

执行 `python tools/check_package.py` 可重做离线检查。工具不导入 app、bridge 或 shop，不读取实际身份配置、数据库和凭据，不启动服务、不连接原链。模拟上下文仅用于 Jinja 内存渲染，没有写入正式界面或资产状态。

`acceptance.py` 保留原实验步骤，内含 NFT 暂停/恢复、奖励与负向调用，不能作为只读检查执行。截图中的业务 PASS 是用户原实验记录，不冒充本次重新执行。

源文件和截图来源分别由 source-export-manifest.json、screenshot-manifest.json 追踪。根目录 MANIFEST.sha256 覆盖交付文件（不含自身）。上传后在最终 ZIP 旁另存远端提交与摘要校验记录。

## 后续演示材料说明

新增docs/网页演示示例视频.mp4，作为网站功能与交互展示材料。录制操作发生在此前实验验证之后，不表示重新执行了原验收用例；本文件中原有检查结果及验证范围保持不变。
