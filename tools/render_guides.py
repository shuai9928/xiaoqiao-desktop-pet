"""Generate editable SVG instruction diagrams; these are not UI screenshots."""
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / 'docs' / 'media'


def diagram(name, title, subtitle, cards, footnote):
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="880" viewBox="0 0 1200 880" role="img" aria-labelledby="title desc">',
             f'<title id="title">{escape(title)}</title><desc id="desc">{escape(subtitle)}</desc>',
             '<rect width="1200" height="880" rx="28" fill="#12101d"/>',
             '<g font-family="Microsoft YaHei, PingFang SC, sans-serif">']
    def text(x, y, value, size=19, color='#c6bfd5', weight='normal'):
        parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}">{escape(value)}</text>')
    text(44, 50, 'XIAOQIAO / HOW IT WORKS', 16, '#e5d2a0')
    text(44, 106, title, 34, '#f5f1ff', 'bold')
    text(44, 146, subtitle, 18)
    for i, (heading, lines) in enumerate(cards):
        x, y = 44 + (i % 3) * 376, 190 + (i // 3) * 294
        parts.append(f'<rect x="{x}" y="{y}" width="360" height="270" rx="18" fill="#211b32" stroke="#514361"/>')
        text(x+22, y+40, f'0{i+1}', 18, '#e5d2a0')
        text(x+65, y+40, heading, 23, '#f5f1ff', 'bold')
        parts.append(f'<path d="M{x+22} {y+58}h316" stroke="#514361"/>')
        for j, line in enumerate(lines):
            text(x+22, y+91+j*30, line)
    text(44, 826, footnote, 17, '#e5d2a0')
    text(44, 858, '操作路径示意图 · 根据源码整理，非程序窗口截图', 14, '#aaa0bc')
    parts.append('</g></svg>')
    (OUT / f'{name}.svg').write_text('\n'.join(parts), encoding='utf-8')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    diagram('menu-map', '想做什么，从这里找到她。', '右键打开互动卡片；「更多」展开完整菜单。', [
        ('常用六按钮', ['聊天 / 喂糖 / 时间魔法', '跳舞 / 玩球 / 睡觉或叫醒', 'Tab 切换，Enter 执行', '顶部看陪伴天数、好感和星光', '提示区看今日小结']),
        ('更多 → 一起玩', ['撒星星、玩球、石头剪刀布', '转圈、跳舞、空翻、变身', '打滚、挥手、伸懒腰、发呆', '走到命令发出时的鼠标位置', '报时、时停、时间回溯']),
        ('更多 → 小本事', ['提醒 / 找文件 / 查天气', '剪贴板总结、翻译 / 看屏幕', '番茄钟：25 / 50 分钟', '喝水：关 / 30 / 45 / 60 / 90', 'AI 主动搭话：条件满足时显示']),
        ('更多 → 设置', ['声音、朗读、开机自启', '偷看窗口 / 笔记本电量提醒', '大小：80% 至 175% 共五档', '置顶 / 鼠标穿透 / AI 密钥', '聊天记录 / 纪念日 / 生日']),
        ('聊天里的动作', ['「冥想」「飘起来」「浮空」', '「猜数字」「今日运势」', '「摸摸头」「挥挥手」', '「5分钟后提醒我喝水」', '无需 AI 的指令会本地执行']),
        ('系统托盘', ['显示 / 隐藏', '和小乔聊天 / 时间魔法', '随机表情', '语音开关 / 退出', '左键穿透后仍可右键打开菜单'])
    ], '冥想、猜数字和今日运势可从聊天触发；并非每个玩法都有独立菜单项。')
    diagram('focus-flow', '陪你专注，也记得让你休息。', '更多 → 小本事 → 番茄钟；今日专注分钟在完成专注段时结算。', [
        ('选一段时间', ['选择 25 或 50 分钟', '也可在聊天说「来个番茄钟」', '开始后进入专注陪伴', '计时状态保存在本机', '停止番茄钟可提前结束']),
        ('安静陪着你', ['暂停闲聊、走动和主动搭话', '保留呼吸、眨眼、视线跟随', '每 4–7 分钟少量无声星光', '专注过半时轻轻蹭一下', '主动摸她仍然会回应']),
        ('完成这一段', ['到点提醒并累计完成次数', '今日专注分钟加上本段时长', '增加好感，可能解锁里程碑', '空闲时接上一次伸懒腰', '进入 5 分钟休息']),
        ('休息一下', ['恢复平常的互动与日常动作', '喝水，站起来走一走', '5 分钟到点再次提示', '本轮结束后由你决定下一轮', '不会自动无限循环专注']),
        ('今日小结', ['摸头 / 喂糖 / 接星', '完成的专注分钟 / 聊天 / 挠痒', '卡片依次显示前三个非零项', '晚上 21 点后空闲时小结一次', '按本机日期跨天重新计数']),
        ('提醒各自独立', ['喝水提醒是另一条周期计时', '一次性提醒到点照常通知', '电量事件在专注与睡眠时静默', '静默期间的电量事件不补播', '提醒不需要 AI 密钥'])
    ], '图示为功能流程；系统关机或进程未运行时，不会凭空弹出通知。')
    diagram('assistant-map', '一句话，到底由谁来完成？', '本地动作、本机助手、联网查询与 AI 对话，各有明确的工作范围。', [
        ('本地角色动作', ['摸头、喂糖、跳舞、冥想', '玩球、猜数字、今日运势', '先匹配程序支持的指令', '不需要密钥，不调用模型', '忙碌时某些动作暂不可用']),
        ('本机实用助手', ['定时提醒、番茄钟', '按名称查找文件', '解析打开或关闭应用的指令', '操作发生在你自己的电脑上', '不等于理解任何自然语言']),
        ('天气与联网', ['从菜单询问当前天气', '按提示提供城市', '需要访问天气服务', '独立于 AI 对话密钥', '网络失败时按提示重试']),
        ('可选 AI 对话', ['安装 requirements-ai.txt', '设置 → 设置 AI 密钥', '使用自己的 Gemini 配置', '对话可能带相关长期记忆', '费用和服务可用性取决于提供方']),
        ('剪贴板与屏幕', ['从对应菜单或指令发起', '总结 / 翻译剪贴板内容', '请求 AI 解释当前屏幕', '相关内容可能发送到模型服务', '使用前确认内容适合发送']),
        ('数据留在哪里', ['设置、提醒、聊天保存在本机', '记忆与 AI 配置位于 assets', '真实数据不进入公开仓库', 'debug-state 可能记录聊天文字', '公开版只带示例 AI 配置'])
    ], '示意图不构成云端隐私承诺；实际发送内容及服务规则以所用 AI 配置为准。')
    print('Generated menu-map, focus-flow, assistant-map SVGs.')


if __name__ == '__main__':
    main()
