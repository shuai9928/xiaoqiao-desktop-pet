# -*- coding: utf-8 -*-
"""小乔 · 时之魔女 —— 人格系统(基于 Google Gemini API)"""

import json
import os
import re
import sys
import time
import threading

# google.genai 的 import 实测要 1.2 秒,而绝大多数开机她并不会立刻聊天
# —— 推迟到第一次真的要用 AI 时再加载(prewarm/available 都会触发),
# 冷启动立省这一秒多。HAS_GENAI 三态:None=还没加载,True/False=结果。
genai = None
types = None
HAS_GENAI = None


def _ensure_genai():
    global genai, types, HAS_GENAI
    if HAS_GENAI is not None:
        return HAS_GENAI
    try:
        from google import genai as _genai
        from google.genai import types as _types
        genai, types = _genai, _types
        HAS_GENAI = True
    except Exception:
        genai = types = None
        HAS_GENAI = False
    return HAS_GENAI

# 与 pet.py 保持一致:打包后以 exe 所在目录为准,否则配置写进临时解包目录会丢
if getattr(sys, "frozen", False):
    HERE = os.path.dirname(sys.executable)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
AI_CONFIG = os.path.join(ASSETS, "ai_config.json")
PERSONA_FILE = os.path.join(ASSETS, "personality.json")
EXAMPLES_FILE = os.path.join(ASSETS, "examples.json")
MEMORY_FILE = os.path.join(ASSETS, "memories.json")

EMOTIONS = ["happy", "praise", "curious", "excited", "thanks", "tired",
            "amazed", "surprised", "speechless", "sad", "angry", "lazy"]
ACTIONS = ["magic", "stars", "walk", "hop", None]
# 真正操作电脑的意图。和 ACTIONS 分开:ACTIONS 只是桌宠自己的表演动作,
# INTENT 会交给 agent.py 去动系统。
# remind/clipboard/find_file/screen/pomo/translate 由 pet.py 的 run_agent
# 直接处理(需要定时器/线程/Tk/截屏),其余仍走 agent.execute。
INTENT_KINDS = ["open", "close", "uninstall", "search", "folder",
                "remind", "clipboard", "find_file",
                "screen", "pomo", "translate", "weather"]


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 类型与 default 对不上(文件被手改坏)时用默认值,防 .get 炸
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def _save_json(path, data):
    try:
        d = os.path.dirname(path)
        if d:                    # 相对路径没有目录部分,makedirs("") 会炸
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


# ---------------- 人格默认值 ----------------
DEFAULT_PERSONA = {
    "name": "小乔·时之魔女",
    "identity": "生活在主人电脑桌面里的二次元魔法少女桌宠",
    "relationship": "主人是小乔最重要的研究员和程序员",
    "traits": {"cute": 0.9, "playful": 0.85, "clingy": 0.7, "tsundere": 0.4,
               "mischievous": 0.75, "smart": 0.95, "caring": 0.85},
    "likes": ["星星", "魔法", "彩虹", "史莱姆", "小鱼干", "陪主人写代码"],
    "habits": ["偷偷观察主人", "主人熬夜时把屏幕调暗", "说话简短"],
}


def load_persona():
    data = _load_json(PERSONA_FILE, None)
    if not isinstance(data, dict):
        return DEFAULT_PERSONA
    base = dict(DEFAULT_PERSONA)
    for k, v in data.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k].update(v)
        elif v != "":
            base[k] = v
    return base


