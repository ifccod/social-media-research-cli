from __future__ import annotations

import csv
import json
import math
import sys
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from . import judge as judge_mod
from .errors import TwitterInputError, TwitterResponseError
from .labels import (
    DEFAULT_EXPAND_MAX_FOLLOWERS,
    DEFAULT_EXPAND_MIN_FOLLOWERS,
    DEFAULT_KOL_FOLLOWING_RATIO,
    DEFAULT_KOL_MIN_FOLLOWERS,
    DEFAULT_MUTUAL_MIN_COUNT,
    DEFAULT_MUTUAL_RATIO_MAX,
    DEFAULT_MUTUAL_RATIO_MIN,
    account_tag,
    is_expand_hub,
)

"""
┌───────────────────────┬────────────────────────────────────────────────────────┐
│ 参数                  │ 作用                                                   │
├───────────────────────┼────────────────────────────────────────────────────────┤
│ --pages 15            │ 自己的 following / followers 各翻 15 页（约 20 人/页） │
├───────────────────────┼────────────────────────────────────────────────────────┤
│ --expand-pages 3      │ 命中的 50–10k 粉互关蓝 V，再翻他们的粉/关各 3 页        │
├───────────────────────┼────────────────────────────────────────────────────────┤
│ --max-expand-users 20 │ 最多拿 20 个枢纽去滚雪球（大 V 仍只进榜、不扩散）      │
├───────────────────────┼────────────────────────────────────────────────────────┤
│ --max-candidates 200  │ 本轮最多新处理 200 人                                  │
├───────────────────────┼────────────────────────────────────────────────────────┤
│ --max-llm-calls 120   │ 本轮最多新打 120 次 Gemini                             │
├───────────────────────┼────────────────────────────────────────────────────────┤
│ --excel               │ 直接出表                                               │
└───────────────────────┴────────────────────────────────────────────────────────┘ 
python -m reverse twitter discover \
  --pages 15 \
  --expand-pages 100 \
  --max-expand-users 20000 \
  --max-candidates 20000 \
  --max-llm-calls 20000 \
  --max-seconds 3600 \
  --csv
"""

DEFAULT_CRITERIA = (
    "必须与 AI、独立开发、大模型、科技或 API 中转站相关。"
    "排除：加密货币、Web3、空投、抽奖、美女图搬运、灰产、泛娱乐、八卦、段子、游戏。"
)
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash-high"
DEFAULT_STATE_NAME = "twitter-discover-state.jsonl"
DEFAULT_CSV_NAME = "twitter-discover.csv"
DEFAULT_GEMINI_CONCURRENCY = 1
_LIST_PAGE_SIZE = 20
_FAMILY_STOP = frozenset({"rate_limited", "forbidden", "verification_required"})
_SKIP_ZERO = {
    "not_blue": 0,
    "not_criteria": 0,
    "protected": 0,
    "unavailable": 0,
    "missing_counts": 0,
    "duplicate": 0,
    "llm_failed": 0,
    "invalid_response": 0,
    "gemini_rate_limited": 0,
}


@dataclass
class _State:
    path: Path
    terminal: dict[str, dict[str, Any]] = field(default_factory=dict)
    queue: deque[str] = field(default_factory=deque)
    queued_ids: set[str] = field(default_factory=set)
    users: dict[str, dict[str, Any]] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    depths: dict[str, int] = field(default_factory=dict)
    lists: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    llm_calls: int = 0
    need_tweets_ids: set[str] = field(default_factory=set)
    tweets_llm_ids: set[str] = field(default_factory=set)
    expand_users: set[str] = field(default_factory=set)
    hits: dict[str, dict[str, Any]] = field(default_factory=dict)
    judged_ids: set[str] = field(default_factory=set)
    metas: list[dict[str, Any]] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=lambda: dict(_SKIP_ZERO))
    visited: int = 0
    dry_items: list[dict[str, Any]] = field(default_factory=list)
    excluded_suggestion_ids: set[str] = field(default_factory=set)
    last_stop: str | None = None
    profile_ids: set[str] = field(default_factory=set)
    tweets: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    llm_results: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    llm_at_start: int = 0
    started_ids: set[str] = field(default_factory=set)


