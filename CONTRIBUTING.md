# 参与贡献

欢迎提交问题和 Pull Request。请描述触发步骤、预期/实际行为、Windows/Python 版本及缩放比例。

先读[开发指南](docs/DEVELOPMENT.md)了解模块职责、检查范围和演示复现方式；所有文档入口见[文档导航](docs/README.md)。

- 安装 `requirements.txt`，使用 `python tools/run_checks.py` 在隔离副本中测试。
- 动作采用经过时间计算，避免帧率变化影响位移或重复触发一次性特效。
- UI 修改请验证键盘操作、小屏、多显示器负坐标和 80%–175% 缩放。
- 不提交聊天、记忆、真实密钥、桌面截图或运行日志。报错内容请先脱敏。
- 提交前运行 `python tools/check_public_files.py`。
- 菜单、动作或设置变更应同步更新 README、互动手册与 `CHANGELOG.md`，运行 `python tools/check_docs.py` 检查本地链接。
- 图文展示使用隔离样本；说明图片是实际渲染、真实控件截图还是示意图，并为动画提供静态备选。
- 新增依赖或素材时注明来源与许可，不把第三方素材归入源码 MIT 许可。

贡献源码时，表示同意按本项目 MIT 许可证提供该源码贡献。
