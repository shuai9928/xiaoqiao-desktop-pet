"""Display observed work phases, without exposing file names or commands.

This is a conservative summary of public action labels, not a task plan or
hidden reasoning. Unknown housekeeping stays in the current phase. The host
keeps its original log for detail clicks; a phase's index points to that log.
"""
import re
from moon_board import workflow
from task_directions import task_direction

RESEARCH = '阅读资料与调研'
IMPLEMENT = '编写与修改'
VERIFY = '测试与验证'
REVIEW = '审核与检查'
DELIVER = '整理与交付'
BUILD = '构建与部署'
GENERAL = '处理任务'
DELEGATE = '委派子智能体'
_PHASE_DIRECTIONS = {RESEARCH:'资料调研', VERIFY:'测试与验证',
                     REVIEW:'审核与检查', BUILD:'交付与部署', DELIVER:'交付与部署'}


def delegation_activity(label):
    text = str(label or '').strip()
    if re.match(r'^(跟进子智能体|followup_task\b|send_message\b)', text, re.I):
        return '跟进子智能体'
    if re.match(r'^(委派子智能体|子代理|子智能体|spawn_agent\b|task\b|agent\b)', text, re.I):
        return DELEGATE
    return None


def display_title(step):
    """Finite phase + finite direction; no raw task names, files or commands."""
    phase = step.get('activity') or step['title']
    direction = step.get('direction')
    return phase + (' · ' + direction if direction and direction != phase else '')


def detail_steps(flow):
    """Delegated responsibilities are drill-down rows, never progress dots.

    These labels describe observed assignments, not child execution status.
    A successful dispatch must not claim that the child's work is complete.
    """
    rows = []
    for step in flow['steps']:
        if step['title'] == DELEGATE and step.get('assignments'):
            for assignment in step['assignments']:
                row = dict(step, **assignment)
                row['status'] = 'error' if assignment['status'] == 'error' else 'recorded'
                rows.append(row)
        else:
            rows.append(step)
    return rows


def stage_title(label):
    """Return a finite display label, or None for an unknown/incidental action."""
    text = str(label or '').strip().lower()
    # Match verbs/tool identifiers, never arbitrary filename substrings:
    # reading test_pet.py is research, not running tests.
    if delegation_activity(label):
        return DELEGATE
    if text in (RESEARCH, IMPLEMENT, VERIFY, REVIEW, DELIVER, BUILD, GENERAL):
        return text
    if re.match(r'^(读|读取|阅读|搜索|搜网页|查阅|调研|整理素材|read\b|search\b|grep\b|glob\b|webfetch\b|websearch\b)', text):
        return RESEARCH
    if re.match(r'^(跑测试|运行测试|测试|验证|复测|unittest\b|pytest\b)', text):
        return VERIFY
    if re.match(r'^(审核|审查|复审|review\b|code.review\b)', text):
        return REVIEW
    if re.match(r'^(构建|部署|打包|发布|build\b)', text):
        return BUILD
    if re.match(r'^(整理文档|整理结果|整理交付|提交|推送|commit\b|push\b)', text):
        return DELIVER
    if re.match(r'^(改|修改|编辑|写|编写|实现|修复|调整布局|生成预览|edit\b|write\b|apply_patch\b)', text):
        return IMPLEMENT
    if re.match(r'^命令 (git (commit|push)|gh (pr|release))\b', text):
        return DELIVER
    if re.match(r'^命令 (npm|pnpm|yarn|bun|pip|pip3|uv) (install|add|sync)\b', text):
        return BUILD
    if re.match(r'^命令 (git (diff|show|log)|rg|grep|get-content|cat)\b', text):
        return RESEARCH
    if re.match(r'^调用工具 .*?(search|fetch|browse|read|find|view)', text):
        return RESEARCH
    if re.match(r'^调用工具 .*?(review|check)', text):
        return REVIEW
    if re.match(r'^调用工具 .*?(test|verify|validate)', text):
        return VERIFY
    if re.match(r'^调用工具 .*?(edit|write|patch|imagegen)', text):
        return IMPLEMENT
    return None


def stages(ui):
    raw = workflow(ui)
    groups = []
    for step in raw['steps']:
        title = stage_title(step['title'])
        direction = task_direction(step['title'])
        if direction == _PHASE_DIRECTIONS.get(title):
            direction = None  # a generic phase is not a new task subject
        activity = delegation_activity(step['title'])
        # Reopening/searching a file while implementing or checking work is
        # part of that phase, not a new round of research. Explicit research
        # activity can still start a new phase.
        if (groups and groups[-1]['title'] not in (GENERAL, RESEARCH)
                and title == RESEARCH
                and not re.match(r'^(调研|研究|搜网页|搜索资料|阅读资料与调研|websearch\b)', step['title'].lower())):
            title = None
            direction = None
        # Unknown calls/waits/turn markers do not add dots or replace a
        # meaningful current phase. Their errors still belong to that phase.
        if not groups or (title and title != groups[-1]['title']):
            previous_direction = (groups[-1]['direction'] if groups
                                  and title != DELEGATE and groups[-1]['title'] != DELEGATE else None)
            groups.append(dict(title=title or GENERAL, index=step['index'],
                               status='recorded', result='', count=0, _statuses=[],
                               direction=previous_direction, activity=None, assignments=[]))
        group = groups[-1]
        if title and group['title'] == GENERAL:
            group['title'] = title
        group['index'] = step['index']
        group['count'] += step.get('count', 1)
        group['_statuses'].append(step['status'])
        # Incidental reads/waits cannot replace the actual work direction.
        if title and direction:
            group['direction'] = direction
        if activity:
            group['activity'] = activity
            # A new assignment without scope is not evidence that it has the
            # previous child's responsibility. Wait/read events still retain it.
            group['direction'] = direction
            assignment = dict(direction=direction, activity=activity,
                              index=step['index'], status=step['status'])
            previous = next((a for a in group['assignments']
                             if a['direction'] == direction), None)
            if previous:
                group['assignments'].remove(previous)
            group['assignments'].append(assignment)
    # Drop the initial receive-task/housekeeping placeholder once there is
    # actual phase evidence. There is no assumed research stage for every job.
    if len(groups) > 1 and groups[0]['title'] == GENERAL:
        groups.pop(0)
    for group in groups:
        statuses = group.pop('_statuses')
        group['status'] = ('error' if 'error' in statuses else
                           'done' if all(s == 'done' for s in statuses) else 'recorded')
        group['result'] = '该阶段出现错误' if group['status'] == 'error' else ''
    if groups and not raw['stale']:
        if raw['state'] in ('running', 'waiting', 'error'):
            groups[-1]['status'] = raw['state']
        elif raw['state'] == 'done' and groups[-1]['status'] != 'error':
            groups[-1]['status'] = 'done'
    return dict(raw, steps=groups, completed=sum(g['status'] == 'done' for g in groups))


def state_label(state, stale=False):
    if stale:
        return '久未更新'
    return {'running': '进行中', 'waiting': '等你确认', 'error': '遇到问题',
            'done': '已结束', 'idle': '空闲'}.get(state, '状态未知')