def run_discover(
    client: Any,
    *,
    seeds: Sequence[str] | None = None,
    max_seed_pages: int = 2,
    max_candidates: int = 80,
    max_llm_calls: int = 40,
    max_seconds: float = 600,
    max_expand_users: int = 5,
    max_expand_pages: int = 1,
    expand_min_followers: int = DEFAULT_EXPAND_MIN_FOLLOWERS,
    expand_max_followers: int = DEFAULT_EXPAND_MAX_FOLLOWERS,
    daily_budget: int = 90,
    batch_size: int = 30,
    user_tweets_limit: int = 10,
    kol_min_followers: int = DEFAULT_KOL_MIN_FOLLOWERS,
    kol_following_ratio: float = DEFAULT_KOL_FOLLOWING_RATIO,
    mutual_ratio_min: float = DEFAULT_MUTUAL_RATIO_MIN,
    mutual_ratio_max: float = DEFAULT_MUTUAL_RATIO_MAX,
    mutual_min_count: int = DEFAULT_MUTUAL_MIN_COUNT,
    include_untagged: bool = True,
    state_path: Path,
    markdown_path: Path | None = None,
    csv_path: Path | None = None,
    criteria: str = DEFAULT_CRITERIA,
    gemini_base_url: str = "",
    gemini_api_key: str = "",
    gemini_model: str = DEFAULT_GEMINI_MODEL,
    gemini_timeout: float = 120,
    gemini_concurrency: int = DEFAULT_GEMINI_CONCURRENCY,
    dry_run: bool = False,
    judge_account: Callable[..., Mapping[str, Any]] | None = None,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] | None = None,
    err: TextIO | None = None,
) -> dict[str, Any]:
    """编排种子列表、硬过滤、Gemini 判定和有界扩散，写出只读榜单。"""

    _validate_discover(
        daily_budget=daily_budget,
        max_seed_pages=max_seed_pages,
        max_expand_pages=max_expand_pages,
        gemini_concurrency=gemini_concurrency,
        dry_run=dry_run,
        gemini_base_url=gemini_base_url,
        gemini_api_key=gemini_api_key,
    )
    seed_names = _normalize_seeds(seeds)
    criteria_text = str(criteria or "").strip() or DEFAULT_CRITERIA
    judge_fn = judge_account or judge_mod.judge_account
    log = err if err is not None else sys.stderr
    stamp = now or (lambda: datetime.now(timezone.utc))
    state = _replay(state_path)
    if not state.metas:
        _write(
            state,
            {
                "type": "meta",
                "started_at": stamp().isoformat(),
                "seeds": [f"{name}:me" for name in seed_names],
                "criteria": criteria_text,
            },
        )
        state.metas.append({"type": "meta"})
    state.llm_at_start = state.llm_calls
    state.visited = 0
    state.started_ids.clear()
    drain_opts: dict[str, Any] = {
        "seed_names": seed_names,
        "max_seed_pages": max_seed_pages,
        "max_candidates": max_candidates,
        "max_llm_calls": max_llm_calls,
        "max_seconds": max_seconds,
        "max_expand_users": max_expand_users,
        "max_expand_pages": max_expand_pages,
        "expand_min_followers": expand_min_followers,
        "expand_max_followers": expand_max_followers,
        "user_tweets_limit": user_tweets_limit,
        "kol_min_followers": kol_min_followers,
        "kol_following_ratio": kol_following_ratio,
        "mutual_ratio_min": mutual_ratio_min,
        "mutual_ratio_max": mutual_ratio_max,
        "mutual_min_count": mutual_min_count,
        "criteria": criteria_text,
        "gemini_base_url": str(gemini_base_url or "").strip(),
        "gemini_api_key": str(gemini_api_key or "").strip(),
        "gemini_model": gemini_model,
        "gemini_timeout": gemini_timeout,
        "gemini_concurrency": gemini_concurrency,
        "dry_run": dry_run,
        "judge_fn": judge_fn,
        "clock": clock,
        "log": log,
    }
    _prepare_lists(
        state,
        seed_names,
        max_seed_pages=max_seed_pages,
        max_expand_pages=max_expand_pages,
    )
    _restore_expand_from_hits(state, **drain_opts)
    stopped = _drain(client, state, **drain_opts)
    _write(state, {"type": "stop", "reason": stopped})
    ranking = _build_ranking(
        state,
        criteria=criteria_text,
        model=gemini_model,
        stopped_reason=stopped,
        daily_budget=daily_budget,
        batch_size=batch_size,
        include_untagged=include_untagged,
        dry_run=dry_run,
    )
    if markdown_path is not None:
        markdown_path.write_text(_render_markdown(ranking), encoding="utf-8")
    if csv_path is not None:
        _write_csv(csv_path, ranking)
    _write_summary(log, ranking)
    return ranking


def _validate_discover(
    *,
    daily_budget: int,
    max_seed_pages: int,
    max_expand_pages: int,
    gemini_concurrency: int,
    dry_run: bool,
    gemini_base_url: str,
    gemini_api_key: str,
) -> None:
    if isinstance(daily_budget, bool) or not isinstance(daily_budget, int):
        raise TwitterInputError("daily-budget 必须在 80 到 100 之间")
    if not 80 <= daily_budget <= 100:
        raise TwitterInputError("daily-budget 必须在 80 到 100 之间")
    for name, value in (
        ("max-seed-pages", max_seed_pages),
        ("max-expand-pages", max_expand_pages),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise TwitterInputError(f"{name} 必须是大于 0 的整数")
    if (
        isinstance(gemini_concurrency, bool)
        or not isinstance(gemini_concurrency, int)
        or not 1 <= gemini_concurrency <= 32
    ):
        raise TwitterInputError("gemini-concurrency 必须在 1 到 32 之间")
    if dry_run:
        return
    if not str(gemini_base_url or "").strip():
        raise TwitterInputError("缺少 GEMINI_BASE_URL 或 --gemini-base-url")
    if not str(gemini_api_key or "").strip():
        raise TwitterInputError("缺少 GEMINI_API_KEY 或 --gemini-api-key")


def _normalize_seeds(seeds: Sequence[str] | None) -> tuple[str, ...]:
    values = tuple(seeds or ("following", "followers"))
    allowed = {"following", "followers"}
    if any(item not in allowed for item in values):
        raise TwitterInputError("seed 只允许 following 或 followers")
    return tuple(dict.fromkeys(values))


def _replay(path: Path) -> _State:
    state = _State(path=path)
    events: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                # ponytail: 崩溃可能留下半行 JSON，跳过无法 json.loads 的行
                continue
            if isinstance(payload, dict):
                events.append(payload)
    last_meta = max(
        (index for index, event in enumerate(events) if event.get("type") == "meta"),
        default=-1,
    )
    for index, event in enumerate(events):
        kind = event.get("type")
        if kind == "meta":
            state.metas.append(event)
        elif kind == "stop":
            reason = event.get("reason")
            if isinstance(reason, str):
                state.last_stop = reason
        elif kind == "cursor":
            key = (_text(event.get("list")), _text(event.get("subject_id")))
            if key[0] and key[1]:
                state.lists[key] = {
                    "page": int(event.get("page") or 0),
                    "cursor": event.get("cursor"),
                    "exhausted": event.get("exhausted") is True,
                    "depth": 0 if key[1] == "me" else 1,
                }
                if key[1] != "me":
                    state.expand_users.add(key[1])
        elif kind == "queued":
            _replay_queued(state, event)
        elif kind == "profile":
            _replay_profile(state, event)
        elif kind == "tweets":
            _replay_tweets(state, event)
        elif kind == "llm":
            _replay_llm(state, event)
        elif kind in {"skip", "hit", "judged"}:
            _replay_terminal(state, event, index=index, last_meta=last_meta)
    state.need_tweets_ids -= set(state.terminal)
    state.need_tweets_ids -= state.tweets_llm_ids
    state.queue = deque(
        user_id for user_id in state.queue if user_id not in state.terminal
    )
    return state


def _replay_queued(state: _State, event: Mapping[str, Any]) -> None:
    user_id = _text(event.get("id"))
    if not user_id or user_id in state.terminal or user_id in state.queued_ids:
        return
    state.queued_ids.add(user_id)
    snapshot = event.get("user")
    if isinstance(snapshot, Mapping):
        state.users[user_id] = dict(snapshot)
    source = _text(event.get("source_seed"))
    if source:
        state.sources[user_id] = source
    depth = event.get("depth")
    state.depths[user_id] = int(depth) if isinstance(depth, int) else 0
    subject_id = _text(event.get("subject_id"))
    if isinstance(depth, int) and depth >= 1 and subject_id:
        state.expand_users.add(subject_id)
    if user_id not in state.terminal:
        state.queue.append(user_id)


def _replay_profile(state: _State, event: Mapping[str, Any]) -> None:
    user_id = _text(event.get("id"))
    if not user_id:
        return
    state.profile_ids.add(user_id)
    snapshot = event.get("user")
    if not isinstance(snapshot, Mapping):
        return
    previous = dict(state.users.get(user_id) or {})
    previous.update(dict(snapshot))
    state.users[user_id] = previous


def _replay_tweets(state: _State, event: Mapping[str, Any]) -> None:
    user_id = _text(event.get("id"))
    raw = event.get("tweets")
    if not user_id or not isinstance(raw, list):
        return
    tweets: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, Mapping):
            tweets.append({"text": _text(item.get("text"))})
    state.tweets[user_id] = tweets