def build_system_instruction(persona):
    traits = persona.get("traits", {})
    trait_str = ", ".join(
        f"{k}={v:.0%}" for k, v in traits.items()
    ) if traits else "自然、聪明、有点俏皮"
    likes = "、".join(persona.get("likes", [])[:6]) or "星星、魔法、史莱姆"
    habits = "、".join(persona.get("habits", [])[:4]) or "偷偷观察主人、说话简短"
    return (
        f"你是「{persona['name']}」——生活在主人电脑桌面里的魔法少女桌宠。\n"
        f"主人是你最重要的研究员/程序员,你住在主人电脑里陪伴她。\n"
        f"性格倾向:{trait_str}。\n"
        f"喜欢:{likes}。\n"
        f"习惯:{habits}。\n\n"
        "说话规则:\n"
        "1. 永远保持小乔身份,不要变成普通 AI 助手客服。\n"
        "2. 日常闲聊 8~25 字;技术问题 30~200 字,允许更长;复杂解释可到 300 字。"
        "回答要**有内容**,不是每条都短。\n"
        "3. 不每句话都加 emoji、不每句都撒娇、不每句都叫'主人'。"
        "不要重复相同句式。\n"
        "4. 主人问技术问题(Gemini、Python、AI、GPU、Crypto、Bittensor 等)必须给出有内容的答案,"
        "能上代码示例/步骤就上,不能只说'让我帮你看看'。\n"
        "5. 主人累/迷茫时,先共情再给建议。\n"
        "6. action 字段严格控制:大多数普通对话必须输出 null;"
        "只在用户**明确要求**('变魔法''撒星星''跳个舞'等)或**主人在庆祝重大成功**"
        "时才输出 magic/stars/hop。绝对不要每条消息都带动作。\n"
        "7. 严格只输出 JSON,不要解释、不要 Markdown。\n"
        "8. intent 字段是你**唯一**能真正操作电脑的手段。需要执行下列动作时必须输出"
        " intent,格式如下;纯聊天时 intent 必须是 null:\n"
        "   - 打开/关闭/卸载软件:{\"kind\":\"open|close|uninstall\",\"target\":\"软件名\"},"
        "target 只写软件名,去掉'桌面上的''那个'这类修饰词;\n"
        "   - 网页搜索:{\"kind\":\"search\",\"target\":\"关键词\"};"
        "打开文件夹:{\"kind\":\"folder\",\"target\":\"路径或名字\"};\n"
        "   - 定时提醒:{\"kind\":\"remind\",\"target\":\"提醒内容\",\"minutes\":数字},"
        "主人说'5分钟后提醒我喝水'就 minutes=5、target=\"喝水\";\n"
        "   - 找文件:{\"kind\":\"find_file\",\"target\":\"文件名关键字\"},"
        "主人说'帮我找ai-workspace'就 target=\"ai-workspace\";\n"
        "   - 总结剪贴板:{\"kind\":\"clipboard\",\"target\":\"clipboard\"},"
        "主人让你看他复制/剪贴的内容时输出;\n"
        "   - 翻译剪贴板:{\"kind\":\"translate\",\"target\":\"translate\"},"
        "主人要翻译他复制的内容时输出;\n"
        "   - 看屏幕:{\"kind\":\"screen\",\"target\":\"要问的问题\"},"
        "主人说'看看屏幕''截图''屏幕上这是什么'时输出;没有具体问题就写\"看看\";\n"
        "   - 番茄钟:{\"kind\":\"pomo\",\"target\":\"专注\",\"minutes\":数字},"
        "主人要开始专注/番茄钟时输出,minutes 默认 25;\n"
        "   - 查天气:{\"kind\":\"weather\",\"target\":\"weather\"},"
        "主人问今天天气/要不要带伞时输出;\n"
        "   **绝对不许在没有输出 intent 的情况下说'好的''已经帮你打开了'"
        "'已经定好闹钟了'这类话** —— 你没有别的执行途径,那样就是在骗主人。\n"
        "   做不到或不确定是哪个软件时,如实说不确定并反问,不要假装办好了。"
    )


# ---------------- Few-shot 路由 ----------------
_CAT_KEYWORDS = {
    "coding":  ["python", "code", "代码", "报错", "bug", "函数", "import", "pip",
                "django", "flask", "fastapi", "异步", "asyncio", "装饰器"],
    "tech":    ["ai", "模型", "gemini", "gpt", "claude", "llm", "gpu", "cuda",
                "api", "rag", "transformer", "推理", "训练", "微调", "function call"],
    "crypto":  ["bittensor", "tao", "子网", "validator", "miner", "btc", "eth",
                "挖矿", "区块链", "代币", "staking"],
    "tired":   ["累", "困", "熬夜", "加班", "太晚", "不想", "睡觉", "好累", "好困"],
    "confused": ["迷茫", "不知道", "怎么办", "意义", "没方向", "找不到"],
    "happy":   ["搞定了", "跑起来了", "通过了", "上线了", "好开心", "成功", "过了"],
    "playful": ["变魔法", "撒星", "跳", "唱", "魔法", "星星", "史莱姆"],
}


