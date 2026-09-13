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
import json
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
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


README = """桌宠小乔 · 使用说明
=====================================

【怎么启动】
  双击 DesktopPet.exe 就行。不需要安装 Python 或任何其他东西。

【第一次打开会问我要密钥?】
  那是给她"聊天"用的 Gemini API 密钥,免费申请:
      https://aistudio.google.com/apikey
  登录 Google 账号 -> Create API key -> 复制 AIza 开头的那串 -> 粘进去。

  不填也完全可以用!她照样会动、会说话、会做表情、能陪你,
  只是不能进行 AI 对话。想以后再填:右键她 -> 设置 AI 密钥。

【怎么玩】
  左键点头     摸摸头(连摸 6 次有惊喜)
  左键点身体   挠痒痒
  双击         时间魔法
  滚轮         顺毛(多滚几下她会害羞)
  中键         随机小惊喜(可能转圈圈哦)
  按住不动     戳脸彩蛋(0.9 秒,别拖动)
  拖动         把她搬到别处;快速左右摇会把她摇晕
  右键         菜单(聊天/一起玩/小本事/设置/退出)

【星光与小游戏】
  她靠"星光值"维持魔法,会随时间慢慢消耗:
      右键菜单顶部能看到星光值;低于 25% 她会主动提醒你
      「一起玩 ▸ 吃星光糖果」可以补充 40 点
      星光很低时她周围的星星会变稀疏,台词也会饿兮兮
  「撒一把星星 ★」会撒出 5 颗会发光的金星星:
      趁它们消失前点一下就能接住,每颗 +2 星光
      全部接住有奖励;速度够快还有"神速"结算
      单局最高纪录会被记住,破纪录她会专门庆祝

【小细节(慢慢发现)】
  久别重逢   让她睡一会儿,超过 10 分钟后再摸她
  打喷嚏     偶尔会发生,稀有
  吹泡泡     偶尔会发生
  夜间流星   深夜(22 点后)挂机时偶尔划过,快许愿
  被冷落     15 分钟不理她,她会委屈;睡着时会说梦话
  节日       元旦/儿童节/国庆/程序员节(1024)/圣诞等当天有特别问候
             春节/元宵/端午/中秋等农历节日也都记得

【她还能帮你做事】
  在聊天框里说:
      打开微信            启动软件
      关闭QQ              关掉软件
      搜索一下 天气        网页搜索
      打开下载文件夹       打开文件夹
      5分钟后提醒我喝水    定时提醒
      帮我找 报告.pdf      找文件(找到后自动在资源管理器里定位)
      看看屏幕,这是什么错  截屏发给小乔,让她看图回答
      翻译剪贴板           中译英 / 英译中
      来个番茄钟           专注 25 分钟,到点叫你休息
      今天天气怎么样       查天气(先在右键菜单里设置城市)

  聊天里也能直接使唤她(本地识别,不花额度):
      摸摸头 / 挠痒痒 / 转个圈 / 跳个舞 / 唱首歌
      撒星星 / 施魔法 / 睡一觉
      猜数字              她想一个 1~50 的数,直接报数字猜
                          猜中 +5 星光;说「不玩了」随时结束
      (带"别/不要"的句子会正常交给 AI 回答)

  右键菜单(分了三组,都在子菜单里):
      「一起玩 ▸」
          撒一把星星 ★         星星雨
          跳个舞 ♬ / 伸懒腰 / 发会儿呆 / 过来我这边
          后空翻 🤸 / 挥挥手 👋 / 打个滚 / 魔法变身 ✨
              (变身 = 30 秒星光形态:发光+星尘尾迹)
          转圈圈💫(真旋转) / 吃星光糖果 / 报时 / 睡一觉
          吃星光糖果           补充星光值
          现在几点?            报时
          睡一觉 / 叫醒
          石头剪刀布 ✊        和她猜拳(有战绩统计)
      「小本事 ▸」
          定个提醒…           弹窗设置一次性提醒
          帮我找文件…         搜桌面/文档/下载等常见目录
          看看我的剪贴板 ✦    让小乔总结你复制的内容
          翻译剪贴板 ✦        中译英 / 英译中
          看看我的屏幕 ✦      截屏发给小乔,问她屏幕上的问题
          现在天气如何?        查天气(先用"设置城市…"选城市)
          番茄钟              专注 25/50 分钟,到点叫你休息
          喝水提醒            每隔一段时间催你喝水(可关)
          AI 主动搭话          开着时她会自己找你聊天
          (菜单顶部还会显示「陪伴第 N 天」——她记着你们在一起多久了)
      「设置 ▸」
          语音(全部声音)      反应音效 + 朗读的总开关
          开口说话            只控制聊天朗读,不动反应音效
          开机自启            打开后每次开机她自己出现
          偷看窗口            开着时她会瞄一眼前台程序,同一种用太久
                              会念叨你去休息(隐私考虑可随时关)
          大小 / 窗口置顶 / 鼠标穿透
          设置 AI 密钥… / 清空聊天记录 / 设置城市…

  每天早上第一次和她打招呼时,她会顺手播报今天的天气(需要设置过城市)。

  声音说明:摸头、魔法、弹跳这些反应音是内置的,最多每 5 秒响一次;
  聊天朗读优先用在线的可爱声线合成(需要网络),没网时自动退回
  Windows 系统语音。全部静音用「语音(全部声音)」开关。

  配合 ZCode 使用:配置好 hook 后,ZCode 每段任务结束她会播报,
  弹确认框时她会喊你回来点确认(包里的 zcode_notify.py 就是干这个的,
  需要你电脑上有 Python)。

  注意:出于安全考虑,"卸载软件"功能已关闭。

【想换成自己的立绘?】
  替换 assets 目录里的图片即可:
      assets/main.png        主立绘(透明背景 PNG)
      assets/expr/*.png      表情贴纸
      assets/decor_*.png     漂浮装饰
  换完可能需要调 assets/config.json 里的 eyes 坐标(眨眼时眼皮的位置)。

【Windows 提示"未知发布者"怎么办?】
  因为这个程序没有购买代码签名证书,不是有毒。
  点"更多信息" -> "仍要运行"即可。

【关掉她】
  右键 -> 退出。或者在托盘图标上右键退出。

【你的数据存在哪】
  聊天记录和设置都存在本程序目录下,不会上传到任何地方。
  只有你主动聊天时,那句话才会发给 Google Gemini。
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