def _replay_llm(state: _State, event: Mapping[str, Any]) -> None:
    state.llm_calls += 1
    user_id = _text(event.get("id"))
    stage = _text(event.get("stage"))
    if not user_id or stage not in {"bio", "tweets"}:
        return
    state.llm_results[(user_id, stage)] = {
        "matches_criteria": event.get("matches_criteria") is True,
        "need_tweets": event.get("need_tweets") is True,
        "confidence": event.get("confidence"),
        "summary": _text(event.get("summary")),
    }
    if stage == "bio" and event.get("need_tweets") is True:
        state.need_tweets_ids.add(user_id)
    if stage == "tweets":
        state.tweets_llm_ids.add(user_id)


def _replay_terminal(
    state: _State,
    event: Mapping[str, Any],
    *,
    index: int,
    last_meta: int,
) -> None:
    user_id = _text(event.get("id"))
    if not user_id:
        return
    kind = event.get("type")
    if kind == "skip" and _text(event.get("reason")) == "llm_failed":
        # 判定失败下次续跑重试，不占终态
        return
    state.terminal[user_id] = dict(event)
    if kind == "skip":
        reason = _text(event.get("reason")) or "not_criteria"
        state.skipped[reason] = state.skipped.get(reason, 0) + 1
    elif kind == "judged":
        state.judged_ids.add(user_id)
    elif kind == "hit":
        state.hits[user_id] = _item_from_event(event)
        if index < last_meta:
            state.excluded_suggestion_ids.add(user_id)


def _prepare_lists(
    state: _State,
    seeds: Sequence[str],
    *,
    max_seed_pages: int,
    max_expand_pages: int,
) -> None:
    for name in seeds:
        key = (name, "me")
        if key not in state.lists:
            state.lists[key] = {
                "page": 0,
                "cursor": None,
                "exhausted": False,
                "depth": 0,
                "max_pages": max_seed_pages,
            }
    for key, rec in state.lists.items():
        rec["depth"] = int(rec.get("depth") or (0 if key[1] == "me" else 1))
        limit = max_seed_pages if key[1] == "me" else max_expand_pages
        rec["max_pages"] = max(int(rec.get("max_pages") or 0), limit)
        if rec.get("exhausted") is True and _text(rec.get("cursor")):
            rec["exhausted"] = False


def _drain(
    client: Any,
    state: _State,
    **opts: Any,
) -> str:
    started = opts["clock"]()
    dry_run = bool(opts["dry_run"])
    concurrency = 1 if dry_run else max(1, int(opts.get("gemini_concurrency") or 1))
    pending: dict[Future[Any], dict[str, Any]] = {}
    executor: ThreadPoolExecutor | None = None
    if not dry_run:
        executor = ThreadPoolExecutor(max_workers=concurrency)
    try:
        while True:
            if opts["clock"]() - started >= opts["max_seconds"]:
                return "max_seconds"
            stopped = _collect_pending(
                client, state, pending, executor, **opts
            )
            if stopped:
                return stopped
            if state.visited >= opts["max_candidates"]:
                if pending:
                    _wait_pending(pending)
                    continue
                return "max_candidates"
            if state.queue:
                status = _start_candidate(
                    client, state, pending, executor, **opts
                )
                if status == "wait":
                    if pending:
                        _wait_pending(pending)
                        continue
                    return "max_llm_calls"
                if status:
                    return status
                continue
            if pending:
                _wait_pending(pending)
                continue
            pulled = _pull_next_list_page(client, state, **opts)
            if pulled is None:
                return "dry_run" if dry_run else "completed"
            if isinstance(pulled, str):
                return pulled
            _emit_progress(state, pending, opts)
    finally:
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


def _wait_pending(pending: Mapping[Future[Any], dict[str, Any]]) -> None:
    if pending:
        wait(tuple(pending), timeout=0.5, return_when=FIRST_COMPLETED)


def _emit_progress(
    state: _State,
    pending: Mapping[Future[Any], dict[str, Any]],
    opts: Mapping[str, Any],
) -> None:
    log = opts.get("log")
    if log is None:
        return
    print(
        "[discover] "
        f"visited={state.visited} inflight={len(pending)} "
        f"llm={_run_llm_calls(state)} queue={len(state.queue)} "
        f"hits={len(state.hits)}",
        file=log,
        flush=True,
    )


