# 开发工具

[开发指南](../docs/DEVELOPMENT.md) · [测试说明](../tests/README.md)

从仓库根目录运行：

| 命令 / 目录 | 用途 |
| --- | --- |
| `py tools/run_checks.py` | 隔离当前核心回归与必需旧引擎兼容烟测 |
| `py tools/run_checks.py --unit-only` | 当前单元检查，供CI使用 |
| `py tools/run_checks.py --legacy` | 额外检查退役功能 |
| `py tools/check_public_files.py` | 跟踪文件的运行数据、密钥和本机路径检查，只输出位置 |
| `py tools/check_docs.py` | 本地链接、锚点和媒体检查 |
| `py tools/preview_workspace.py` | 当前工作台离线预览，只用合成数据，不读取会话或调用模型 |
| `tools/assets/` | 素材派生与布局导出，手动开发工具 |
| `tools/diagnostics/` | 性能、特效与浸泡探针，不自动运行 |
| `tools/release/build_release.py` | Windows打包、发布副本净化与本机存档回填 |
| `tools/legacy/` | 旧布局补丁、切层、音频制作和旧演示 |

素材生成器可能写素材，在独立开发副本执行。探针的额外依赖见脚本说明。旧真实AI质量脚本和通配重启脚本均已归档，不进入默认检查。

公开文件检查仅覆盖跟踪或暂存文件；文档检查不验证外部网站。打包工具存在不等于已经发布验收过的exe。
