from __future__ import annotations

import csv
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from reverse.twitter_reverse import cli
from reverse.twitter_reverse.discover import DEFAULT_CRITERIA, run_discover
from reverse.twitter_reverse.errors import TwitterInputError, TwitterResponseError


def make_user(
    user_id: str,
    username: str,
    *,
    blue: bool = True,
    followers: int | None = 3000,
    following: int | None = 3000,
    description: str = "I ship local LLM tools",
    protected: bool = False,
    unavailable: bool = False,
    **extra: object,
) -> dict[str, object]:
    homepage = f"https://x.com/{username}"
    user: dict[str, object] = {
        "id": user_id,
        "name": username,
        "username": username,
        "url": homepage,
        "homepage": homepage,
        "avatar_url": "",
        "description": description,
        "verified": blue,
        "legacy_verified": False,
        "blue_verified": blue,
        "followers": followers,
        "following": following,
        "protected": protected,
        "unavailable": unavailable,
    }
    user.update(extra)
    return user


class FakeClient:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, object]] = {}
        self.following: dict[str, list[dict[str, object]]] = {}
        self.followers: dict[str, list[dict[str, object]]] = {}
        self.tweets: dict[str, list[dict[str, object]]] = {}
        self.calls: list[tuple[object, ...]] = []
        self.following_error: Exception | None = None
        self.followers_error: Exception | None = None
        self.user_error: Exception | None = None
        self.tweets_error: Exception | None = None

    def add_user(self, user: dict[str, object]) -> None:
        self.users[str(user["id"])] = user
        self.users[str(user["username"])] = user

    def follow(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("follow", args, kwargs))
        raise AssertionError("discover 不得调用 follow")

    def get_user(self, screen_name: str | None = None, user_id: str | None = None) -> dict:
        self.calls.append(("get_user", screen_name, user_id))
        if self.user_error is not None:
            raise self.user_error
        key = user_id or screen_name
        user = self.users.get(str(key or ""))
        if user is None:
            raise TwitterResponseError("missing user", code="invalid_response")
        return {"kind": "twitter_user", "user": user}

    def get_user_tweets(
        self,
        screen_name: str | None = None,
        user_id: str | None = None,
        *,
        limit: int = 10,
        cursor: str | None = None,
    ) -> dict:
        self.calls.append(("get_user_tweets", screen_name, user_id, limit, cursor))
        if self.tweets_error is not None:
            raise self.tweets_error
        key = str(user_id or screen_name or "")
        return {
            "kind": "twitter_timeline",
            "mode": "user",
            "posts": list(self.tweets.get(key, [])),
        }

    def get_following(
        self,
        screen_name: str | None = None,
        user_id: str | None = None,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict:
        self.calls.append(("get_following", screen_name, user_id, cursor))
        if self.following_error is not None:
            raise self.following_error
        return self._page(self.following, screen_name, user_id, cursor, "twitter_following")

    def get_followers(
        self,
        screen_name: str | None = None,
        user_id: str | None = None,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict:
        self.calls.append(("get_followers", screen_name, user_id, cursor))
        if self.followers_error is not None:
            raise self.followers_error
        return self._page(self.followers, screen_name, user_id, cursor, "twitter_followers")

    def _page(
        self,
        store: dict[str, list[dict[str, object]]],
        screen_name: str | None,
        user_id: str | None,
        cursor: str | None,
        kind: str,
    ) -> dict:
        identity = str(user_id or screen_name or "me")
        pages = store.get(identity) or []
        page = None
        for item in pages:
            page_cursor = item.get("cursor")
            if cursor in {None, ""} and not page_cursor:
                page = item
                break
            if cursor and page_cursor == cursor:
                page = item
                break
        if page is None:
            page = {"items": [], "next_cursor": None, "has_more": False}
        return {
            "kind": kind,
            "items": list(page.get("items") or []),
            "next_cursor": page.get("next_cursor"),
            "previous_cursor": page.get("previous_cursor"),
            "has_more": bool(page.get("has_more")),
        }

    def method_calls(self, name: str, user_id: str | None = None) -> list[tuple[object, ...]]:
        rows = [row for row in self.calls if row and row[0] == name]
        if user_id is None:
            return rows
        return [row for row in rows if user_id in row]


class FakeJudge:
    def __init__(
        self,
        mapping: dict[str, object] | None = None,
        default: object | None = None,
    ) -> None:
        self.mapping = mapping or {}
        self.default = default if default is not None else {
            "matches_criteria": True,
            "need_tweets": False,
            "confidence": 0.9,
            "summary": "ok",
            "reasons": ["ok"],
        }
        self.calls: list[dict[str, object]] = []

    def __call__(self, account: dict, **kwargs: object) -> dict:
        self.calls.append({"account": dict(account), "kwargs": dict(kwargs)})
        key = str(account.get("username") or account.get("id") or "")
        result = self.mapping.get(key, self.default)
        if isinstance(result, Exception):
            raise result
        if not isinstance(result, dict):
            raise AssertionError("invalid fake judge result")
        return dict(result)


class TwitterDiscoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "twitter-discover-state.jsonl"
        self.err = StringIO()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, client: FakeClient, judge: FakeJudge | None = None, **kwargs: object) -> dict:
        params: dict[str, object] = {
            "seeds": ("following", "followers"),
            "state_path": self.state,
            "criteria": DEFAULT_CRITERIA,
            "gemini_base_url": "https://example.com",
            "gemini_api_key": "test-key",
            "judge_account": judge or FakeJudge(),
            "err": self.err,
        }
        params.update(kwargs)
        return run_discover(client, **params)  # type: ignore[arg-type]

    def _write_state(self, rows: list[dict[str, object]]) -> None:
        self.state.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    def _events(self) -> list[dict[str, object]]:
        if not self.state.is_file():
            return []
        rows: list[dict[str, object]] = []
        for line in self.state.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def test_parser_marks_discover_as_workflow(self) -> None:
        parser = cli._parser()
        args = parser.parse_args(["discover", "--dry-run"])
        self.assertEqual(args._command_level, "workflow")
        self.assertIn("discover", cli._BROWSER_COMMANDS)
        subparsers = next(
            action
            for action in parser._actions
            if getattr(action, "choices", None) and "discover" in action.choices
        )
        command_help = next(
            action.help
            for action in subparsers._choices_actions
            if action.dest == "discover"
        )
        self.assertIn("Chrome 登录态临时传输", command_help)
        self.assertIn("不自动关注", command_help)
        self.assertEqual(
            parser.parse_args(["discover", "--pages", "1", "--dry-run"]).max_seed_pages,
            1,
        )
        self.assertEqual(
            parser.parse_args(
                ["discover", "--expand-pages", "3", "--dry-run"]
            ).max_expand_pages,
            3,
        )
        csv_args = parser.parse_args(["discover", "--csv", "--dry-run"])
        self.assertEqual(csv_args.csv.name, "twitter-discover.csv")
        self.assertEqual(
            parser.parse_args(["discover", "--dry-run"]).gemini_concurrency,
            1,
        )
        self.assertEqual(
            parser.parse_args(
                ["discover", "--gemini-concurrency", "20", "--dry-run"]
            ).gemini_concurrency,
            20,
        )

    def test_resume_after_skip_not_blue_does_not_rejudge(self) -> None:
        client = FakeClient()
        user = make_user("1", "plain", blue=False)
        client.following["me"] = [{"items": [user], "next_cursor": None, "has_more": False}]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        judge = FakeJudge()
        first = self._run(client, judge)
        self.assertEqual(first["stats"]["skipped"]["not_blue"], 1)
        self.assertEqual(judge.calls, [])
        calls_after_first = list(client.calls)
        second = self._run(client, judge)
        self.assertEqual(client.calls, calls_after_first)
        self.assertEqual(judge.calls, [])
        self.assertFalse(any(row[0] == "follow" for row in client.calls))
        self.assertIn("not_blue", {event.get("reason") for event in self._events() if event.get("type") == "skip"})
        self.assertEqual(second["stopped_reason"], "completed")

    def test_resume_retries_llm_failed(self) -> None:
        user = make_user("77", "retry_llm")
        self._write_state(
            [
                {
                    "type": "meta",
                    "started_at": "2026-09-08T00:00:00+00:00",
                    "seeds": ["following:me"],
                    "criteria": DEFAULT_CRITERIA,
                },
                {
                    "type": "queued",
                    "id": "77",
                    "list": "following",
                    "subject_id": "me",
                    "depth": 0,
                    "source_seed": "following:me",
                    "user": user,
                },
                {
                    "type": "cursor",
                    "list": "following",
                    "subject_id": "me",
                    "page": 1,
                    "cursor": None,
                    "exhausted": True,
                },
                {
                    "type": "skip",
                    "id": "77",
                    "reason": "llm_failed",
                    "detail": "Gemini 判定结果无法解析",
                },
            ]
        )
        client = FakeClient()
        client.add_user(user)
        judge = FakeJudge()
        result = self._run(client, judge, max_expand_users=0)
        self.assertEqual(len(judge.calls), 1)
        self.assertEqual(result["items"][0]["id"], "77")

    def test_exhausted_list_still_judges_queued_ids(self) -> None:
        user = make_user("222", "queued_dev")
        self._write_state(
            [
                {
                    "type": "meta",
                    "started_at": "2026-09-08T00:00:00+00:00",
                    "seeds": ["following:me", "followers:me"],
                    "criteria": DEFAULT_CRITERIA,
                },
                {
                    "type": "queued",
                    "id": "222",
                    "list": "following",
                    "subject_id": "me",
                    "depth": 0,
                    "source_seed": "following:me",
                    "user": user,
                },
                {
                    "type": "cursor",
                    "list": "following",
                    "subject_id": "me",
                    "page": 2,
                    "cursor": "CURSOR",
                    "exhausted": True,
                },
                {
                    "type": "cursor",
                    "list": "followers",
                    "subject_id": "me",
                    "page": 1,
                    "cursor": None,
                    "exhausted": True,
                },
            ]
        )
        client = FakeClient()
        client.add_user(user)
        judge = FakeJudge()
        result = self._run(client, judge, max_expand_users=0)
        self.assertEqual([call["account"]["username"] for call in judge.calls], ["queued_dev"])
        self.assertEqual(client.method_calls("get_following"), [])
        self.assertEqual(client.method_calls("get_followers"), [])
        self.assertEqual(result["stats"]["hits"], 1)
        self.assertEqual(result["items"][0]["id"], "222")

    def test_resume_after_bio_need_tweets_runs_judge2(self) -> None:
        user = make_user("444", "tweet_dev")
        self._write_state(
            [
                {
                    "type": "meta",
                    "started_at": "2026-09-08T00:00:00+00:00",
                    "seeds": ["following:me"],
                    "criteria": DEFAULT_CRITERIA,
                },
                {
                    "type": "queued",
                    "id": "444",
                    "list": "following",
                    "subject_id": "me",
                    "depth": 0,
                    "source_seed": "following:me",
                    "user": user,
                },
                {
                    "type": "cursor",
                    "list": "following",
                    "subject_id": "me",
                    "page": 1,
                    "cursor": None,
                    "exhausted": True,
                },
                {
                    "type": "cursor",
                    "list": "followers",
                    "subject_id": "me",
                    "page": 1,
                    "cursor": None,
                    "exhausted": True,
                },
                {
                    "type": "llm",
                    "id": "444",
                    "stage": "bio",
                    "need_tweets": True,
                    "matches_criteria": None,
                },
            ]
        )
        client = FakeClient()
        client.add_user(user)
        client.tweets["444"] = [{"text": "shipping a local model router"}]
        judge = FakeJudge(
            {
                "tweet_dev": {
                    "matches_criteria": True,
                    "need_tweets": False,
                    "confidence": 0.8,
                    "summary": "from tweets",
                    "reasons": ["tweets"],
                }
            }
        )
        result = self._run(client, judge)
        self.assertEqual(len(judge.calls), 1)
        self.assertEqual(judge.calls[0]["account"]["tweets"], [{"text": "shipping a local model router"}])
        self.assertEqual(len(client.method_calls("get_user_tweets")), 1)
        self.assertEqual(result["items"][0]["judged_from"], "bio+tweets")
        self.assertEqual(
            [event.get("stage") for event in self._events() if event.get("type") == "llm"],
            ["bio", "tweets"],
        )

    def test_max_llm_calls_counts_bio_and_tweets_separately(self) -> None:
        client = FakeClient()
        user = make_user("9", "need_more")
        client.following["me"] = [{"items": [user], "next_cursor": None, "has_more": False}]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        client.tweets["9"] = [{"text": "later"}]
        judge = FakeJudge(
            default={
                "matches_criteria": True,
                "need_tweets": True,
                "confidence": 0.5,
                "summary": "need tweets",
                "reasons": ["bio weak"],
            }
        )
        result = self._run(client, judge, max_llm_calls=1)
        self.assertEqual(result["stopped_reason"], "max_llm_calls")
        self.assertEqual(result["stats"]["llm_calls"], 1)
        self.assertEqual(client.method_calls("get_user_tweets"), [])
        self.assertEqual(len(judge.calls), 1)
        self.assertEqual(judge.calls[0]["account"]["tweets"], [])

    def test_resume_does_not_reexpand_hub(self) -> None:
        hub = make_user("444", "hubdev", followers=3000, following=3000)
        leaf = make_user("555", "leaf", blue=False, followers=3000, following=3000)
        client = FakeClient()
        client.following["me"] = [{"items": [hub], "next_cursor": None, "has_more": False}]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        client.following["444"] = [{"items": [leaf], "next_cursor": None, "has_more": False}]
        client.followers["444"] = [{"items": [], "next_cursor": None, "has_more": False}]
        judge = FakeJudge()
        first = self._run(client, judge)
        self.assertEqual(first["stats"]["hits"], 1)
        hub_list_calls = client.method_calls("get_following", "444") + client.method_calls(
            "get_followers", "444"
        )
        self.assertGreater(len(hub_list_calls), 0)
        second = self._run(client, judge)
        hub_list_calls_after = client.method_calls("get_following", "444") + client.method_calls(
            "get_followers", "444"
        )
        self.assertEqual(len(hub_list_calls_after), len(hub_list_calls))
        self.assertEqual(second["stats"]["hits"], 1)
        queued_hub_subjects = {
            event.get("subject_id")
            for event in self._events()
            if event.get("type") == "queued" and event.get("depth", 0) >= 1
        }
        self.assertEqual(queued_hub_subjects, {"444"})

    def test_only_mutual_blue_in_follower_range_expands(self) -> None:
        kol = make_user("10", "kol_ai", followers=88000, following=410)
        none = make_user("11", "builder", followers=5000, following=400)
        small = make_user("13", "tiny", followers=50, following=50)
        leaf = make_user("12", "leaf", blue=False)
        client = FakeClient()
        client.following["me"] = [
            {"items": [kol, none, small], "next_cursor": None, "has_more": False}
        ]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        client.following["10"] = [{"items": [leaf], "next_cursor": None, "has_more": False}]
        client.followers["10"] = [{"items": [], "next_cursor": None, "has_more": False}]
        client.following["11"] = [{"items": [], "next_cursor": None, "has_more": False}]
        client.followers["11"] = [{"items": [], "next_cursor": None, "has_more": False}]
        client.following["13"] = [{"items": [leaf], "next_cursor": None, "has_more": False}]
        client.followers["13"] = [{"items": [], "next_cursor": None, "has_more": False}]
        self._run(client, FakeJudge(), seeds=("following",))
        self.assertEqual(client.method_calls("get_following", "10"), [])
        self.assertEqual(client.method_calls("get_following", "11"), [])
        self.assertGreater(len(client.method_calls("get_following", "13")), 0)
        self.assertGreater(len(client.method_calls("get_followers", "13")), 0)

    def test_expand_before_remaining_seed_pages(self) -> None:
        hub = make_user("444", "hubdev", followers=3000, following=3000)
        later = make_user("9", "later_seed")
        leaf = make_user("555", "leaf", blue=False)
        client = FakeClient()
        client.following["me"] = [
            {"items": [hub], "next_cursor": "C2", "has_more": True},
            {"cursor": "C2", "items": [later], "next_cursor": None, "has_more": False},
        ]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        client.following["444"] = [{"items": [leaf], "next_cursor": None, "has_more": False}]
        client.followers["444"] = [{"items": [], "next_cursor": None, "has_more": False}]
        self._run(
            client,
            FakeJudge(),
            seeds=("following",),
            max_seed_pages=2,
        )
        following = client.method_calls("get_following")
        hub_at = next(
            index for index, row in enumerate(following) if "444" in row
        )
        seed_page2_at = next(
            index for index, row in enumerate(following) if row[3] == "C2"
        )
        self.assertLess(hub_at, seed_page2_at)

    def test_resume_expands_existing_hits_after_llm_budget(self) -> None:
        hub = make_user("444", "hubdev", followers=3000, following=3000)
        leaf = make_user("555", "leaf", blue=False, followers=3000, following=3000)
        self._write_state(
            [
                {
                    "type": "meta",
                    "started_at": "2026-09-08T00:00:00+00:00",
                    "seeds": ["following:me"],
                    "criteria": DEFAULT_CRITERIA,
                },
                {
                    "type": "queued",
                    "id": "444",
                    "list": "following",
                    "subject_id": "me",
                    "depth": 0,
                    "source_seed": "following:me",
                    "user": hub,
                },
                {
                    "type": "cursor",
                    "list": "following",
                    "subject_id": "me",
                    "page": 1,
                    "cursor": None,
                    "exhausted": True,
                },
                {
                    "type": "hit",
                    "id": "444",
                    "username": "hubdev",
                    "tag": "mutual_blue",
                    "followers": 3000,
                    "following": 3000,
                    "matches_criteria": True,
                    "source_seed": "following:me",
                    "judged_from": "bio",
                },
                {"type": "stop", "reason": "max_llm_calls"},
            ]
        )
        client = FakeClient()
        client.add_user(hub)
        client.following["444"] = [{"items": [leaf], "next_cursor": None, "has_more": False}]
        client.followers["444"] = [{"items": [], "next_cursor": None, "has_more": False}]
        self._run(client, FakeJudge(), seeds=("following",), max_expand_users=5)
        self.assertGreater(len(client.method_calls("get_following", "444")), 0)
        queued_subjects = {
            event.get("subject_id")
            for event in self._events()
            if event.get("type") == "queued" and event.get("depth", 0) >= 1
        }
        self.assertEqual(queued_subjects, {"444"})

    def test_not_matching_criteria_is_not_in_items(self) -> None:
        client = FakeClient()
        user = make_user("3", "offtopic")
        client.following["me"] = [{"items": [user], "next_cursor": None, "has_more": False}]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        judge = FakeJudge(
            default={
                "matches_criteria": False,
                "need_tweets": False,
                "confidence": 0.2,
                "summary": "no",
                "reasons": ["off"],
            }
        )
        result = self._run(client, judge)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["stats"]["skipped"]["not_criteria"], 1)

    def test_strong_bio_match_skips_user_tweets(self) -> None:
        client = FakeClient()
        user = make_user("4", "strong_bio")
        client.following["me"] = [{"items": [user], "next_cursor": None, "has_more": False}]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        judge = FakeJudge(
            default={
                "matches_criteria": True,
                "need_tweets": False,
                "confidence": 0.95,
                "summary": "bio enough",
                "reasons": ["bio"],
            }
        )
        result = self._run(client, judge)
        self.assertEqual(client.method_calls("get_user_tweets"), [])
        self.assertEqual(result["items"][0]["judged_from"], "bio")
        self.assertTrue(result["items"][0]["ai_related"])

    def test_rate_limited_list_stops_on_error_code(self) -> None:
        client = FakeClient()
        client.following_error = TwitterResponseError(
            "forbidden to continue right now",
            code="rate_limited",
        )
        result = self._run(client, FakeJudge())
        self.assertEqual(result["stopped_reason"], "rate_limited")
        self.assertTrue(result["stats"]["rate_limited"])
        self.assertIn("family_latched=true", self.err.getvalue())
        self.assertNotEqual(result["stopped_reason"], "forbidden")

    def test_today_suggested_only_mutual_blue_and_splits_batches(self) -> None:
        kol = make_user("10", "kol_ai", followers=88000, following=410)
        mutuals = [
            make_user(str(100 + index), f"mutual{index}", followers=150, following=150)
            for index in range(5)
        ]
        client = FakeClient()
        client.following["me"] = [
            {"items": [kol, *mutuals], "next_cursor": None, "has_more": False}
        ]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        result = self._run(client, FakeJudge(), max_expand_users=0, batch_size=2)
        item_ids = [item["id"] for item in result["items"]]
        self.assertIn("10", item_ids)
        self.assertEqual(result["items"][0]["tag"], "kol")
        suggested = result["today_suggested"]
        self.assertEqual(len(suggested["morning"]), 2)
        self.assertEqual(len(suggested["afternoon"]), 2)
        self.assertEqual(len(suggested["evening"]), 1)
        suggested_ids = [
            item["id"]
            for batch in ("morning", "afternoon", "evening")
            for item in suggested[batch]
        ]
        self.assertNotIn("10", suggested_ids)
        self.assertTrue(all(item["tag"] == "mutual_blue" for item in suggested["morning"]))
        self.assertTrue(all(item["matches_criteria"] for item in suggested["morning"]))

    def test_daily_budget_out_of_range_is_input_error(self) -> None:
        client = FakeClient()
        with self.assertRaises(TwitterInputError):
            self._run(client, dry_run=True, daily_budget=79)
        with self.assertRaises(TwitterInputError):
            self._run(client, dry_run=True, daily_budget=101)

    def test_dry_run_does_not_call_judge_or_tweets(self) -> None:
        client = FakeClient()
        user = make_user("8", "dry_user")
        client.following["me"] = [{"items": [user], "next_cursor": None, "has_more": False}]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]

        def boom_judge(*args: object, **kwargs: object) -> dict:
            raise AssertionError("dry-run 不得调用 judge")

        result = self._run(client, boom_judge, dry_run=True)
        self.assertEqual(result["stopped_reason"], "dry_run")
        self.assertEqual(client.method_calls("get_user_tweets"), [])
        self.assertEqual(result["items"][0]["judged_from"], "dry-run")
        self.assertFalse(result["items"][0]["matches_criteria"])
        self.assertFalse(
            any(event.get("type") in {"judged", "hit"} for event in self._events())
        )

    def test_gemini_unauthorized_stops_without_family_latch(self) -> None:
        client = FakeClient()
        user = make_user("7", "need_key")
        client.following["me"] = [{"items": [user], "next_cursor": None, "has_more": False}]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        judge = FakeJudge(
            default=TwitterResponseError(
                "forbidden by proxy",
                code="gemini_unauthorized",
            )
        )
        result = self._run(client, judge)
        self.assertEqual(result["stopped_reason"], "gemini_unauthorized")
        self.assertNotEqual(result["stopped_reason"], "forbidden")
        self.assertNotIn("family_latched=true", self.err.getvalue())
        self.assertIn("stopped=gemini_unauthorized", self.err.getvalue())

    def test_pages_must_be_positive(self) -> None:
        client = FakeClient()
        with self.assertRaises(TwitterInputError):
            self._run(client, dry_run=True, max_seed_pages=0)
        with self.assertRaises(TwitterInputError):
            self._run(client, dry_run=True, max_expand_pages=0)

    def test_following_seed_marks_followed_by_me(self) -> None:
        client = FakeClient()
        user = make_user("8", "dry_user")
        client.following["me"] = [{"items": [user], "next_cursor": None, "has_more": False}]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        result = self._run(client, dry_run=True)
        self.assertTrue(result["items"][0]["followed_by_me"])

    def test_explicit_followed_by_me_false_is_kept(self) -> None:
        client = FakeClient()
        user = make_user("21", "not_followed", followed_by_me=False)
        client.followers["me"] = [{"items": [user], "next_cursor": None, "has_more": False}]
        client.following["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        result = self._run(client, FakeJudge(), max_expand_users=0, seeds=("followers",))
        self.assertFalse(result["items"][0]["followed_by_me"])

    def test_csv_export_has_homepage_follow_tag_counts_and_summary(self) -> None:
        client = FakeClient()
        user = make_user("8", "dry_user")
        client.following["me"] = [{"items": [user], "next_cursor": None, "has_more": False}]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        path = Path(self.tmp.name) / "out.csv"
        self._run(client, dry_run=True, csv_path=path)
        self.assertTrue(path.is_file())
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(
            rows[0],
            ["主页链接", "我是否关注", "标签", "粉丝数", "关注数", "AI判断总结"],
        )
        self.assertEqual(rows[1][0], "https://x.com/dry_user")
        self.assertEqual(rows[1][1], "是")
        self.assertEqual(rows[1][2], "mutual_blue")
        self.assertEqual(rows[1][3], "3000")
        self.assertEqual(rows[1][4], "3000")

    def test_second_run_budget_skips_terminal_and_does_not_refetch_lists(self) -> None:
        first = make_user("1", "first_hit")
        second = make_user("2", "second_hit")
        client = FakeClient()
        client.following["me"] = [
            {"items": [first, second], "next_cursor": None, "has_more": False}
        ]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        judge = FakeJudge()
        first_run = self._run(
            client, judge, max_candidates=1, max_expand_users=0, seeds=("following",)
        )
        self.assertEqual([call["account"]["username"] for call in judge.calls], ["first_hit"])
        list_calls = len(client.method_calls("get_following"))
        second_run = self._run(
            client, judge, max_candidates=1, max_expand_users=0, seeds=("following",)
        )
        self.assertEqual(
            [call["account"]["username"] for call in judge.calls],
            ["first_hit", "second_hit"],
        )
        self.assertEqual(len(client.method_calls("get_following")), list_calls)
        self.assertEqual(first_run["stats"]["hits"], 1)
        self.assertEqual(second_run["stats"]["hits"], 2)

    def test_resume_higher_pages_does_not_refetch_page_one(self) -> None:
        page_one = make_user("1", "page_one")
        page_two = make_user("2", "page_two")
        client = FakeClient()
        client.following["me"] = [
            {"items": [page_one], "next_cursor": "C2", "has_more": True},
            {"cursor": "C2", "items": [page_two], "next_cursor": None, "has_more": False},
        ]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        self._run(
            client,
            dry_run=True,
            max_seed_pages=1,
            max_expand_users=0,
            seeds=("following",),
        )
        self.assertEqual(len(client.method_calls("get_following")), 1)
        self._run(
            client,
            dry_run=True,
            max_seed_pages=2,
            max_expand_users=0,
            seeds=("following",),
        )
        following_calls = client.method_calls("get_following")
        self.assertEqual(len(following_calls), 2)
        self.assertIsNone(following_calls[0][3])
        self.assertEqual(following_calls[1][3], "C2")

    def test_cached_profile_is_not_refetched(self) -> None:
        listed = make_user("9", "nodesc", description="")
        filled = make_user("9", "nodesc", description="now has bio")
        client = FakeClient()
        client.add_user(filled)
        client.following["me"] = [
            {"items": [listed], "next_cursor": None, "has_more": False}
        ]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        self._run(client, dry_run=True, max_expand_users=0, seeds=("following",))
        fetches = len(client.method_calls("get_user"))
        self.assertGreater(fetches, 0)
        self._run(client, dry_run=True, max_expand_users=0, seeds=("following",))
        self.assertEqual(len(client.method_calls("get_user")), fetches)

    def test_cached_tweets_are_not_refetched(self) -> None:
        user = make_user("444", "tweet_dev")
        self._write_state(
            [
                {
                    "type": "meta",
                    "started_at": "2026-09-08T00:00:00+00:00",
                    "seeds": ["following:me"],
                    "criteria": DEFAULT_CRITERIA,
                },
                {
                    "type": "queued",
                    "id": "444",
                    "list": "following",
                    "subject_id": "me",
                    "depth": 0,
                    "source_seed": "following:me",
                    "user": user,
                },
                {
                    "type": "cursor",
                    "list": "following",
                    "subject_id": "me",
                    "page": 1,
                    "cursor": None,
                    "exhausted": True,
                },
                {
                    "type": "cursor",
                    "list": "followers",
                    "subject_id": "me",
                    "page": 1,
                    "cursor": None,
                    "exhausted": True,
                },
                {
                    "type": "llm",
                    "id": "444",
                    "stage": "bio",
                    "need_tweets": True,
                    "matches_criteria": None,
                },
                {
                    "type": "tweets",
                    "id": "444",
                    "tweets": [{"text": "cached tweet"}],
                },
            ]
        )
        client = FakeClient()
        client.add_user(user)
        client.tweets["444"] = [{"text": "network tweet"}]
        judge = FakeJudge(
            {
                "tweet_dev": {
                    "matches_criteria": True,
                    "need_tweets": False,
                    "confidence": 0.8,
                    "summary": "from cache",
                    "reasons": ["cached"],
                }
            }
        )
        result = self._run(client, judge, max_expand_users=0)
        self.assertEqual(client.method_calls("get_user_tweets"), [])
        self.assertEqual(
            judge.calls[0]["account"]["tweets"],
            [{"text": "cached tweet"}],
        )
        self.assertEqual(result["items"][0]["judged_from"], "bio+tweets")

    def test_judge_before_next_seed_page(self) -> None:
        first = make_user("1", "one")
        second = make_user("2", "two")
        client = FakeClient()
        client.following["me"] = [
            {"items": [first], "next_cursor": "C2", "has_more": True},
            {"cursor": "C2", "items": [second], "next_cursor": None, "has_more": False},
        ]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        following_when_judged: list[int] = []

        def judge(account: dict, **kwargs: object) -> dict:
            following_when_judged.append(len(client.method_calls("get_following")))
            return {
                "matches_criteria": True,
                "need_tweets": False,
                "confidence": 0.9,
                "summary": "ok",
                "reasons": ["ok"],
            }

        result = self._run(
            client,
            judge,  # type: ignore[arg-type]
            max_expand_users=0,
            seeds=("following",),
            max_seed_pages=2,
        )
        self.assertEqual(following_when_judged, [1, 2])
        self.assertEqual([item["id"] for item in result["items"]], ["1", "2"])

    def test_expand_waits_until_current_queue_judged(self) -> None:
        hub = make_user("444", "hubdev", followers=3000, following=3000)
        other = make_user("446", "other")
        leaf = make_user("555", "leaf", blue=False, followers=3000, following=3000)
        client = FakeClient()
        client.following["me"] = [
            {"items": [hub, other], "next_cursor": None, "has_more": False}
        ]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        client.following["444"] = [{"items": [leaf], "next_cursor": None, "has_more": False}]
        client.followers["444"] = [{"items": [], "next_cursor": None, "has_more": False}]
        judged_before_hub_lists: list[str] = []

        def judge(account: dict, **kwargs: object) -> dict:
            if not client.method_calls("get_following", "444"):
                judged_before_hub_lists.append(str(account.get("username") or ""))
            return {
                "matches_criteria": True,
                "need_tweets": False,
                "confidence": 0.9,
                "summary": "ok",
                "reasons": ["ok"],
            }

        result = self._run(client, judge)  # type: ignore[arg-type]
        self.assertEqual(judged_before_hub_lists, ["hubdev", "other"])
        self.assertGreater(len(client.method_calls("get_following", "444")), 0)
        self.assertEqual({item["id"] for item in result["items"]}, {"444", "446"})

    def test_gemini_concurrency_judges_two_users(self) -> None:
        first = make_user("1", "one")
        second = make_user("2", "two")
        client = FakeClient()
        client.following["me"] = [
            {"items": [first, second], "next_cursor": None, "has_more": False}
        ]
        client.followers["me"] = [{"items": [], "next_cursor": None, "has_more": False}]
        judge = FakeJudge()
        result = self._run(
            client,
            judge,
            max_expand_users=0,
            seeds=("following",),
            gemini_concurrency=20,
        )
        self.assertEqual(
            {call["account"]["username"] for call in judge.calls},
            {"one", "two"},
        )
        self.assertEqual({item["id"] for item in result["items"]}, {"1", "2"})

    def test_cached_llm_is_not_sent_again(self) -> None:
        user = make_user("10", "cached_llm")
        self._write_state(
            [
                {
                    "type": "meta",
                    "started_at": "2026-09-08T00:00:00+00:00",
                    "seeds": ["following:me"],
                    "criteria": DEFAULT_CRITERIA,
                },
                {
                    "type": "queued",
                    "id": "10",
                    "list": "following",
                    "subject_id": "me",
                    "depth": 0,
                    "source_seed": "following:me",
                    "user": user,
                },
                {
                    "type": "cursor",
                    "list": "following",
                    "subject_id": "me",
                    "page": 1,
                    "cursor": None,
                    "exhausted": True,
                },
                {
                    "type": "cursor",
                    "list": "followers",
                    "subject_id": "me",
                    "page": 1,
                    "cursor": None,
                    "exhausted": True,
                },
                {
                    "type": "llm",
                    "id": "10",
                    "stage": "bio",
                    "need_tweets": False,
                    "matches_criteria": True,
                    "summary": "already judged",
                    "confidence": 0.7,
                },
            ]
        )
        client = FakeClient()
        client.add_user(user)
        judge = FakeJudge()
        result = self._run(client, judge, max_expand_users=0)
        self.assertEqual(judge.calls, [])
        self.assertEqual(result["items"][0]["ai_summary"], "already judged")

    def test_dotenv_file_fills_missing_env_and_does_not_override(self) -> None:
        env_path = Path(self.tmp.name) / ".env"
        env_path.write_text(
            "GEMINI_BASE_URL=https://relay.example/v1\n"
            "GEMINI_API_KEY=from-file\n"
            "export UNUSED_FLAG=1\n",
            encoding="utf-8",
        )
        environ = {"GEMINI_API_KEY": "keep-existing"}
        cli._apply_dotenv(env_path, environ)
        self.assertEqual(environ["GEMINI_API_KEY"], "keep-existing")
        self.assertEqual(environ["GEMINI_BASE_URL"], "https://relay.example/v1")
        self.assertEqual(environ["UNUSED_FLAG"], "1")


if __name__ == "__main__":
    unittest.main()
