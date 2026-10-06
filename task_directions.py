"""Finite work directions from public labels; never return source text.

These categories add one useful level below an observed workflow phase. They
are conservative keyword summaries, not an inferred task plan or agent count.
"""
import json
import re


DIRECTIONS = (
    '工作流与进度', '窗口材质', '颜色与对比度', '比例与尺寸',
    '角色动作', '动态特效', '界面与布局', '数据接入',
    '测试与验证', '审核与检查', '资料调研', '交付与部署',
)

_MODULES = {
    'workflow_stages': '工作流与进度', 'task_directions': '工作流与进度',
    'moon_board': '工作流与进度', 'popup_material': '窗口材质',
    'flat_workspace': '界面与布局', 'apple_ui': '界面与布局',
    'ai_work_panel': '界面与布局', 'house_ai_ui': '界面与布局',
    'native_session_sync': '数据接入', 'ai_lights_core': '数据接入',
    'mac_session_sync': '数据接入', 'wsl_lights_hook': '数据接入',
    'xiaoqiao-lights-hook': '数据接入', 'zcode_notify': '数据接入',
    'ai_session_logs': '数据接入', 'hat_fx': '动态特效', 'fx': '动态特效',
}

_WORDS = (
    ('工作流与进度', r'工作流|任务进度|阶段概览|代理分工|workflow|task[\s_-]*progress'),
    ('窗口材质', r'窗口材质|弹层材质|半透明|毛玻璃|透明度|popup[\s_-]*material|opacity|translucent|translucency|frosted'),
    ('颜色与对比度', r'颜色|色彩|配色|对比度|饱和度|color|colour|contrast|saturation'),
    ('比例与尺寸', r'比例|尺寸|缩放|真实大小|真实尺寸|proportion|real[\s_-]*size|scale|sizing'),
    ('角色动作', r'闭眼|眨眼|睡眠|打盹|角色动作|唤醒|坐姿|blink|closed[\s_-]*eye|sleep|nap|pose'),
    ('动态特效', r'特效|粒子|星烟|星轨|星爆|萤火|hat[\s_-]*fx|particle|render|vfx'),
    ('界面与布局', r'界面|布局|交互|菜单|聊天窗|互动卡片|ui|layout|menu|chat[\s_-]*ui|interface|design'),
    ('数据接入', r'数据接入|会话数据|会话采集|同步数据|native[\s_-]*session|session[\s_-]*sync|session[\s_-]*metadata|collector|metadata|data[\s_-]*sync'),
    ('测试与验证', r'测试|验证|回归|复测|test|testing|verify|verification|validate|validation|regression'),
    ('审核与检查', r'审核|审查|检查|复审|review|audit|inspection'),
    ('资料调研', r'调研|研究资料|查资料|资料调研|research|investigation|explore'),
    ('交付与部署', r'交付|部署|发布|打包|推送|提交成果|deployment|deploy|release|publish|delivery|handoff'),
)


def _subject_pattern(pattern):
    # Chinese alternatives have no word-boundary requirement. Wrap each
    # ASCII alternative separately, preserving expressions inside it.
    bounded = [a if any('\u4e00' <= c <= '\u9fff' for c in a)
               else r'(?<![a-z0-9])(?:' + a + r')(?![a-z0-9])'
               for a in pattern.split('|')]
    return re.compile('|'.join(bounded))


_MATCHERS = tuple((category, _subject_pattern(pattern)) for category, pattern in _WORDS)


def task_direction(text):
    """Return a known broad direction or None; paths/prompts never escape.

    English terms require identifier boundaries so, for example, "testimony"
    is not evidence of testing. Underscores/hyphens in public task names count
    as separators. Exact Chinese category labels are accepted unchanged.
    """
    if not isinstance(text, str) or not text:
        return None
    lowered = text.lower()
    # A file with test_ in its name is still a file, not an executed test.
    # Prefer its known module subject; unknown file subjects stay unknown.
    file_action = re.fullmatch(r'(?:读|读取|阅读|改|修改|编辑|写)\s+(\S+)', lowered.strip())
    if file_action:
        lowered = re.split(r'[\\/]', file_action.group(1))[-1]
        lowered = re.sub(r'\.[a-z0-9]+$', '', lowered)
        lowered = re.sub(r'^test[_-]', '', lowered)
        if lowered in _MODULES:
            return _MODULES[lowered]
    for category in DIRECTIONS:
        if category in lowered:
            return category
    normalized = lowered.replace('_', ' ').replace('-', ' ')
    for category, pattern in _MATCHERS:
        if pattern.search(normalized):
            return category
    return None


def delegation_label(name, arguments):
    """Summarize explicit delegation only; never retain a prompt or agent ID.

    Shared by native log readers and ZCode/WSL hooks. Unknown tool names return
    None so callers preserve their existing action-label behavior.
    """
    name = str(name or '').split('.')[-1]
    if name in ('Task', 'Agent', 'spawn_agent'):
        prefix = '委派子智能体'
    elif name in ('followup_task', 'send_message'):
        prefix = '跟进子智能体'
    else:
        return None
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (ValueError, TypeError):
            arguments = {}
    inp = arguments if isinstance(arguments, dict) else {}
    # Prefer the public responsibility name to incidental background context
    # in its longer instruction. Only the finite category survives this call.
    direction = next((category for field in ('task_name', 'description')
                      if (category := task_direction(inp.get(field)))), None)
    if direction is None and isinstance(inp.get('message'), str):
        # Later paragraphs often contain excluded scope or background tasks.
        # Inspect a short public heading only, never the complete instruction.
        heading = re.split(r'[\n。！？!?]', inp['message'], maxsplit=1)[0][:160]
        if not re.search(r'不要|禁止|不许|do not|don\x27t|must not', heading, re.I):
            direction = task_direction(heading)
    if direction is None:
        # Capability types (e.g. Explore) must not override assigned work.
        direction = task_direction(inp.get('subagent_type'))
    return prefix + (' · ' + direction if direction else '')