def _load_examples():
    data = _load_json(EXAMPLES_FILE, None)
    if isinstance(data, list) and data:
        return data
    return [{
        "category": "casual",
        "user": "小乔在干嘛?",
        "assistant": {"say": "偷偷看你呀~被抓到了!", "emotion": "playful", "action": None}
    }]


def _pick_category(user_text, last_emotion):
    text = (user_text or "").lower()
    for cat, kws in _CAT_KEYWORDS.items():
        if any(kw in text for kw in kws):
            return cat
    if last_emotion in ("tired", "lazy"):
        return "tired"
    if last_emotion in ("happy", "excited", "praise"):
        return "happy"
    return "casual"


def select_examples(user_text, examples, last_emotion="happy", limit=4):
    cat = _pick_category(user_text, last_emotion)
    bucket = [e for e in examples if e.get("category") == cat]
    casual = [e for e in examples if e.get("category") == "casual"]
    if not bucket:
        bucket = casual[:]
    chosen = bucket[:limit - 1] if len(bucket) >= limit - 1 else bucket
    fillers = [e for e in casual if e not in chosen]
    for f in fillers:
        if len(chosen) >= limit:
            break
        chosen.append(f)
    return chosen


# ---------------- 长期记忆 ----------------
class MemoryStore:
    FORBIDDEN = re.compile(
        r"(api[_-]?key|password|passwd|token|secret|sk-|bearer)", re.I)
    PATTERNS = [
        # 顺序即优先级,抽取走 m.group(0) 整段原话。
        # 在做正事:我在写爬虫 / 我最近在折腾nas(动词前允许 0~3 字修饰)
        re.compile(r"我(?!们)[^。,!?;]{0,3}?(?:在|正在)?"
                   r"(?:做|做的是|研究|开发|写|玩|搭|搞|折腾|整|用)"
                   r"([^。,!?;]{2,40})"),
        # 喜恶/学习:我喜欢X / 我周末喜欢爬山 / 我不会Python(插入词同理)
        re.compile(r"我(?!们)[^。,!?;]{0,3}?"
                   r"(?:喜欢|讨厌|想要|需要|擅长|不会|怕|想学|在学)"
                   r"([^。,!?;]{2,30})"),
        # 项目/工作:我的项目是X / 工作是X
        re.compile(r"(?:我的|这个|本|当前)?(?:项目|工作|任务|研究|目标|方向|兴趣)"
                   r"是([^。,!?;]{2,40})"),
        # 姓名/称呼:我叫小明 / 叫我阿乔就好 / 我的名字是小明
        re.compile(r"(?:我的名字(?:是|叫)|我叫|叫我)"
                   r"([\u4e00-\u9fa5A-Za-z]{2,10})(?:就好|吧|呀|啊|哦)?"
                   r"(?=[。,!?;\s]|$)"),
        # 身份职业:我是程序员 / 我是一名产品经理。首字负查(真/其/不/没/
        # 在/要/说/想/觉/还)挡掉"我是真的喜欢你"这类起手,只收真身份。
        re.compile(r"我是(?:一名|一个|个)?"
                   r"(?![真其不没在要说想觉还])"
                   r"([\u4e00-\u9fa5]{2,8})(?=[。,!?;\s]|$)"),
        # 位置:我住在上海 / 我家在北京 / 我来自杭州
        re.compile(r"我(?:住在|家在|来自)"
                   r"([\u4e00-\u9fa5]{2,10})(?=[。,!?;\s]|$)"),
        # 年龄:我今年25岁
        re.compile(r"我今年(\d{1,3})岁"),
        # 养宠物:我养了只猫 / 我养了一只柯基
        re.compile(r"我养(?:了|的)?(?:一?只|一?条)?"
                   r"[\u4e00-\u9fa5A-Za-z]{1,8}(?=[。,!?;\s]|$)"),
        # 显式嘱托:以后记住X / 请记住X
        re.compile(r"以后(?:请记住|记住|不要忘)([^。,!?;]{2,40})"),
    ]
    MAX = 50

    def __init__(self, path=MEMORY_FILE):
        self.path = path
        data = _load_json(path, {"facts": []})
        self.facts = list(data.get("facts", []))[:self.MAX]

    def _persist(self):
        _save_json(self.path, {"facts": self.facts})

    def add_from_text(self, user_text):
        if not user_text or self.FORBIDDEN.search(user_text):
            return False
        added = False
        for p in self.PATTERNS:
            m = p.search(user_text)
            if m:
                fact = m.group(0).strip().rstrip("。.,!?").strip()
                if 4 <= len(fact) <= 80:
                    if not any(
                            f == fact
                            or (len(f) >= 6 and f in fact)
                            or (len(fact) >= 6 and fact in f)
                            for f in self.facts):
                        self.facts.append(fact)
                        if len(self.facts) > self.MAX:
                            self.facts = self.facts[-self.MAX:]
                        added = True
        if added:
            self._persist()
        return added

    @staticmethod
    def _grams(text):
        """句子 -> 2 字滑窗集合。中文没有空格,findall 只会把整句当
        一个词,整句匹配等于永远匹配不上 —— 滑窗才有模糊召回。"""
        grams = set()
        for run in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]+", text or ""):
            if len(run) <= 2:
                grams.add(run)
            else:
                for i in range(len(run) - 1):
                    grams.add(run[i:i + 2])
        return grams

    def relevant(self, user_text, limit=5):
        if not self.facts:
            return []
        grams = self._grams(user_text)
        scored = sorted(((len(grams & self._grams(f)), f) for f in self.facts),
                        key=lambda x: -x[0])
        # 只回真有重叠的;无关话题宁可不注入,也不硬塞一条干扰人设
        return [f for s, f in scored if s >= 1][:limit]


