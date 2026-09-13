"""Fail closed on tracked private runtime files and recognizable secrets.

Print filenames/line numbers only, never matching values. This is a publishing
guard, not a replacement for reviewing the diff and asset permissions.
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = re.compile(r'^(ai_config|memories|chat_history|pet_settings|pet_reminders|pet_state|pet_cmd)(?:[._-].*)?\.json$',re.I)
PATTERNS = {
    'google-key': re.compile(r'AIza[0-9A-Za-z_-]{30,}'),
    'github-token': re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}'),
    'api-token': re.compile(r'sk-[A-Za-z0-9_-]{30,}'),
    'aws-key': re.compile(r'AKIA[0-9A-Z]{16}'),
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'local-user-path': re.compile(r'(?i)[A-Z]:[\\/]+Users[\\/]+(?!Public\b|Default\b|example\b|user\b)[^\\/\s"\']+'),
}


def main():
    result=subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True,check=True)
    files=[p for p in result.stdout.decode('utf-8').split('\0') if p]
    if not files:
        print('No tracked files to inspect. Stage the release snapshot first.')
        return 1
    findings=[]
    for name in files:
        path=ROOT/name
        if ((PRIVATE.match(path.name) and name!='assets/ai_config.example.json')
            or path.suffix.lower() in ('.log','.bak','.tmp','.dmp')
            or any(part in ('.venv','__pycache__','_tts_cache','_archive','release','dist','build') for part in path.parts)
            or path.name=='.env' or path.name=='.zcode_hook_state.json'):
            findings.append((name,0,'private-runtime-file'))
        if path.suffix.lower() not in ('.py','.md','.json','.txt','.yml','.yaml','.ps1','.bat'):
            continue
        text=path.read_text(encoding='utf-8-sig')
        for line_no,line in enumerate(text.splitlines(),1):
            for kind,pattern in PATTERNS.items():
                if pattern.search(line): findings.append((name,line_no,kind))
    for name,line,kind in findings: print(f'{name}:{line}: {kind}')
    print(f'Checked {len(files)} tracked files; {len(findings)} findings.')
    return int(bool(findings))


if __name__=='__main__': raise SystemExit(main())
