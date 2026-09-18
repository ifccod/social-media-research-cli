from __future__ import annotations

import csv
import json
import math
import re
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TextIO

from .client import _SCREEN_NAME_RE, _USER_ID_RE
from .errors import TwitterInputError, TwitterResponseError


DEFAULT_FOLLOW_STATE_NAME = "twitter-follow-state.jsonl"
WINDOW_SECONDS = 900
WINDOW_LIMIT = 50
DAILY_SECONDS = 86400
DAILY_LIMIT = 400
DEFAULT_INTERVAL = 18.0
_STOP_CODES = frozenset(
    {"verification_required", "not_logged_in", "tab_unavailable"}
)
_DONE_TYPES = frozenset({"followed", "skipped", "already_following"})
_PROFILE_URL_RE = re.compile(
    r"(?i)^(?:https?://)?(?:www\.)?(?:x\.com|twitter\.com)/@?"
    r"([A-Za-z0-9_]{1,15})(?:[/?#]|$)"
)


def run_follow_batch(
    client: Any,
    *,
    file_path: Path | None = None,
    csv_path: Path | None = None,
    state_path: Path,
    cooldown: float = 1800,
    interval: float = 0,
    window_seconds: float = WINDOW_SECONDS,
    window_limit: int = WINDOW_LIMIT,
    daily_limit: int = DAILY_LIMIT,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
    log: TextIO | None = None,
) -> dict[str, Any]:
    """按名单批量关注；默认 15 分钟 50 次、24 小时 400 次，满额停止。"""

    err = log if log is not None else sys.stderr

    if (file_path is None) == (csv_path is None):
        raise TwitterInputError("follow-batch requires exactly one of --file or --csv")
    _require_non_negative("cooldown", cooldown)
    _require_non_negative("interval", interval)
    _require_non_negative("window_seconds", window_seconds)
    if (
        isinstance(window_limit, bool)
        or not isinstance(window_limit, int)
        or window_limit < 0
    ):
        raise TwitterInputError("window_limit must be a non-negative integer")
    if (
        isinstance(daily_limit, bool)
        or not isinstance(daily_limit, int)
        or daily_limit < 0
    ):
        raise TwitterInputError("daily_limit must be a non-negative integer")
    targets = (
        _load_file(file_path) if file_path is not None else _load_csv(csv_path)
    )
    done = _load_done(state_path)
    quota_times = _load_quota_times(state_path)
    attempted = 0
    followed = 0
    skipped = 0
    already_following = 0
    cooldown_count = 0
    stopped_reason: str | None = None
    pace_before = False
    print(
        f"[关注] 间隔 {interval:g} 秒，15 分钟 {window_limit} 次，"
        f"24 小时 {daily_limit} 次，限流冷却 {cooldown:g} 秒",
        file=err,
        flush=True,
    )

    for kind, value, skip_reason in targets:
        keys = _identity_keys(kind, value)
        if keys & done:
            continue
        if skip_reason:
            skipped += 1
            _record(state_path, done, "skipped", kind, value, reason=skip_reason)
            continue
        if kind == "invalid":
            skipped += 1
            _record(state_path, done, "skipped", "", value, reason="invalid")
            continue
        kwargs = {"user_id": value} if kind == "user_id" else {"screen_name": value}
        while True:
            quota, wait = _quota_wait(
                quota_times,
                now=now(),
                window_seconds=window_seconds,
                window_limit=window_limit,
                daily_limit=daily_limit,
            )
            if quota == "daily_limit":
                print(
                    f"[配额] 24 小时内已关注 {daily_limit} 次，停止",
                    file=err,
                    flush=True,
                )
                stopped_reason = "daily_limit"
                break
            if quota == "window" and wait > 0:
                print(
                    f"[配额] 15 分钟内已关注 {window_limit} 次，等待 {wait:g} 秒",
                    file=err,
                    flush=True,
                )
                sleep(wait)
                continue
            if pace_before and interval > 0:
                sleep(interval)
            pace_before = False
            attempted += 1
            try:
                payload = client.follow(**kwargs)
            except TwitterInputError:
                skipped += 1
                _record(state_path, done, "skipped", kind, value, reason="invalid")
                break
            except TwitterResponseError as exc:
                code = exc.code or "request_failed"
                if code == "rate_limited":
                    quota_times.append(now())
                    print(
                        f"[限流] {kind}={value} rate_limited，"
                        f"休息 {cooldown:g} 秒后重试同一条",
                        file=err,
                        flush=True,
                    )
                    sleep(cooldown)
                    cooldown_count += 1
                    print(
                        f"[限流] 冷却结束，继续 {kind}={value}",
                        file=err,
                        flush=True,
                    )
                    continue
                if code == "forbidden":
                    skipped += 1
                    quota_times.append(now())
                    _record(
                        state_path,
                        done,
                        "skipped",
                        kind,
                        value,
                        reason="forbidden",
                    )
                    pace_before = True
                    break
                stopped_reason = code if code in _STOP_CODES else code
                break
            stamp = now()
            quota_times.append(stamp)
            result = payload if isinstance(payload, Mapping) else {}
            user_id = str(result.get("user_id") or "")
            screen_name = str(result.get("screen_name") or "")
            if result.get("already_following") is True:
                already_following += 1
                _record(
                    state_path,
                    done,
                    "already_following",
                    kind,
                    value,
                    user_id=user_id,
                    screen_name=screen_name,
                    at=stamp,
                )
            else:
                followed += 1
                _record(
                    state_path,
                    done,
                    "followed",
                    kind,
                    value,
                    user_id=user_id,
                    screen_name=screen_name,
                    at=stamp,
                )
            pace_before = True
            break
        if stopped_reason:
            break

    return {
        "kind": "twitter_follow_batch",
        "attempted": attempted,
        "followed": followed,
        "skipped": skipped,
        "already_following": already_following,
        "stopped_reason": stopped_reason,
        "cooldown": cooldown_count,
    }