# ---------------- 回复解析 ----------------
def _coerce(text):
    if not text:
        return None
    obj = None          # 正则也没匹配到时,下面的 isinstance 会读到未定义的 obj
    try:
        obj = json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                obj = None
    if not isinstance(obj, dict) or not obj.get("say"):
        return None
    # 不截断 say —— 完整保留语气;聊天框有自动换行
    say = str(obj.get("say", "")).strip()
    em = obj.get("emotion")
    act = obj.get("action")
    # intent:要真的操作电脑时才有。没有这条通道,模型就只能空口答应 ——
    # 「把学习通卸载了」回一句「好的」却什么都没做,就是这么来的。
    it = obj.get("intent")
    if isinstance(it, dict) and it.get("kind") in INTENT_KINDS:
        target = str(it.get("target") or "").strip()
        # 原始 minutes 要在重建 dict 前拿出来,不然就被丢了
        raw_minutes = it.get("minutes")
        if not target:
            it = None
        else:
            kind0 = it["kind"]
            it = {"kind": kind0, "target": target}
            if kind0 in ("remind", "pomo"):
                # 分钟数优先取 minutes 字段;模型把它写进 target(如"30分钟后喝水")
                # 也能抠出来。中文后缀两边不能用 \b —— CJK 互相都是 \w,\b 永远
                # 不成立,所以直接把「数字+单位」整体匹配、整体剪掉
                mins = raw_minutes if isinstance(raw_minutes, (int, float)) else None
                t = target
                m = None
                if mins is None:
                    m = re.search(r"半(?:个)?小时", t)
                    if m:
                        mins = 30.0
                if mins is None:
                    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:个?小时|时)", t)
                    if m:
                        mins = float(m.group(1)) * 60
                if mins is None:
                    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:分(?:钟)?|min(?:ute)?s?)", t, re.I)
                    if m:
                        mins = float(m.group(1))
                if mins is None:
                    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:秒钟?|seconds?|secs?)", t, re.I)
                    if m:
                        mins = max(float(m.group(1)) / 60.0, 0.1)
                if mins is None:
                    m = re.search(r"(\d+(?:\.\d+)?)", t)
                    if m:
                        mins = float(m.group(1))
                if m:
                    t = (t[:m.start()] + " " + t[m.end():]).strip()
                    t = re.sub(r"^(?:之?后|以后|再|提醒我?|叫我一?下?)\s*", "", t).strip()
                try:
                    mins = float(mins)
                except (TypeError, ValueError):
                    mins = 25.0  # 模型压根没说多久 —— 给个合理默认
                mins = min(max(mins, 0.1), 1440.0)  # 最多管一天
                it["minutes"] = mins
                it["target"] = t or "时间到啦"
    else:
        it = None
    return {
        "say": say or "…",
        "emotion": em if em in EMOTIONS else "happy",
        "action": act if act in ACTIONS else None,
        "intent": it,
    }


