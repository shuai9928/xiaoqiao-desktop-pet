"""Read native Codex/Claude public session events for the desktop lights.

No credentials, transcript text, tool output, reasoning or account fields are
copied. Runs on a daemon thread so log discovery never blocks rendering. Cloud
Claude sessions have no local transcript and are deliberately not synthesized.
"""
import datetime
import json
import os
import re
import threading
import time
from pathlib import Path

from ai_lights_core import action_label, safe_name, write_json
from task_directions import delegation_label

TAIL_BYTES = 4 * 1024 * 1024
MAX_LINE = 2 * 1024 * 1024
STALE_AFTER = 900


def codex_label(name, arguments):
    # Codex Desktop wraps tools in a public JavaScript orchestration call.
    # Extract only a known tool name and, if JSON-quoted, the command literal.
    # Never evaluate JavaScript or retain the wrapper/body itself.
    if name == 'exec' and isinstance(arguments, str):
        tool = re.search(r'tools\.([A-Za-z0-9_]+)\s*\(', arguments)
        if tool:
            name = tool.group(1)
            if name in ('spawn_agent', 'followup_task', 'send_message'):
                fields = {}
                for field in ('task_name', 'subagent_type', 'description', 'message'):
                    match = re.search(r'\b' + field + r'\s*:\s*("(?:[^"\\]|\\.)*")', arguments)
                    if match:
                        try:
                            fields[field] = json.loads(match.group(1))
                        except ValueError:
                            pass
                return delegation_label(name, fields)
            if name == 'apply_patch':
                # Decode only a quoted tool argument, never execute the JS.
                # Keep just the first public file header for the existing
                # basename-only action label; no patch contents are cached.
                literal = re.search(r'tools\.apply_patch\s*\(\s*("(?:[^"\\]|\\.)*")', arguments)
                if literal:
                    try:
                        patch = json.loads(literal.group(1))
                        header = re.search(r'\*\*\* (?:Update|Add|Delete) File:\s*([^\r\n]+)', patch)
                        if header:
                            return action_label(name, {'file_path': header.group(1).strip()})
                    except ValueError:
                        pass
            if name == 'exec_command':
                command = re.search(r'\bcmd\s*:\s*("(?:[^"\\]|\\.)*")', arguments)
                if command:
                    try:
                        return action_label(name, {'cmd': json.loads(command.group(1))})
                    except ValueError:
                        pass
            return action_label(name, {})
        return '执行工具'
    delegated = delegation_label(name, arguments)
    if delegated:
        return delegated
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (ValueError, TypeError):
            arguments = {'input': arguments} if name == 'apply_patch' else {}
    return action_label(name, arguments)


def stamp(value):
    try:
        return datetime.datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0


class Transcript:
    def __init__(self, path, agent):
        self.path, self.agent = Path(path), agent
        self.offset = None
        self.pending = b''
        self.updated = self.since = 0
        self.state = 'idle'
        self.actions = []
        self.sid = self.path.stem[-36:]
        self.calls = {}

    def action(self, label, when, result='', error=False):
        if not label:
            return
        entry = {'t': when, 'a': label, 'r': result, 'err': int(error)}
        if self.actions and self.actions[0].get('a') == label:
            self.actions[0] = entry
        else:
            self.actions.insert(0, entry)
        del self.actions[48:]

    def state_at(self, state, when):
        if state != self.state:
            self.since = when
        self.state = state
        self.updated = max(self.updated, when)

    def consume(self, row):
        if not isinstance(row, dict):
            return
        kind = row.get('type')
        when = stamp(row.get('timestamp'))
        p = row.get('payload') or {}
        if not isinstance(p, dict):
            return
        if kind == 'session_meta':
            self.sid = safe_name(p.get('id') or self.sid)
            return
        if kind == 'event_msg' and when:
            typ = p.get('type')
            if typ in ('task_started', 'user_message'):
                self.state_at('running', when)
                if typ == 'task_started':
                    self.actions.insert(0, {'turn': 1, 't': when})
                self.action('收到新任务', when)
            elif typ in ('task_complete', 'task_completed'):
                self.state_at('done', when)
                self.action('本轮已结束', when, '已结束')
            elif typ in ('turn_aborted', 'task_aborted'):
                self.state_at('idle', when)
                self.action('本轮已中断', when)
            elif typ in ('item_started', 'item_completed'):
                item = p.get('item') or {}
                if not isinstance(item, dict):
                    return
                it = item.get('type')
                if it == 'CommandExecution':
                    command = item.get('command')
                    if isinstance(command, list):
                        command = command[-1] if command else ''
                    label = action_label('exec_command', {'cmd': command})
                    code = item.get('exit_code')
                    failed = isinstance(code, int) and code != 0
                    self.state_at('running', when)
                    self.action(label, when, ('退出 ' + str(code)) if isinstance(code, int) else '', failed)
                elif it == 'AgentMessage' and item.get('phase') == 'final':
                    self.state_at('done', when)
                    self.action('本轮已结束', when, '已结束')
            return
        if kind == 'response_item' and when:
            typ = p.get('type')
            if typ in ('function_call', 'custom_tool_call'):
                name = str(p.get('name') or '').split('.')[-1]
                arguments = p.get('arguments') or p.get('input') or {}
                label = codex_label(name, arguments)
                self.calls[p.get('call_id')] = label
                self.state_at('waiting' if name.startswith('request_user_input') else 'running', when)
                self.action(label, when)
            elif typ == 'message' and p.get('role') == 'assistant' and p.get('phase') == 'final':
                self.state_at('done', when)
                self.action('本轮已结束', when, '已结束')
            return
        if self.agent == 'native-claude' and when:
            message = row.get('message') or {}
            if not isinstance(message, dict):
                return
            content = message.get('content')
            blocks = content if isinstance(content, list) else []
            if kind == 'user' and not any(isinstance(x, dict) and x.get('type') == 'tool_result' for x in blocks):
                self.state_at('running', when)
                self.actions.insert(0, {'turn': 1, 't': when})
                self.action('收到新任务', when)
            elif kind == 'assistant':
                for block in blocks:
                    if not isinstance(block, dict) or block.get('type') != 'tool_use':
                        continue
                    name = block.get('name') or ''
                    label = (delegation_label(name, block.get('input'))
                             or action_label(name, block.get('input')))
                    self.calls[block.get('id')] = label
                    self.action(label, when)
                    self.state_at('waiting' if name == 'AskUserQuestion' else 'running', when)
                if message.get('stop_reason') == 'end_turn':
                    self.state_at('done', when)
                    self.action('本轮已结束', when, '已结束')
            elif kind == 'user':
                for block in blocks:
                    if isinstance(block, dict) and block.get('type') == 'tool_result':
                        label = self.calls.get(block.get('tool_use_id'))
                        self.action(label, when, '工具报错' if block.get('is_error') else '已返回', bool(block.get('is_error')))
                        self.state_at('running', when)
            elif kind == 'system' and row.get('subtype') == 'stop_hook_summary':
                self.state_at('done', when)
                self.action('本轮已结束', when, '已结束')

    def poll(self):
        size = self.path.stat().st_size
        if self.offset is None or size < self.offset:
            self.offset = max(0, size - TAIL_BYTES)
            self.pending = b''
            if self.offset:
                with self.path.open('rb') as f:
                    f.seek(self.offset)
                    f.readline()  # discard the partial first record
                    self.offset = f.tell()
        with self.path.open('rb') as f:
            f.seek(self.offset)
            chunk = f.read(TAIL_BYTES)
            self.offset = f.tell()
        lines = (self.pending + chunk).split(b'\n')
        self.pending = lines.pop()
        if len(self.pending) > MAX_LINE:
            self.pending = b''
        for line in lines:
            if len(line) > MAX_LINE:
                continue
            try:
                self.consume(json.loads(line))
            except (ValueError, TypeError, OverflowError):
                continue

    def snapshot(self, now):
        stale = self.state in ('running', 'waiting', 'error') and now - self.updated > STALE_AFTER
        return {'id': safe_name(self.agent + '-' + self.sid), 'agent': self.agent,
                'source': 'windows-native', 'state': 'idle' if stale else self.state,
                'title': 'Windows 原生会话', 'updated': self.updated,
                'since': self.since, 'stale': stale, 'actions': self.actions[:48]}


