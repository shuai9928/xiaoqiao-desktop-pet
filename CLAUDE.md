# Claude 开发入口

从GitHub `main` 获取当前版本。先读 [README](README.md)、[AGENTS](AGENTS.md) 和[开发指南](docs/DEVELOPMENT.md)。

实际改动落在根目录生产模块，测试放 `tests/`，维护记录放 `docs/design/`。`docs/archive/` 的参考图与旧交接只用于回顾，不可覆盖当前实现。

Windows原生日志采集不代表Claude云端会话已接入。云端只能报告实际运行过的检查，不能把参考图、离线渲染或Linux测试当成Windows桌面验收。
