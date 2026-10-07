# -*- coding: utf-8 -*-
"""把桌宠打包成可以直接转发给别人的 Windows 独立程序。

产出:release/DesktopPet-Windows-x64.zip
解压后双击 DesktopPet.exe 即可运行,对方不需要装 Python 或任何环境。

要点
----
* onedir 而不是 onefile:启动快、写配置直观、杀软误报率低。
* assets/ 放在 exe 旁边(不塞进 _internal),这样对方想换立绘直接替换文件。
  pet.py 冻结时用 dirname(sys.executable) 作根目录,正好对上。
* 发布副本要净化:不带 API 密钥、不带聊天记录、不带 AI 记住的个人信息。
  源项目不受影响。
"""

from pathlib import Path
import sys
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "tests"))

import json
import os
import shutil
import subprocess
import sys
import zipfile

HERE = str(Path(__file__).resolve().parents[2])
DIST = os.path.join(HERE, "dist")
BUILD = os.path.join(HERE, "build")
RELEASE = os.path.join(HERE, "release")
APP = "DesktopPet"
OUT = os.path.join(RELEASE, APP)

# 绝不能进入发布包的文件(私人凭证 / 个人数据 / 运行时垃圾)
EXCLUDE = {
    "chat_history.json", "pet_settings.json", "pet_state.json",
    "pet_cmd.json", "pet_error.log",
    # 目录也要能排掉:响度重制留下的旧音频备份有 3.7MB,
    # 之前被 copytree 整个拷进发布包,而 os.remove 对目录静默失败
    "audio_peaknorm_backup", "audio_v2",
}

# 本机重装时要保住的运行数据(release/DesktopPet 里那只的数据)。
# 重建会 rmtree 整个 release —— 先备份、打完 zip 再回填:zip 保持净化,
# 本机数据不丢。ai_config.json 含密钥/密文,同样只回填、不进 zip。
RUNTIME_FILES = ("pet_settings.json", "chat_history.json",
                 "pet_reminders.json")
RUNTIME_ASSET_FILES = ("memories.json", "ai_config.json")


def backup_runtime():
    """重建前把 release/DesktopPet 的运行数据拷到临时目录。首次构建没有
    旧数据,安静跳过。"""
    import tempfile
    if not os.path.isdir(OUT):
        return None
    tmp = tempfile.mkdtemp(prefix="pet_runtime_")
    kept = 0
    for name in RUNTIME_FILES:
        src = os.path.join(OUT, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(tmp, name))
            kept += 1
    for name in RUNTIME_ASSET_FILES:
        src = os.path.join(OUT, "assets", name)
        if os.path.isfile(src):
            os.makedirs(os.path.join(tmp, "assets"), exist_ok=True)
            shutil.copy2(src, os.path.join(tmp, "assets", name))
            kept += 1
    log(f"已备份本机运行数据 {kept} 项")
    return tmp


def restore_runtime(tmp):
    """zip 打完之后把数据回填进 OUT(zip 已经封口,不会带个人数据)。"""
    if not tmp or not os.path.isdir(tmp):
        return
    for name in RUNTIME_FILES:
        src = os.path.join(tmp, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(OUT, name))
    for name in RUNTIME_ASSET_FILES:
        src = os.path.join(tmp, "assets", name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(OUT, "assets", name))
    shutil.rmtree(tmp, ignore_errors=True)
    log("已回填本机运行数据(设置/聊天/提醒/记忆/密钥)")


def log(msg):
    print(f"[build] {msg}", flush=True)


def make_icon():
    """用立绘生成 .ico,让 exe 有个像样的图标。"""
    from PIL import Image
    src = os.path.join(HERE, "assets", "main.png")
    if not os.path.exists(src):
        return None
    im = Image.open(src).convert("RGBA")
    # 裁到不透明区域再放进正方形画布,避免图标里人物偏一边
    bb = im.getbbox()
    if bb:
        im = im.crop(bb)
    side = max(im.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    ico = os.path.join(BUILD, "pet.ico")
    os.makedirs(BUILD, exist_ok=True)
    canvas.save(ico, sizes=[(256, 256), (128, 128), (64, 64),
                            (48, 48), (32, 32), (16, 16)])
    log(f"图标已生成 {ico}")
    return ico


def run_pyinstaller(icon):
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed",                 # 不弹黑色控制台窗口
        "--name", APP,
        "--distpath", DIST,
        "--workpath", BUILD,
        "--specpath", BUILD,
        # google-genai 的子模块 PyInstaller 静态分析抓不全,显式收集
        "--collect-all", "google.genai",
        "--collect-submodules", "pystray",
        "--collect-submodules", "PIL",
        "--hidden-import", "pystray._win32",
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.messagebox",
        "--hidden-import", "tkinter.simpledialog",
        # 用不到的大件排除掉,能省几十 MB
        # pet.py 已经不用 numpy 了(网格太小,反而是 numpy 的调用开销更大)。
        # 显式排除,免得 PIL 之类的可选依赖又把它拖进来。
        "--exclude-module", "numpy",
        "--exclude-module", "matplotlib",
        "--exclude-module", "scipy",
        "--exclude-module", "pandas",
        "--exclude-module", "pytest",
        "--exclude-module", "IPython",
    ]
    if icon:
        args += ["--icon", icon]
    args.append(os.path.join(HERE, "pet.py"))
    log("开始 PyInstaller 打包(第一次会比较慢)…")
    r = subprocess.run(args, cwd=HERE)
    if r.returncode != 0:
        raise SystemExit(f"PyInstaller 失败,返回码 {r.returncode}")
    log("PyInstaller 完成")