def _load_file(path: Path | None) -> list[tuple[str, str, str]]:
    if path is None or not path.is_file():
        raise TwitterInputError(f"follow-batch file not found: {path}")
    rows: list[tuple[str, str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed = _parse_identity(line)
        if parsed is None:
            rows.append(("invalid", line, "invalid"))
        else:
            kind, value = parsed
            rows.append((kind, value, ""))
    return rows


def _load_csv(path: Path | None) -> list[tuple[str, str, str]]:
    if path is None or not path.is_file():
        raise TwitterInputError(f"follow-batch csv not found: {path}")
    rows: list[tuple[str, str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "主页链接" not in reader.fieldnames:
            raise TwitterInputError("csv must contain 主页链接 column")
        for row in reader:
            homepage = str(row.get("主页链接") or "").strip()
            handle_name = _handle_from_url(homepage)
            if not handle_name:
                rows.append(("invalid", homepage or "", "invalid"))
                continue
            followed = str(row.get("我是否关注") or "").strip()
            skip_reason = "already_following" if followed == "是" else ""
            rows.append(("screen_name", handle_name, skip_reason))
    return rows


def _parse_identity(value: str) -> tuple[str, str] | None:
    text = value.strip()
    if text.startswith("@"):
        text = text[1:]
    if _USER_ID_RE.fullmatch(text):
        return "user_id", text
    if _SCREEN_NAME_RE.fullmatch(text):
        return "screen_name", text
    return None


def _handle_from_url(value: str) -> str:
    text = value.strip()
    match = _PROFILE_URL_RE.match(text)
    if not match:
        return ""
    handle = match.group(1)
    if not _SCREEN_NAME_RE.fullmatch(handle):
        return ""
    return handle


def _identity_keys(kind: str, value: str) -> set[str]:
    if kind == "user_id":
        return _keys_from_record(value, "")
    if kind == "screen_name":
        return _keys_from_record("", value)
    return set()


def _keys_from_record(user_id: str, screen_name: str) -> set[str]:
    keys: set[str] = set()
    rest_id = user_id.strip()
    handle = screen_name.strip().lstrip("@")
    if _USER_ID_RE.fullmatch(rest_id):
        keys.add(f"user_id:{rest_id}")
    if handle:
        keys.add(f"screen_name:{handle.lower()}")
    return keys


def _load_done(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.is_file():
        return done
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return done
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or row.get("type") not in _DONE_TYPES:
            continue
        done.update(
            _keys_from_record(
                str(row.get("user_id") or ""),
                str(row.get("screen_name") or ""),
            )
        )
    return done


def _record(
    path: Path,
    done: set[str],
    event_type: str,
    kind: str,
    value: str,
    *,
    user_id: str = "",
    screen_name: str = "",
    reason: str = "",
    at: float | None = None,
) -> None:
    if kind == "user_id" and not user_id:
        user_id = value
    if kind == "screen_name" and not screen_name:
        screen_name = value
    event: dict[str, Any] = {
        "type": event_type,
        "user_id": user_id,
        "screen_name": screen_name,
    }
    if reason:
        event["reason"] = reason
    if at is not None:
        event["at"] = at
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    done.update(_keys_from_record(user_id, screen_name))


def _require_non_negative(name: str, value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise TwitterInputError(f"{name} must be a non-negative number of seconds")


def _counts_toward_quota(row: Mapping[str, Any]) -> bool:
    event_type = row.get("type")
    if event_type in {"followed", "already_following"}:
        return True
    return event_type == "skipped" and row.get("reason") == "forbidden"


def _load_quota_times(path: Path) -> list[float | None]:
    times: list[float | None] = []
    if not path.is_file():
        return times
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return times
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or not _counts_toward_quota(row):
            continue
        stamp = row.get("at")
        if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
            times.append(float(stamp))
        else:
            times.append(None)
    return times


def _quota_wait(
    times: list[float | None],
    *,
    now: float,
    window_seconds: float,
    window_limit: int,
    daily_limit: int,
) -> tuple[str | None, float]:
    daily = 0
    window: list[float] = []
    for stamp in times:
        if stamp is None:
            daily += 1
            continue
        if now - stamp < DAILY_SECONDS:
            daily += 1
        if window_seconds > 0 and now - stamp < window_seconds:
            window.append(stamp)
    if daily_limit > 0 and daily >= daily_limit:
        return "daily_limit", 0.0
    if window_limit > 0 and len(window) >= window_limit:
        return "window", max(window_seconds - (now - min(window)), 0.0)
    return None, 0.0