def _can_submit_judge(
    state: _State,
    pending: Mapping[Future[Any], dict[str, Any]],
    **opts: Any,
) -> bool:
    concurrency = max(1, int(opts.get("gemini_concurrency") or 1))
    return (
        len(pending) < concurrency
        and _run_llm_calls(state) + len(pending) < opts["max_llm_calls"]
    )


def _start_candidate(
    client: Any,
    state: _State,
    pending: dict[Future[Any], dict[str, Any]],
    executor: ThreadPoolExecutor | None,
    **opts: Any,
) -> str | None:
    user_id = state.queue.popleft()
    if user_id in state.terminal:
        return None
    if user_id not in state.started_ids:
        state.started_ids.add(user_id)
        state.visited += 1
    cached_tweets = state.llm_results.get((user_id, "tweets"))
    if cached_tweets is not None:
        return _finish_cached_judgment(
            client,
            state,
            user_id,
            cached_tweets,
            judged_from="bio+tweets",
            **opts,
        )
    cached_bio = state.llm_results.get((user_id, "bio"))
    if cached_bio is not None:
        if cached_bio["need_tweets"] or user_id in state.need_tweets_ids:
            return _submit_tweets_judge(
                client, state, user_id, pending, executor, **opts
            )
        if cached_bio["matches_criteria"]:
            return _finish_cached_judgment(
                client,
                state,
                user_id,
                cached_bio,
                judged_from="bio",
                **opts,
            )
        _skip(state, user_id, "not_criteria")
        return None
    if user_id in state.need_tweets_ids:
        return _submit_tweets_judge(
            client, state, user_id, pending, executor, **opts
        )
    user, stopped = _resolve_user(client, state, user_id)
    if stopped:
        return stopped
    if user is None:
        return None
    skip_reason = _hard_filter(user)
    if skip_reason:
        _skip(state, user_id, skip_reason)
        return None
    if not str(user.get("description") or "").strip():
        user, stopped = _fill_description(client, state, user)
        if stopped:
            return stopped
        if user is None:
            return None
        skip_reason = _hard_filter(user)
        if skip_reason:
            _skip(state, user_id, skip_reason)
            return None
    tag = _tag_user(user, **opts)
    if opts["dry_run"]:
        state.dry_items.append(
            _ranking_item(
                user,
                tag=tag,
                source_seed=state.sources.get(user_id, ""),
                matches_criteria=False,
                summary="",
                confidence=None,
                judged_from="dry-run",
            )
        )
        return None
    if not _can_submit_judge(state, pending, **opts) or executor is None:
        state.queue.appendleft(user_id)
        return "wait"
    _submit_judge(
        executor,
        pending,
        {
            "user_id": user_id,
            "stage": "bio",
            "user": dict(user),
            "tweets": [],
            "tag": tag,
        },
        **opts,
    )
    return None


def _submit_tweets_judge(
    client: Any,
    state: _State,
    user_id: str,
    pending: dict[Future[Any], dict[str, Any]],
    executor: ThreadPoolExecutor | None,
    **opts: Any,
) -> str | None:
    cached = state.llm_results.get((user_id, "tweets"))
    if cached is not None:
        return _finish_cached_judgment(
            client,
            state,
            user_id,
            cached,
            judged_from="bio+tweets",
            **opts,
        )
    if opts["dry_run"]:
        return None
    if not _can_submit_judge(state, pending, **opts) or executor is None:
        if user_id not in state.queue:
            state.queue.appendleft(user_id)
        return "wait"
    user, stopped = _resolve_user(client, state, user_id)
    if stopped:
        return stopped
    if user is None:
        return None
    tweets, stopped = _load_tweets(client, state, user_id, opts["user_tweets_limit"])
    if stopped:
        if user_id not in state.queue:
            state.queue.appendleft(user_id)
        return stopped
    if tweets is None:
        return None
    _submit_judge(
        executor,
        pending,
        {
            "user_id": user_id,
            "stage": "tweets",
            "user": dict(user),
            "tweets": list(tweets),
            "tag": _tag_user(user, **opts),
        },
        **opts,
    )
    return None


def _submit_judge(
    executor: ThreadPoolExecutor,
    pending: dict[Future[Any], dict[str, Any]],
    job: dict[str, Any],
    **opts: Any,
) -> None:
    account = _judge_account_payload(job["user"], job.get("tweets") or [])
    future = executor.submit(
        _invoke_judge,
        opts["judge_fn"],
        account,
        opts["criteria"],
        opts["gemini_base_url"],
        opts["gemini_api_key"],
        opts["gemini_timeout"],
        opts["gemini_model"],
    )
    pending[future] = job


def _invoke_judge(
    judge_fn: Callable[..., Mapping[str, Any]],
    account: Mapping[str, Any],
    criteria: str,
    base_url: str,
    api_key: str,
    timeout: float,
    model: str,
) -> tuple[str, Any]:
    try:
        judgment = judge_fn(
            account,
            criteria=criteria,
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            model=model,
        )
    except TwitterResponseError as exc:
        return ("error", exc)
    except Exception as exc:
        return (
            "error",
            TwitterResponseError(str(exc), code="llm_failed"),
        )
    if not isinstance(judgment, Mapping):
        return (
            "error",
            TwitterResponseError("Gemini 判定结果无法解析", code="llm_failed"),
        )
    return (
        "ok",
        {
            "matches_criteria": judgment.get("matches_criteria") is True,
            "need_tweets": judgment.get("need_tweets") is True,
            "confidence": judgment.get("confidence"),
            "summary": _text(judgment.get("summary")),
        },
    )


