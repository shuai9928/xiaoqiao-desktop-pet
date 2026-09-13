# 小乔 · 时之魔女

一个 Windows 桌面宠物：保留二次元立绘，用连续深度网格、分部位跟随和柔和光影呈现小角度 2.5D 动作。

![小乔](assets/main.png)

## 能做什么

- 摸头、挠痒、拖动、摇晕、甩出、跳舞、转圈、接光球、睡觉和叫醒。
- 暗紫星金互动卡片、表情贴纸、气泡、聊天窗和本地角色语音。
- 星光与好感养成、番茄钟、提醒、小游戏和安静陪伴。
- 可选 Gemini AI 聊天、记忆，以及找文件、打开应用等本机助手功能。
- Tkinter + PIL + Win32 分层窗口，不需要游戏引擎。只支持 Windows。

这是小角度的 2.5D 演出，不是可任意旋转的三维模型。自然立体感包括头部、身体、帽沿/发梢分速跟随、柔光、悬浮投影，以及五官随同一网格变形。

## 从源码运行

建议 Windows 10/11、Python 3.12–3.14（包含 Tkinter）。本机验证使用 Python 3.14。

```powershell
git clone https://github.com/shuai9928/xiaoqiao-desktop-pet.git
cd xiaoqiao-desktop-pet
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (!(Test-Path assets\ai_config.json)) { Copy-Item assets\ai_config.example.json assets\ai_config.json }
.\.venv\Scripts\python.exe pet.py
```

不配置密钥也能使用桌宠动作、语音、提醒和小游戏。程序运行后右键小乔打开互动卡片；“更多”可进入完整菜单，包括设置和退出。

### 启用 AI（可选）

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

在右键菜单的 AI 设置中配置自己的 Gemini 密钥，并启用 AI。模型名称也可在本机 `assets/ai_config.json` 中调整。API 由使用者自行申请和承担费用；不要把实际配置提交到仓库。

## 常用操作

| 操作 | 反馈 |
| --- | --- |
| 左键点头 / 点身体 | 摸头 / 挠痒 |
| 按住拖动 | 移动；快速松手可以甩出 |
| 滚轮 | 顺毛 |
| 双击 | 时间魔法 |
| 中键 | 随机动作 |
| 右键 | 聊天、喂糖、魔法、跳舞、玩球、睡觉/叫醒 |
| 卡片中的“更多” | 完整菜单、设置、退出 |

详细玩法见 [CONTENTS.md](CONTENTS.md)。

## 数据与隐私

配置、提醒、聊天记录和长期记忆保存在本机，已加入 `.gitignore`。本仓库使用全新的公开提交历史，不包含开发者的个人存档、聊天记忆、API 密钥或旧 Git 历史。

AI 开启后，对话及相关记忆会发送给配置的模型服务；请求分析剪贴板或屏幕时，相应内容也可能发送。找文件、打开/关闭应用等助手操作在使用者自己的电脑上执行。请了解这些行为后再启用相关功能。

`--debug-state` 会把界面状态（可能含聊天文字）写入 `pet_state.json`，只应在需要排查问题时使用。

## 开发与测试

```powershell
# 在临时副本运行，隔离个人数据并关闭真实 AI
.\.venv\Scripts\python.exe tools\run_checks.py
# 仅单元与模拟 UI 检查（供 CI 使用）
.\.venv\Scripts\python.exe tools\run_checks.py --unit-only
# 发布前检查 Git 跟踪文件是否包含运行数据、密钥或本机路径
.\.venv\Scripts\python.exe tools\check_public_files.py
```

完整检查会短暂创建测试桌宠，结束后关闭。不要直接在日常运行目录执行 `test_pet.py`；使用上面的隔离入口。

| 文件 | 职责 |
| --- | --- |
| `pet.py` | 窗口、交互、状态机、聊天 UI、音效 |
| `depth_model.py` | 连续深度网格、部位跟随、光照与阴影缓存 |
| `fx.py` | 法阵、粒子和特效缓存 |
| `ai_chat.py` | 可选 AI、记忆、回复解析 |
| `agent.py` | 本机助手意图与执行 |
| `zcode_notify.py` | 可选 ZCode 完成/待确认通知 |
| `build_release.py` | Windows 打包与发布副本净化 |

开发决策见 [EXPERIMENTS.md](EXPERIMENTS.md)，参与贡献见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 打包 Windows 程序

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe build_release.py
```

输出 `release/DesktopPet-Windows-x64.zip`。打包脚本会清除发布包里的密钥和记忆；对外发布前仍应检查压缩包内容，不要直接上传自己的日常运行目录。仓库首次公开包含源码与素材，尚未提供经过本轮验证的预编译安装包。

## 许可证与素材

项目源码采用 [MIT License](LICENSE)。角色图片、贴纸、音乐和语音**不自动适用 MIT**，详见 [ASSET_LICENSES.md](ASSET_LICENSES.md)。维护者已确认这些素材可随本仓库公开分发；该说明不额外授予商用、修改或再次分发素材的权利。

这是个人桌宠项目，不代表相关角色或素材权利方的官方产品。