def sanitize_assets(dst_assets):
    """净化发布副本里的配置:清空密钥和个人记忆。源项目不动。"""
    # 1) API 密钥留空 —— 对方首次启动会被引导填自己的
    cfg_path = os.path.join(dst_assets, "ai_config.json")
    cfg = {
        "enabled": True,
        "api_key": "",
        "model": "gemini-flash-lite-latest",
        "greet_interval_min": 30,
        "_说明": ("首次启动会弹窗引导填写。也可以直接把 Gemini 密钥粘到 api_key 里。"
                  "密钥免费申请:https://aistudio.google.com/apikey"),
    }
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    log("已清空 API 密钥")

    # 2) 清空 AI 记住的个人信息
    mem = os.path.join(dst_assets, "memories.json")
    with open(mem, "w", encoding="utf-8") as f:
        json.dump({"facts": []}, f, ensure_ascii=False, indent=1)
    log("已清空 memories.json")

    # 3) 人设里的「研究员/程序员」换成中性说法
    per = os.path.join(dst_assets, "personality.json")
    try:
        with open(per, encoding="utf-8") as f:
            d = json.load(f)
        d["relationship"] = "主人是小乔最重要的人,小乔住在主人电脑里陪伴主人"
        with open(per, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        log("已中性化 personality.json")
    except Exception as e:
        log(f"personality.json 处理跳过: {e}")


def assemble():
    src_app = os.path.join(DIST, APP)
    if not os.path.isdir(src_app):
        raise SystemExit(f"没找到 PyInstaller 输出: {src_app}")
    if os.path.isdir(RELEASE):
        shutil.rmtree(RELEASE)
    os.makedirs(RELEASE, exist_ok=True)
    shutil.copytree(src_app, OUT)
    log(f"已复制程序主体到 {OUT}")

    # assets 放在 exe 旁边,方便对方替换立绘
    shutil.copytree(os.path.join(HERE, "assets"), os.path.join(OUT, "assets"))
    for name in EXCLUDE:
        p = os.path.join(OUT, "assets", name)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)     # os.remove 删不掉目录
        elif os.path.exists(p):
            os.remove(p)
    sanitize_assets(os.path.join(OUT, "assets"))

    # ZCode 联动小脚本(需要对方机器上有 Python 才用得上,带上无害)
    zn = os.path.join(HERE, "zcode_notify.py")
    if os.path.exists(zn):
        shutil.copy2(zn, os.path.join(OUT, "zcode_notify.py"))
        # zcode_notify 要用它(动作写成人话、文件锁),少了会话灯就不更新
        shutil.copy2(os.path.join(HERE, "ai_lights_core.py"), os.path.join(OUT, "ai_lights_core.py"))
        shutil.copy2(os.path.join(HERE, "task_directions.py"), os.path.join(OUT, "task_directions.py"))

    with open(os.path.join(OUT, "使用说明.txt"), "w", encoding="utf-8") as f:
        f.write(README)
    log("已写入使用说明")


def zip_release():
    zpath = os.path.join(RELEASE, f"{APP}-Windows-x64.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, _, files in os.walk(OUT):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, RELEASE))
    mb = os.path.getsize(zpath) / 1024 / 1024
    log(f"压缩完成 {zpath}  ({mb:.1f} MB)")
    return zpath


README = """小乔 · 时之魔女（核心陪伴版）

启动：DesktopPet.exe。当前左侧角色、右侧AI阶段/方向与已用额度。
右键聊天/喂糖/场景/休息，双击聊天，中键AI工作信息。拖动移动，滚轮缩放。
AI聊天可选，使用自己的配置；主动聊天才请求模型，任务观察不调用模型。
个人设置、聊天和配置保存在程序目录，不提交或公开。
更新先从菜单退出原实例，再启动新版。
完整说明：https://github.com/shuai9928/xiaoqiao-desktop-pet
"""


def main():
    log(f"Python {sys.version.split()[0]}")
    runtime = backup_runtime()
    icon = make_icon()
    run_pyinstaller(icon)
    assemble()
    z = zip_release()
    restore_runtime(runtime)
    log("=" * 50)
    log(f"完成: {z}")


if __name__ == "__main__":
    main()