def _collect_pending(
    client: Any,
    state: _State,
    pending: dict[Future[Any], dict[str, Any]],
    executor: ThreadPoolExecutor | None,
    **opts: Any,
) -> str | None:
    for future in [item for item in pending if item.done()]:
        job = pending.pop(future)
        stopped = _apply_judge_future(
            client, state, job, future, pending, executor, **opts
        )
        if stopped:
            return stopped
        _emit_progress(state, pending, opts)
    return None


def _apply_judge_future(
    client: Any,
    state: _State,
    job: Mapping[str, Any],
    future: Future[Any],
    pending: dict[Future[Any], dict[str, Any]],
    executor: ThreadPoolExecutor | None,
    **opts: Any,
) -> str | None:
    user_id = _text(job.get("user_id"))
    try:
        status, payload = future.result()
    except Exception as exc:
        _skip_llm_failed(state, user_id, str(exc), opts)
        return None
    if status == "error":
        exc = payload
        code = getattr(exc, "code", None)
        if code == "gemini_unauthorized":
            return "gemini_unauthorized"
        if code in _FAMILY_STOP:
            return str(code)
        if code == "gemini_rate_limited":
            _skip(state, user_id, "gemini_rate_limited")
            return None
        _skip_llm_failed(state, user_id, str(exc), opts)
        return None
    parsed = payload if isinstance(payload, Mapping) else {}
    stage = _text(job.get("stage")) or "bio"
    _commit_llm(state, user_id, stage, parsed)
    if stage == "tweets":
        state.need_tweets_ids.discard(user_id)
    if stage == "bio" and parsed.get("need_tweets") is True:
        state.need_tweets_ids.add(user_id)
        status = _submit_tweets_judge(
            client, state, user_id, pending, executor, **opts
        )
        if status == "wait":
            return None
        return status
    if parsed.get("matches_criteria") is True:
        user = job.get("user")
        if not isinstance(user, Mapping):
            user, stopped = _resolve_user(client, state, user_id)
            if stopped:
                return stopped
            if user is None:
                return None
        return _record_hit(
            client,
            state,
            user,
            tag=_text(job.get("tag")) or _tag_user(user, **opts),
            judgment=parsed,
            judged_from="bio" if stage == "bio" else "bio+tweets",
            **opts,
        )
    _skip(state, user_id, "not_criteria")
    return None


def _commit_llm(
    state: _State,
    user_id: str,
    stage: str,
    parsed: Mapping[str, Any],
) -> None:
    _write(
        state,
        {
            "type": "llm",
            "id": user_id,
            "stage": stage,
            "need_tweets": parsed.get("need_tweets") is True,
            "matches_criteria": parsed.get("matches_criteria") is True,
            "summary": _text(parsed.get("summary")),
            "confidence": parsed.get("confidence"),
        },
    )
    state.llm_results[(user_id, stage)] = {
        "matches_criteria": parsed.get("matches_criteria") is True,
        "need_tweets": parsed.get("need_tweets") is True,
        "confidence": parsed.get("confidence"),
        "summary": _text(parsed.get("summary")),
    }
    state.llm_calls += 1


