"""Check local Markdown links, anchors and media without network access."""
from pathlib import Path
from urllib.parse import unquote, urlsplit
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]


def anchors(text):
    found = set(re.findall(r'\bid=["\']([^"\']+)["\']', text))
    seen = {}
    for title in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', text, re.M):
        title = re.sub(r'<[^>]+>|[*`]', '', title).strip().lower()
        slug = ''.join(c for c in title if c in '-_ ' or unicodedata.category(c)[0] in 'LN').replace(' ', '-')
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        found.add(slug + (f'-{count}' if count else ''))
    return found


def main():
    files = sorted(ROOT.glob('*.md')) + sorted((ROOT/'docs').rglob('*.md')) + sorted((ROOT/'tools').glob('*.md'))
    failures, checked = [], 0
    for file in files:
        text = file.read_text(encoding='utf-8-sig')
        # Code examples can contain placeholders that are not navigation links.
        visible = re.sub(r'```.*?```', '', text, flags=re.S)
        refs = re.findall(r'!?\[[^\]\n]*\]\(([^\s)]+)(?:\s+"[^"]*")?\)', visible)
        refs += re.findall(r'\b(?:src|href)=["\']([^"\']+)["\']', visible)
        for ref in refs:
            url = urlsplit(ref.strip('<>'))
            if url.scheme or url.netloc:
                continue
            checked += 1
            target = (file.parent / unquote(url.path)).resolve() if url.path else file
            if not target.is_relative_to(ROOT):
                failures.append((file, ref, 'outside repository'))
            elif not target.exists():
                failures.append((file, ref, 'missing file'))
            elif target.is_file() and target.stat().st_size == 0:
                failures.append((file, ref, 'empty file'))
            elif url.fragment and target.suffix == '.md':
                fragment = unquote(url.fragment)
                if fragment not in anchors(target.read_text(encoding='utf-8-sig')):
                    failures.append((file, ref, 'missing anchor'))
    for file, ref, reason in failures:
        print(f'{file.relative_to(ROOT)}: {reason}: {ref}')
    print(f'Checked {len(files)} documents and {checked} local references; {len(failures)} findings.')
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