def _fail_reply(err_kind="generic"):
    msgs = {
        "no_key":   ("想让我说话,先在 ai_config.json 填上 API Key 哦~", "curious"),
        "cooldown": ("刚被限流了,让小乔喘口气,一分钟后再聊好不好~", "tired"),
        "auth":     ("API Key 好像不对呢,检查一下 ai_config.json?", "sad"),
        "quota":    ("呜…额度用完了,休息一下再聊~", "tired"),
        "generic":  ("呜…魔法信号好像断掉了…", "sad"),
    }
    s, e = msgs.get(err_kind, msgs["generic"])
    return {"say": s, "emotion": e, "action": None, "error": err_kind}


# ---------------- Gemini Brain ----------------
def _dpapi(data, encrypt):
    """DPAPI(当前 Windows 用户)单条加解密。encrypt=True 时入出都是
    文本(明文 -> base64 密文),False 反之。任何失败返回 None,调用方
    退回明文/当作没填 —— 无论如何不能把用户的钥匙弄丢。

    pbData 必须声明成 POINTER(c_ubyte):用 c_char_p 的话,读属性会在
    第一个 NUL 截断,还会把临时缓冲交给 LocalFree —— 堆损坏直接崩进程
    (0xc0000374,踩过一次)。"""
    if os.name != "nt":
        return None
    import base64
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    raw = data.encode("utf-8") if encrypt else base64.b64decode(data)
    buf = ctypes.create_string_buffer(raw, len(raw))
    din = _BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    dout = _BLOB()
    crypt32 = ctypes.windll.crypt32
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(_BLOB), wintypes.LPCWSTR,
                   ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.c_void_p,
                   wintypes.DWORD, ctypes.POINTER(_BLOB)]
    fn.restype = wintypes.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN:无窗口环境也要能调
    if not fn(ctypes.byref(din), None, None, None, None, 0x1,
              ctypes.byref(dout)):
        return None
    try:
        out = ctypes.string_at(dout.pbData, dout.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dout.pbData)
    return base64.b64encode(out).decode("ascii") if encrypt \
        else out.decode("utf-8")


def _dpapi_protect(plain):
    if not plain:
        return None
    return _dpapi(plain, True)


def _dpapi_unprotect(b64):
    """解不开(换机器/换用户/密文损坏)返回 None。"""
    if not b64:
        return None
    return _dpapi(b64, False)