def _judge_account_payload(
    user: Mapping[str, Any],
    tweets: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    return {
        "username": user.get("username"),
        "name": user.get("name"),
        "description": user.get("description"),
        "followers": user.get("followers"),
        "following": user.get("following"),
        "blue_verified": user.get("blue_verified"),
        "tweets": [dict(item) for item in tweets],
    }


def _tag_user(user: Mapping[str, Any], **opts: Any) -> str:
    return account_tag(
        _optional_int(user.get("followers")),
        _optional_int(user.get("following")),
        kol_min_followers=opts["kol_min_followers"],
        kol_following_ratio=opts["kol_following_ratio"],
        mutual_ratio_min=opts["mutual_ratio_min"],
        mutual_ratio_max=opts["mutual_ratio_max"],
        mutual_min_count=opts["mutual_min_count"],
    )


def _run_llm_calls(state: _State) -> int:
    return max(0, state.llm_calls - state.llm_at_start)


def _finish_cached_judgment(
    client: Any,
    state: _State,
    user_id: str,
    judgment: Mapping[str, Any],
    *,
    judged_from: str,
    **opts: Any,
) -> str | None:
    user, stopped = _resolve_user(client, state, user_id)
    if stopped:
        return stopped
    if user is None:
        return None
    if judgment.get("matches_criteria") is not True:
        _skip(state, user_id, "not_criteria")
        return None
    tag = account_tag(
        _optional_int(user.get("followers")),
        _optional_int(user.get("following")),
        kol_min_followers=opts["kol_min_followers"],
        kol_following_ratio=opts["kol_following_ratio"],
        mutual_ratio_min=opts["mutual_ratio_min"],
        mutual_ratio_max=opts["mutual_ratio_max"],
        mutual_min_count=opts["mutual_min_count"],
    )
    return _record_hit(
        client,
        state,
        user,
        tag=tag,
        judgment=judgment,
        judged_from=judged_from,
        **opts,
    )


def _record_hit(
    client: Any,
    state: _State,
    user: Mapping[str, Any],
    *,
    tag: str,
    judgment: Mapping[str, Any],
    judged_from: str,
    **opts: Any,
) -> str | None:
    user_id = _text(user.get("id"))
    item = _ranking_item(
        user,
        tag=tag,
        source_seed=state.sources.get(user_id, ""),
        matches_criteria=True,
        summary=_text(judgment.get("summary")),
        confidence=judgment.get("confidence"),
        judged_from=judged_from,
    )
    hit_event = {"type": "hit", **item}
    _write(state, hit_event)
    state.terminal[user_id] = hit_event
    state.hits[user_id] = item
    _write(
        state,
        {
            "type": "judged",
            "id": user_id,
            "matches_criteria": True,
            "judged_from": judged_from,
            "summary": item["ai_summary"],
            "confidence": item["confidence"],
        },
    )
    state.judged_ids.add(user_id)
    return _maybe_expand(client, state, user, tag=tag, **opts)


def _restore_expand_from_hits(state: _State, **opts: Any) -> None:
    for user_id, item in state.hits.items():
        user = state.users.get(user_id)
        if not isinstance(user, Mapping):
            continue
        tag = _text(item.get("tag")) or _tag_user(user, **opts)
        _maybe_expand(None, state, user, tag=tag, **opts)


def _maybe_expand(
    client: Any,
    state: _State,
    user: Mapping[str, Any],
    *,
    tag: str,
    **opts: Any,
) -> str | None:
    user_id = _text(user.get("id"))
    if not user_id:
        return None
    if not is_expand_hub(
        tag,
        _optional_int(user.get("followers")),
        expand_min_followers=opts["expand_min_followers"],
        expand_max_followers=opts["expand_max_followers"],
    ):
        return None
    already = user_id in state.expand_users
    if not already and len(state.expand_users) >= opts["max_expand_users"]:
        return None
    parent_depth = state.depths.get(user_id, 0)
    state.expand_users.add(user_id)
    # ponytail: 只登记列表，由 drain 在队列和 Gemini 都空时再翻一页
    for list_kind in ("following", "followers"):
        key = (list_kind, user_id)
        rec = state.lists.get(key)
        if rec is None:
            state.lists[key] = {
                "page": 0,
                "cursor": None,
                "exhausted": False,
                "depth": parent_depth + 1,
                "max_pages": opts["max_expand_pages"],
            }
            continue
        rec["max_pages"] = max(
            int(rec.get("max_pages") or 0),
            opts["max_expand_pages"],
        )
        if rec.get("exhausted") is True and _text(rec.get("cursor")):
            rec["exhausted"] = False
    return None


def _hard_filter(user: Mapping[str, Any]) -> str | None:
    if user.get("unavailable") is True:
        return "unavailable"
    if user.get("protected") is True:
        return "protected"
    if user.get("blue_verified") is not True:
        return "not_blue"
    if user.get("followers") is None and user.get("following") is None:
        return "missing_counts"
    return None


def _resolve_user(
    client: Any,
    state: _State,
    user_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    cached = state.users.get(user_id)
    if cached:
        return cached, None
    return _fetch_user(client, state, user_id)


def _fill_description(
    client: Any,
    state: _State,
    user: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    user_id = _text(user.get("id"))
    if user_id in state.profile_ids:
        return dict(state.users.get(user_id) or user), None
    fetched, stopped = _fetch_user(client, state, user_id)
    if stopped:
        return None, stopped
    return fetched, None


def _fetch_user(
    client: Any,
    state: _State,
    user_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = client.get_user(user_id=user_id)
    except TwitterResponseError as exc:
        return _user_fetch_failure(state, user_id, exc)
    raw = payload.get("user") if isinstance(payload, Mapping) else None
    if not isinstance(raw, Mapping) or not _text(raw.get("id")):
        _skip(state, user_id, "invalid_response")
        return None, None
    previous = dict(state.users.get(user_id) or {})
    merged = dict(previous)
    merged.update(dict(raw))
    if merged.get("followed_by_me") is None and previous.get("followed_by_me") is not None:
        merged["followed_by_me"] = previous.get("followed_by_me")
    state.users[user_id] = merged
    state.profile_ids.add(user_id)
    _write(state, {"type": "profile", "id": user_id, "user": merged})
    return merged, None


def _user_fetch_failure(
    state: _State,
    user_id: str,
    exc: TwitterResponseError,
) -> tuple[None, str | None]:
    if exc.code in _FAMILY_STOP:
        return None, exc.code
    if exc.code == "invalid_response":
        _skip(state, user_id, "invalid_response")
        return None, None
    raise exc


def _load_tweets(
    client: Any,
    state: _State,
    user_id: str,
    limit: int,
) -> tuple[list[dict[str, str]] | None, str | None]:
    cached = state.tweets.get(user_id)
    if cached is not None:
        return list(cached), None
    try:
        payload = client.get_user_tweets(user_id=user_id, limit=limit)
    except TwitterResponseError as exc:
        if exc.code in _FAMILY_STOP:
            return None, exc.code
        if exc.code == "invalid_response":
            _skip(state, user_id, "invalid_response")
            return None, None
        raise
    posts = payload.get("posts") if isinstance(payload, Mapping) else None
    tweets: list[dict[str, str]] = []
    if isinstance(posts, list):
        for post in posts:
            if isinstance(post, Mapping):
                tweets.append({"text": _text(post.get("text"))})
    state.tweets[user_id] = tweets
    _write(state, {"type": "tweets", "id": user_id, "tweets": tweets})
    return tweets, None


def _pull_next_list_page(client: Any, state: _State, **opts: Any) -> str | bool | None:
    key = _next_open_list(
        state,
        seeds=opts["seed_names"],
        max_seed_pages=opts["max_seed_pages"],
        max_expand_pages=opts["max_expand_pages"],
    )
    if key is None:
        return None
    return _pull_list_page(client, state, key)


def _next_open_list(
    state: _State,
    *,
    seeds: Sequence[str],
    max_seed_pages: int,
    max_expand_pages: int,
) -> tuple[str, str] | None:
    best: tuple[str, str] | None = None
    best_rank: tuple[int, int] | None = None
    for key, rec in state.lists.items():
        limit = rec.get("max_pages")
        if not isinstance(limit, int):
            limit = max_seed_pages if key[1] == "me" else max_expand_pages
        if rec.get("exhausted") is True:
            continue
        page = int(rec.get("page") or 0)
        if page >= limit:
            continue
        # 枢纽列表优先于自己的剩余页；同层按已翻页数升序，避免一个名单翻完再开下一个
        rank = (0 if key[1] != "me" else 1, page)
        if best_rank is None or rank < best_rank:
            best = key
            best_rank = rank
    return best


def _pull_list_page(
    client: Any,
    state: _State,
    key: tuple[str, str],
) -> str | bool | None:
    list_kind, subject_id = key
    rec = state.lists.setdefault(
        key,
        {"page": 0, "cursor": None, "exhausted": False, "depth": 0 if subject_id == "me" else 1},
    )
    max_pages = rec.get("max_pages")
    if rec.get("exhausted") is True:
        return None
    if isinstance(max_pages, int) and int(rec.get("page") or 0) >= max_pages:
        return None
    cursor = rec.get("cursor")
    request_cursor = cursor if isinstance(cursor, str) and cursor else None
    try:
        payload = _request_list(
            client,
            list_kind,
            subject_id,
            cursor=request_cursor,
        )
    except TwitterResponseError as exc:
        if exc.code in _FAMILY_STOP:
            return exc.code
        if exc.code == "invalid_response":
            rec["exhausted"] = True
            _write(
                state,
                {
                    "type": "cursor",
                    "list": list_kind,
                    "subject_id": subject_id,
                    "page": int(rec.get("page") or 0),
                    "cursor": rec.get("cursor"),
                    "exhausted": True,
                },
            )
            return False
        raise
    items = payload.get("items") if isinstance(payload, Mapping) else None
    depth = int(rec.get("depth") or (0 if subject_id == "me" else 1))
    source_seed = f"{list_kind}:me" if subject_id == "me" else f"expand:{subject_id}"
    if isinstance(items, list):
        for item in items:
            if isinstance(item, Mapping):
                _enqueue(state, item, list_kind=list_kind, subject_id=subject_id, depth=depth, source_seed=source_seed)
    next_cursor = payload.get("next_cursor") if isinstance(payload, Mapping) else None
    has_more = payload.get("has_more") is True if isinstance(payload, Mapping) else False
    page = int(rec.get("page") or 0) + 1
    exhausted = (not has_more) or not _text(next_cursor)
    rec["page"] = page
    rec["cursor"] = next_cursor
    rec["exhausted"] = exhausted
    _write(
        state,
        {
            "type": "cursor",
            "list": list_kind,
            "subject_id": subject_id,
            "page": page,
            "cursor": next_cursor,
            "exhausted": exhausted,
        },
    )
    if depth >= 1:
        state.expand_users.add(subject_id)
    return True


def _request_list(
    client: Any,
    list_kind: str,
    subject_id: str,
    *,
    cursor: str | None,
) -> Mapping[str, Any]:
    kwargs: dict[str, Any] = {"limit": _LIST_PAGE_SIZE, "cursor": cursor}
    if subject_id == "me":
        kwargs["screen_name"] = "me"
    else:
        kwargs["user_id"] = subject_id
    if list_kind == "following":
        return client.get_following(**kwargs)
    return client.get_followers(**kwargs)


def _enqueue(
    state: _State,
    user: Mapping[str, Any],
    *,
    list_kind: str,
    subject_id: str,
    depth: int,
    source_seed: str,
) -> None:
    user_id = _text(user.get("id"))
    if not user_id:
        return
    if user_id in state.terminal or user_id in state.queued_ids:
        state.skipped["duplicate"] = state.skipped.get("duplicate", 0) + 1
        return
    snapshot = dict(user)
    if (
        snapshot.get("followed_by_me") is None
        and list_kind == "following"
        and subject_id == "me"
    ):
        snapshot["followed_by_me"] = True
    event = {
        "type": "queued",
        "id": user_id,
        "list": list_kind,
        "subject_id": subject_id,
        "depth": depth,
        "source_seed": source_seed,
        "user": snapshot,
    }
    _write(state, event)
    state.queued_ids.add(user_id)
    state.queue.append(user_id)
    state.users[user_id] = snapshot
    state.sources[user_id] = source_seed
    state.depths[user_id] = depth
    if depth >= 1:
        state.expand_users.add(subject_id)


def _skip(state: _State, user_id: str, reason: str, detail: str = "") -> None:
    event: dict[str, Any] = {"type": "skip", "id": user_id, "reason": reason}
    if detail:
        event["detail"] = detail[:500]
    _write(state, event)
    if reason != "llm_failed":
        state.terminal[user_id] = event
    state.skipped[reason] = state.skipped.get(reason, 0) + 1
    state.need_tweets_ids.discard(user_id)


def _skip_llm_failed(
    state: _State,
    user_id: str,
    detail: str,
    opts: Mapping[str, Any],
) -> None:
    _skip(state, user_id, "llm_failed", detail)
    log = opts.get("log")
    shown = state.skipped.get("llm_failed") or 0
    if log is None or shown > 3:
        return
    print(f"[discover] llm_failed id={user_id} {detail}", file=log, flush=True)


def _write(state: _State, event: Mapping[str, Any]) -> None:
    state.path.parent.mkdir(parents=True, exist_ok=True)
    with state.path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(event), ensure_ascii=False) + "\n")


def _build_ranking(
    state: _State,
    *,
    criteria: str,
    model: str,
    stopped_reason: str,
    daily_budget: int,
    batch_size: int,
    include_untagged: bool,
    dry_run: bool,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in (*state.hits.values(), *state.dry_items):
        user_id = _text(item.get("id"))
        if not user_id or user_id in seen:
            continue
        if not include_untagged and item.get("tag") == "none":
            continue
        if item.get("judged_from") == "dry-run":
            if not dry_run:
                continue
        elif item.get("matches_criteria") is not True:
            continue
        seen.add(user_id)
        items.append(dict(item))
    items = _sort_items(items)
    return {
        "kind": "twitter_discover_ranking",
        "source": "twitter_web_graphql",
        "transport": "browser_web",
        "browser_session": True,
        "model": model,
        "criteria": criteria,
        "stopped_reason": stopped_reason,
        "daily_budget": daily_budget,
        "batch_size": batch_size,
        "stats": {
            "users_visited": state.visited,
            "judged": len(state.judged_ids),
            "hits": len(state.hits),
            "llm_calls": _run_llm_calls(state),
            "rate_limited": stopped_reason == "rate_limited",
            "skipped": dict(state.skipped),
        },
        "items": items,
        "today_suggested": _today_suggested(
            items,
            daily_budget=daily_budget,
            batch_size=batch_size,
            excluded=state.excluded_suggestion_ids,
        ),
    }


def _sort_items(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    kol = [dict(item) for item in items if item.get("tag") == "kol"]
    mutual = [dict(item) for item in items if item.get("tag") == "mutual_blue"]
    rest = [
        dict(item)
        for item in items
        if item.get("tag") not in {"kol", "mutual_blue"}
    ]
    kol.sort(key=lambda item: int(item.get("followers") or 0), reverse=True)
    mutual.sort(key=_mutual_sort_key)
    return kol + mutual + rest


def _mutual_sort_key(item: Mapping[str, Any]) -> tuple[float, int]:
    followers = int(item.get("followers") or 0)
    following = int(item.get("following") or 0)
    ratio = abs(math.log(following / followers))
    return (ratio, -followers)


def _today_suggested(
    items: Sequence[Mapping[str, Any]],
    *,
    daily_budget: int,
    batch_size: int,
    excluded: set[str],
) -> dict[str, list[dict[str, Any]]]:
    picked: list[dict[str, Any]] = []
    for item in items:
        if item.get("tag") != "mutual_blue" or item.get("matches_criteria") is not True:
            continue
        user_id = _text(item.get("id"))
        if not user_id or user_id in excluded:
            continue
        picked.append(dict(item))
        if len(picked) >= daily_budget:
            break
    size = max(int(batch_size), 1)
    return {
        "morning": picked[:size],
        "afternoon": picked[size : size * 2],
        "evening": picked[size * 2 :],
    }


def _ranking_item(
    user: Mapping[str, Any],
    *,
    tag: str,
    source_seed: str,
    matches_criteria: bool,
    summary: str,
    confidence: Any,
    judged_from: str,
) -> dict[str, Any]:
    username = _text(user.get("username"))
    homepage = (
        _text(user.get("homepage"))
        or _text(user.get("url"))
        or (f"https://x.com/{username}" if username else "")
    )
    return {
        "id": _text(user.get("id")),
        "homepage": homepage,
        "username": username,
        "name": _text(user.get("name")),
        "tag": tag,
        "followers": user.get("followers"),
        "following": user.get("following"),
        "followed_by_me": user.get("followed_by_me"),
        "blue_verified": user.get("blue_verified") is True,
        "bio": _text(user.get("description")),
        "ai_summary": summary,
        "matches_criteria": matches_criteria,
        "ai_related": matches_criteria,
        "confidence": confidence,
        "source_seed": source_seed,
        "judged_from": judged_from,
    }


def _item_from_event(event: Mapping[str, Any]) -> dict[str, Any]:
    matches = event.get("matches_criteria") is True
    return {
        "id": _text(event.get("id")),
        "homepage": _text(event.get("homepage")),
        "username": _text(event.get("username")),
        "name": _text(event.get("name")),
        "tag": _text(event.get("tag")) or "none",
        "followers": event.get("followers"),
        "following": event.get("following"),
        "followed_by_me": event.get("followed_by_me"),
        "blue_verified": event.get("blue_verified") is True,
        "bio": _text(event.get("bio")),
        "ai_summary": _text(event.get("ai_summary")),
        "matches_criteria": matches,
        "ai_related": event.get("ai_related") if "ai_related" in event else matches,
        "confidence": event.get("confidence"),
        "source_seed": _text(event.get("source_seed")),
        "judged_from": _text(event.get("judged_from")),
    }


def _render_markdown(ranking: Mapping[str, Any]) -> str:
    lines = [
        "# twitter discover 榜单",
        "",
        f"stopped_reason: {ranking.get('stopped_reason')}",
        "",
        "| username | tag | followers | following | followed_by_me | matches_criteria | homepage |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in ranking.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| {username} | {tag} | {followers} | {following} | {follow} | {matches} | {homepage} |".format(
                username=item.get("username") or "",
                tag=item.get("tag") or "",
                followers=item.get("followers"),
                following=item.get("following"),
                follow=_follow_label(item.get("followed_by_me")),
                matches=item.get("matches_criteria"),
                homepage=item.get("homepage") or "",
            )
        )
    suggested = ranking.get("today_suggested") or {}
    lines.extend(["", "## 今日建议", ""])
    for batch in ("morning", "afternoon", "evening"):
        lines.append(f"### {batch}")
        rows = suggested.get(batch) or []
        if not rows:
            lines.append("(空)")
        for item in rows:
            if isinstance(item, Mapping):
                lines.append(f"- {item.get('username')} {item.get('homepage')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _follow_label(value: object) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return ""


def _write_csv(path: Path, ranking: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["主页链接", "我是否关注", "标签", "粉丝数", "关注数", "AI判断总结"])
        for item in ranking.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            writer.writerow(
                [
                    _text(item.get("homepage")) or _text(item.get("url")),
                    _follow_label(item.get("followed_by_me")),
                    _text(item.get("tag")),
                    item.get("followers"),
                    item.get("following"),
                    _text(item.get("ai_summary")),
                ]
            )


def _write_summary(err: TextIO, ranking: Mapping[str, Any]) -> None:
    stats = ranking.get("stats") if isinstance(ranking.get("stats"), Mapping) else {}
    skipped = stats.get("skipped") if isinstance(stats.get("skipped"), Mapping) else {}
    stopped = _text(ranking.get("stopped_reason"))
    parts = [
        f"[discover] visited={stats.get('users_visited', 0)}",
        f"judged={stats.get('judged', 0)}",
        f"hits={stats.get('hits', 0)}",
        f"llm={stats.get('llm_calls', 0)}",
        f"skipped_not_blue={skipped.get('not_blue', 0)}",
        f"skipped_not_criteria={skipped.get('not_criteria', 0)}",
        f"rate_limited={'true' if stats.get('rate_limited') else 'false'}",
        f"stopped={stopped}",
    ]
    if stopped in _FAMILY_STOP:
        parts.append("family_latched=true")
    print(" ".join(parts), file=err)


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value