class NativeSessions:
    def __init__(self, home, dest):
        self.home, self.dest = Path(home), Path(dest)
        self.readers, self.saved = {}, {}
        self.last_discovery = 0

    def tick(self, now=None):
        now = time.time() if now is None else now
        if now - self.last_discovery >= 10:
            self.last_discovery = now
            for folder, pattern, agent in (
                    (self.home / '.codex' / 'sessions', '*/*/*/*.jsonl', 'native-codex'),
                    (self.home / '.claude' / 'projects', '*/*.jsonl', 'native-claude')):
                candidates = []
                for path in folder.glob(pattern):
                    try:
                        modified = path.stat().st_mtime
                        if now - modified < 7 * 86400:
                            candidates.append((modified, path))
                    except OSError:
                        pass
                for _, path in sorted(candidates, reverse=True)[:24]:
                    self.readers.setdefault(path, Transcript(path, agent))
        self.dest.mkdir(parents=True, exist_ok=True)
        for reader in list(self.readers.values()):
            try:
                reader.poll()
                # Native Claude publishes an explicit idle/running state in
                # ~/.claude/sessions. It can correct a resumed old transcript.
                if reader.agent == 'native-claude':
                    for path in (self.home / '.claude' / 'sessions').glob('*.json'):
                        try:
                            metadata = json.loads(path.read_text(encoding='utf-8'))
                        except (OSError, ValueError):
                            continue
                        if not isinstance(metadata, dict):
                            continue
                        if metadata.get('sessionId') != reader.sid:
                            continue
                        when = float(metadata.get('statusUpdatedAt') or 0) / 1000
                        status = metadata.get('status')
                        if when >= reader.updated and status in ('idle', 'running', 'waiting'):
                            reader.state_at(status, when)
                            if not reader.actions:
                                reader.action('等待新任务' if status == 'idle' else '正在处理任务', when)
                data = reader.snapshot(now)
                if not data['actions']:
                    continue
                serialized = json.dumps(data, ensure_ascii=False)
                if self.saved.get(data['id']) != serialized:
                    write_json(str(self.dest / (data['id'] + '.json')), data)
                    self.saved[data['id']] = serialized
                if len(reader.calls) > 128:
                    reader.calls = dict(list(reader.calls.items())[-64:])
            except (OSError, ValueError, TypeError):
                continue


def start(dest):
    """One reader per pet process; its lifecycle ends with the desktop pet."""
    if os.name != 'nt':
        return None
    bridge = NativeSessions(Path.home(), dest)
    def run():
        while True:
            try:
                bridge.tick()
            except Exception:
                pass  # missing/corrupt session logs must never stop the pet
            time.sleep(2)
    thread = threading.Thread(target=run, name='native-session-sync', daemon=True)
    thread.start()
    return thread