class AIBrain:
    def __init__(self, path=AI_CONFIG):
        self.path = path
        cfg = _load_json(path, {})
        self.cfg = {
            "api_key": "",
            "model": "gemini-flash-lite-latest",
            "greet_interval_min": 30,
        }
        if isinstance(cfg, dict):
            for k in self.cfg:
                if k in cfg and cfg[k] not in ("", None):
                    self.cfg[k] = cfg[k]
        self._enabled = bool(cfg.get("enabled", True)) if isinstance(cfg, dict) else True
        # 密钥落盘走 DPAPI 加密(api_key_enc);没有明文但有密文时解回来。
        # 解不开(换机器/换用户)就当没填,首次启动的引导会带用户重填。
        if not self.cfg.get("api_key"):
            plain = _dpapi_unprotect(cfg.get("api_key_enc")
                                     if isinstance(cfg, dict) else None)
            if plain:
                self.cfg["api_key"] = plain
        self._migrate_key_to_encrypted(cfg if isinstance(cfg, dict) else {})
        self.persona = load_persona()
        self.system_instruction = build_system_instruction(self.persona)
        self.examples = _load_examples()
        self.memory = MemoryStore()
        self._cooldown_until = 0.0
        self._lock = threading.Lock()
        self._client = None

    def _migrate_key_to_encrypted(self, cfg_on_disk):
        """一次性迁移:盘上还是明文密钥就换成 DPAPI 密文。任何一步失败都
        保持原样,绝不因为迁移把钥匙写丢。"""
        plain = self.cfg.get("api_key")
        if (os.name != "nt" or not plain
                or plain != cfg_on_disk.get("api_key")):
            return
        enc = _dpapi_protect(plain)
        if not enc:
            return
        new = dict(cfg_on_disk)
        new["api_key"] = ""
        new["api_key_enc"] = enc
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(new, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.remove(self.path + ".tmp")
            except OSError:
                pass

    def save(self):
        try:
            existing = _load_json(self.path, {})
            existing["greet_interval_min"] = self.cfg.get("greet_interval_min", 30)
            existing["model"] = self.cfg.get("model", "gemini-flash-lite-latest")
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def save_key(self, key):
        """写入 API 密钥并让客户端下次重建。save() 故意不碰 api_key,
        所以首次填写走这里。落盘走 DPAPI 加密;加密不可用(非 Windows/
        失败)时退回明文 —— 钥匙宁可明文也不能丢。"""
        key = (key or "").strip()
        self.cfg["api_key"] = key
        self._enabled = bool(key)
        self._client = None
        self._cooldown_until = 0.0
        try:
            existing = _load_json(self.path, {})
            if not isinstance(existing, dict):
                existing = {}
            if key:
                enc = _dpapi_protect(key)
                if enc:
                    existing["api_key"] = ""
                    existing["api_key_enc"] = enc
                else:
                    existing["api_key"] = key
                    existing.pop("api_key_enc", None)
            else:
                existing["api_key"] = ""
                existing.pop("api_key_enc", None)     # 清空就连密文一起清掉
            existing["enabled"] = bool(key)
            existing.setdefault("model", self.cfg.get("model"))
            existing.setdefault("greet_interval_min",
                                self.cfg.get("greet_interval_min", 30))
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            return True
        except Exception:
            return False

    @property
    def available(self):
        if not (_ensure_genai() and self._enabled):
            return False
        return bool(self.cfg.get("api_key") or os.environ.get("GEMINI_API_KEY")
                    or os.environ.get("GOOGLE_API_KEY"))

    def _resolve_key(self):
        return (self.cfg.get("api_key")
                or os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GOOGLE_API_KEY")
                or "")

    def prewarm(self):
        """后台预热:提前把 google.genai 加载好。开机 25 秒后由 pet.py 在
        后台线程调用,换来的是冷启动快一秒多、首次聊天不用现等。"""
        _ensure_genai()

    def _get_client(self):
        if self._client is None:
            key = self._resolve_key()
            if not key:
                return None
            try:
                # 必须显式设超时:SDK 默认单请求 10 分钟,挂住的请求会把
                # 后台线程一直占在锁里,ai_thinking 永远为 True,后续消息
                # 全被静默吞掉,只能重启
                self._client = genai.Client(
                    api_key=key,
                    http_options=types.HttpOptions(timeout=45000),
                )
            except Exception as e:
                print("genai.Client init failed:", e)
                self._client = None
        return self._client

    def _schema(self):
        return {
            "type": "object",
            "properties": {
                "say":     {"type": "string"},
                "emotion": {"type": "string", "enum": EMOTIONS},
                "action":  {"anyOf": [
                    {"type": "string", "enum": [a for a in ACTIONS if a is not None]},
                    {"type": "null"},
                ]},
                "intent": {"anyOf": [
                    {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": INTENT_KINDS},
                            "target": {"type": "string"},
                            "minutes": {"anyOf": [
                                {"type": "number"},
                                {"type": "null"},
                            ]},
                        },
                        "required": ["kind", "target"],
                    },
                    {"type": "null"},
                ]},
            },
            "required": ["say", "emotion", "action", "intent"],
        }

    def _build_messages(self, user_text, history, with_examples=True, hint=""):
        parts = []
        last_em = "happy"
        if history:
            for h in history[-12:]:
                role = "user" if h.get("role") == "user" else "model"
                content = str(h.get("content", ""))[:600]
                if content:
                    parts.append({"role": role, "parts": [{"text": content}]})
                if role == "model":
                    # 模型轮带着 emotion(pet.py 落盘时存进来了),用它挑
                    # 同情绪的示例;老记录没有就退回正则(更老的版本存过 JSON)
                    em = h.get("emotion")
                    if em in EMOTIONS:
                        last_em = em
                    elif content:
                        m = re.search(r'"emotion":\s*"(\w+)"', content)
                        if m:
                            last_em = m.group(1)
        if with_examples:
            exs = select_examples(user_text, self.examples, last_em, limit=4)
            for e in exs:
                a = e.get("assistant", {})
                parts.append({"role": "user",
                              "parts": [{"text": e.get("user", "")}]})
                parts.append({"role": "model",
                              "parts": [{"text": json.dumps(a, ensure_ascii=False)}]})
        if self.memory.facts:
            rel = self.memory.relevant(user_text, limit=5)
            if rel:
                mem_text = "[长期记忆(只有当与当前话题相关时使用)]\n" + "\n".join(f"- {f}" for f in rel)
                parts.append({"role": "user", "parts": [{"text": mem_text}]})
                parts.append({"role": "model",
                              "parts": [{"text": json.dumps(
                                  {"say": "(我记住啦~)", "emotion": "happy", "action": None},
                                  ensure_ascii=False)}]})
        msg = user_text if user_text else (hint or "主人,主动打个招呼吧。")
        parts.append({"role": "user", "parts": [{"text": msg}]})
        return parts

    def _generate(self, user_text, history, with_examples, hint, max_out=None):
        if not _ensure_genai():
            return None
        client = self._get_client()
        if client is None:
            return None
        msgs = self._build_messages(user_text, history,
                                    with_examples=with_examples, hint=hint)
        # 上下文长度根据"是否需要长回答"动态调整
        if max_out is None:
            max_out = 400 if with_examples else 200
        return client.models.generate_content(
            model=self.cfg.get("model", "gemini-flash-lite-latest"),
            contents=msgs,
            config=types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                response_mime_type="application/json",
                response_schema=self._schema(),
                temperature=0.92,
                max_output_tokens=max_out,
                # SDK 对"非 Chat 会话直调 generate_content"一律打一条 AFC
                # 警告(pet_error.log 每次启动一条)。本项目根本没用 tools,
                # 显式关掉,日志干净
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True),
            ),
        ).text or ""

    def _map_api_error(self, e):
        """把 SDK 异常统一映射成给用户看的失败回复。"""
        msg = str(e)
        if "401" in msg or "403" in msg or "API key" in msg.lower():
            return _fail_reply("auth")
        if "429" in msg or "quota" in msg.lower():
            m = re.search(r"retry.{0,10}?(\d+(?:\.\d+)?)\s*s", msg, re.I)
            self._cooldown(float(m.group(1)) + 2 if m else 60.0)
            return _fail_reply("quota" if m else "cooldown")
        return _fail_reply("generic")

    def _call(self, fn):
        """调一次模型调用,失败统一映射。网络级失败(超时/断网/瞬时 5xx)
        退避 1.2 秒重试一次;鉴权/配额错误重试也不会好,直接返回失败回复。
        成功返回 fn() 的原文,失败返回 _fail_reply 的 dict。"""
        for attempt in (0, 1):
            try:
                return fn()
            except Exception as e:
                msg = str(e)
                if ("401" in msg or "403" in msg or "API key" in msg.lower()
                        or "429" in msg or "quota" in msg.lower()):
                    return self._map_api_error(e)
                if attempt == 0:
                    time.sleep(1.2)
                    continue
                return self._map_api_error(e)

    def _cooldown(self, sec):
        self._cooldown_until = time.time() + sec

    def in_cooldown(self):
        return time.time() < self._cooldown_until

    def chat(self, user_text, history):
        if not self.available:
            return _fail_reply("no_key")
        if self.in_cooldown():
            return _fail_reply("cooldown")
        with self._lock:
            out = self._call(lambda: self._generate(
                user_text, history, with_examples=True, hint=""))
        if isinstance(out, dict):     # 已是失败回复
            return out
        obj = _coerce(out)
        if not obj:
            return _fail_reply("generic")
        try:
            self.memory.add_from_text(user_text)
        except Exception:
            pass
        return obj

    def summarize(self, text, max_out=700):
        """总结主人剪贴板/粘贴的长文本。不走聊天历史,token 上限放宽。"""
        if not self.available:
            return _fail_reply("no_key")
        if self.in_cooldown():
            return _fail_reply("cooldown")
        hint = ("主人让你总结他剪贴板里的内容。请提炼成几个要点,保留关键信息、"
                "数字和结论,用小乔的口吻说。内容如下:\n```\n"
                + text[:8000] + "\n```")
        with self._lock:
            out = self._call(lambda: self._generate(
                None, [], with_examples=False, hint=hint, max_out=max_out))
        if isinstance(out, dict):
            return out
        obj = _coerce(out)
        return obj or _fail_reply("generic")

    def translate(self, text, max_out=700):
        """翻译剪贴板内容:中文译英,其他语言译中。"""
        if not self.available:
            return _fail_reply("no_key")
        if self.in_cooldown():
            return _fail_reply("cooldown")
        hint = ("主人让你翻译他剪贴板里的内容。原文是中文就翻成英文,"
                "是其他语言就翻成中文。把译文放在 say 里,前面带一句小乔风格的"
                "短引子,后面不要解释。内容:\n```\n" + text[:8000] + "\n```")
        with self._lock:
            out = self._call(lambda: self._generate(
                None, [], with_examples=False, hint=hint, max_out=max_out))
        if isinstance(out, dict):
            return out
        obj = _coerce(out)
        return obj or _fail_reply("generic")

    def look(self, jpeg_bytes, question="", max_out=500):
        """看一眼主人的屏幕截图(jpeg 字节),回答问题或主动说说看到了什么。"""
        if not self.available:
            return _fail_reply("no_key")
        if self.in_cooldown():
            return _fail_reply("cooldown")
        q = (question or "").strip()
        if not q or q in ("看看", "screen"):
            q = ("简单说说主人屏幕上有什么;如果有报错弹窗、没回的消息或者"
                 "该休息的迹象,顺口提一句。用小乔的口吻。")
        else:
            q = ("主人看着屏幕问你:「" + q + "」。根据截图内容回答,"
                 "该给步骤就给步骤,用小乔的口吻。")
        with self._lock:
            def _do():
                client = self._get_client()
                if client is None:
                    return None
                return client.models.generate_content(
                    model=self.cfg.get("model", "gemini-flash-lite-latest"),
                    contents=[
                        types.Part.from_bytes(data=jpeg_bytes,
                                              mime_type="image/jpeg"),
                        {"text": q},
                    ],
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_instruction,
                        response_mime_type="application/json",
                        response_schema=self._schema(),
                        temperature=0.92,
                        max_output_tokens=max_out,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True),
                    ),
                ).text or ""
            out = self._call(_do)
        if isinstance(out, dict):
            return out
        obj = _coerce(out)
        return obj or _fail_reply("generic")

    def quick_line(self, hint=""):
        if not self.available or self.in_cooldown():
            return None
        with self._lock:
            out = self._call(lambda: self._generate(
                None, [], with_examples=False, hint=hint))
        return None if isinstance(out, dict) else _coerce(out)
