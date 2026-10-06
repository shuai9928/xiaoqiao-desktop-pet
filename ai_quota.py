"""Read-only quota snapshots, separate from AI session/workflow selection.

Snapshot ``t`` remains UTC milliseconds; cycle ``reset`` and view ``age`` are
seconds.  No network, session scans or model calls occur here.  Unknown values
are never replaced with zero, and an expired window retains its LAST sample.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
import time


STALE_AFTER = 3600
CODEX_SOURCE = "Codex 官方用量接口"
ACCOUNTS = (("codex", "Codex"), ("claude", "Claude"), ("zcode", "ZCode"))
PERIODS = (("5 小时", 300), ("7 天", 10080))
NOTES = {"codex": "用量快照 · 自动同步尚未接入",
         "claude": "本机用量样本", "zcode": "额度尚未接入"}
LABELS = {"codex": "Codex · 账户额度", "claude": "Claude · 账户共享额度",
          "zcode": "ZCode · 额度"}
SOURCE_PROVIDER = {"codex": "codex", "mac": "codex", "mac-codex": "codex", "maccodex": "codex",
                   "wslcodex": "codex", "wsl-codex": "codex",
                   "claude": "claude", "macclaude": "claude",
                   "mac-claude": "claude", "zcode": "zcode"}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def _timestamp(value, milliseconds=False):
    """Keep the original units, but accept only platform-formatable dates."""
    value = _number(value)
    if value is None or value <= 0:
        return None
    seconds = value/1000 if milliseconds else value
    try:
        datetime.fromtimestamp(seconds, timezone.utc)
        local = time.localtime(seconds)
        if not 1 <= local.tm_year <= 9999:
            return None
    except (OverflowError, OSError, ValueError):
        return None
    return value


def _used(value):
    value = _number(value)
    return value if value is not None and 0 <= value <= 100 else None


def _reset(value, timestamp):
    value = _timestamp(value)
    return value if timestamp is not None and value is not None and value > timestamp/1000 else None


def _codex_snapshot(raw):
    """Whitelist fields and canonicalize cycle names; duplicate cycles unknown."""
    if not isinstance(raw, dict) or raw.get("provider") != "codex":
        return None
    stamp = _timestamp(raw.get("t"), milliseconds=True)
    rows = raw.get("cycles") if isinstance(raw.get("cycles"), list) else []
    cycles = []
    for label, minutes in PERIODS:
        matches = [row for row in rows if isinstance(row, dict)
                   and _number(row.get("minutes")) == minutes]
        row = matches[0] if len(matches) == 1 else {}
        cycles.append({"label": label, "minutes": minutes,
                       "used": _used(row.get("used")),
                       "reset": _reset(row.get("reset"), stamp)})
    return {"provider": "codex", "t": stamp, "cycles": cycles,
            "source": CODEX_SOURCE}


def read_codex_quota(path):
    """Return a sanitized snapshot or None for an unreadable/invalid file.

    The host can distinguish a missing file from read failure and set the
    trusted ``ui.codex_quota_error`` flag while retaining its previous sample.
    File-supplied source/status/account/credential fields never enter the UI.
    """
    try:
        path = Path(path)
        if path.stat().st_size > 65536:
            return None
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError, RecursionError):
        return None
    return _codex_snapshot(raw)


def quota_accounts(ui):
    """Available quota selectors, NOT fabricated sessions or connected accounts."""
    return list(ACCOUNTS)


def _select_provider(ui, provider):
    for requested in (provider, ui.get("quota_provider")):
        if isinstance(requested, str) and requested in LABELS:
            return requested
    selected = ui.get("sel_key")
    if not selected and isinstance(ui.get("sel_session"), dict):
        selected = ui["sel_session"].get("agent")
    if isinstance(selected, str) and selected in SOURCE_PROVIDER:
        return SOURCE_PROVIDER[selected]
    if _codex_snapshot(ui.get("codex_quota")) is not None:
        return "codex"
    if isinstance(ui.get("quota"), dict):
        return "claude"
    return "codex"


def quota_view(ui, provider=None):
    """Build honest UI data: current/partial/unknown/stale/read_error.

    ``ui.now`` is UTC seconds, optional for deterministic rendering/tests.
    ``stale`` marks unusable freshness; status stays unknown when the sample
    time is missing/future.  Claude's optional age cannot make that time fresh.
    Reset passage never implies that the account has recovered to full quota.
    """
    ui = ui if isinstance(ui, dict) else {}
    provider = _select_provider(ui, provider)
    now = _timestamp(ui.get("now"))
    now = time.time() if now is None else now
    error = bool(ui.get(provider+"_quota_error"))
    data, stamp = None, None
    rows = []
    if provider == "codex":
        data = _codex_snapshot(ui.get("codex_quota"))
        if data is not None:
            stamp = data["t"]
            rows = [(row["used"], row["reset"], False) for row in data["cycles"]]
    elif provider == "claude":
        q = ui.get("quota")
        if isinstance(q, dict):
            data = q
            stamp = _timestamp(q.get("t"), milliseconds=True)
            reset = _reset(q.get("reset_est"), stamp)
            rows = [(_used(q.get("fh")), reset, reset is not None),
                    (_used(q.get("sd")), None, False)]
    known_time = stamp is not None and stamp/1000 <= now
    age = now-stamp/1000 if known_time else None
    if provider == "claude" and known_time:
        supplied_age = _number(ui.get("quota_age"))
        if supplied_age is not None and supplied_age >= 0:
            age = max(age, supplied_age)
    old = bool(data is not None and (not known_time or age > STALE_AFTER))
    cycles = []
    for index, (label, _minutes) in enumerate(PERIODS):
        used, reset, estimated = rows[index] if rows else (None, None, False)
        stale = error or old or (reset is not None and now >= reset)
        cycles.append({"label": label, "used": used,
                       "remaining": None if used is None else 100-used,
                       "reset": reset, "estimated": estimated, "stale": stale})
    stale = any(row["stale"] for row in cycles)
    count = sum(row["used"] is not None for row in cycles)
    if error:
        status = "read_error"
    elif not known_time or not count:
        status = "unknown"
    elif stale:
        status = "stale"
    else:
        status = "current" if count == len(PERIODS) else "partial"
    return {"provider": provider, "label": LABELS[provider], "cycles": cycles,
            "age": age, "t": stamp, "stale": stale, "status": status,
            "note": NOTES[provider]}
