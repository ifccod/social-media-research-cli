from __future__ import annotations

import json
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.reddit_reverse.cli import _parser, _run
from reverse.reddit_reverse.client import DEFAULT_USER_AGENT, RedditClient
from reverse.reddit_reverse.errors import RedditError, RedditInputError, RedditRateLimited, RedditResponseError


PUBLIC_CAPABILITIES_FIXTURE = json.loads(
    (Path(__file__).with_name("fixtures") / "public_capabilities.json").read_text(
        encoding="utf-8"
    )
)
MORE_COMMENTS_FIXTURE = json.loads(
    (Path(__file__).with_name("fixtures") / "more_comments.json").read_text(
        encoding="utf-8"
    )
)


def response(
    payload: object | None = None,
    *,
    text: str | None = None,
    status: int = 200,
    url: str = "",
    headers: dict[str, str] | None = None,
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.content = (text if text is not None else json.dumps(payload)).encode()
    result.default_encoding = "utf-8"
    if headers:
        result.headers.update(headers)
    return result


class FakeSession(requests.Session):
    def __init__(self, results: list[requests.Response | Exception]) -> None:
        super().__init__()
        self.results = deque(results)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> requests.Response:
        self.calls.append((url, kwargs))
        if not self.results:
            raise AssertionError(f"unexpected HTTP request: {url}")
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        if not result.url:
            result.url = url
        return result


def post_data(post_id: str, *, title: str | None = None) -> dict[str, object]:
    return {
        "id": post_id,
        "name": f"t3_{post_id}",
        "title": title or f"post {post_id}",
        "selftext": "fixture body",
        "permalink": f"/r/python/comments/{post_id}/fixture/",
        "url": f"https://www.reddit.com/r/python/comments/{post_id}/fixture/",
        "author": "fixture_user",
        "author_fullname": "t2_user",
        "subreddit": "python",
        "subreddit_id": "t5_python",
        "created_utc": 1_700_000_000.5,
        "score": 42,
        "upvote_ratio": 0.95,
        "num_comments": 3,
        "total_awards_received": 1,
        "is_self": True,
    }


def listing(
    children: list[dict[str, object]],
    *,
    after: object | None = None,
) -> dict[str, object]:
    return {"kind": "Listing", "data": {"after": after, "children": children}}


def post_child(post_id: str, *, title: str | None = None) -> dict[str, object]:
    return {"kind": "t3", "data": post_data(post_id, title=title)}


def comment_data(comment_id: str, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": comment_id,
        "name": f"t1_{comment_id}",
        "parent_id": "t3_post1",
        "link_id": "t3_post1",
        "author": "fixture_user",
        "author_fullname": "t2_user",
        "body": f"comment {comment_id}",
        "created_utc": 1_700_000_000.5,
        "score": 12,
        "subreddit": "python",
        "subreddit_id": "t5_python",
        "link_title": "Fixture post",
        "link_author": "post_author",
        "link_url": "https://example.test/post?x=1&amp;y=2",
        "permalink": f"/r/python/comments/post1/fixture/{comment_id}/",
        "replies": "",
    }
    data.update(overrides)
    return data


def comment_child(comment_id: str, **overrides: object) -> dict[str, object]:
    return {"kind": "t1", "data": comment_data(comment_id, **overrides)}


def morechildren(
    things: list[object], *, errors: list[object] | None = None
) -> dict[str, object]:
    return {
        "json": {
            "errors": [] if errors is None else errors,
            "data": {"things": things},
        }
    }


def tree_summary(comments: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "id": comment["id"],
            "replies": tree_summary(comment["replies"]),  # type: ignore[arg-type]
        }
        for comment in comments
    ]


class RedditClientTest(unittest.TestCase):
    def test_shared_public_capabilities_fixture_matches_full_contract(self) -> None:
        comments_fixture = PUBLIC_CAPABILITIES_FIXTURE["user_comments"]
        comments_client = RedditClient(
            session=FakeSession(
                [response(text="identity")]
                + [response(page) for page in comments_fixture["pages"]]
            ),
            retries=0,
        )
        comments = comments_client.get_user_comments(
            comments_fixture["target"], **comments_fixture["options"]
        )
        self.assertEqual(comments, comments_fixture["expected"])

        info_fixture = PUBLIC_CAPABILITIES_FIXTURE["subreddit_info"]
        info_client = RedditClient(
            session=FakeSession(
                [response(text="identity"), response(info_fixture["response"])]
            ),
            retries=0,
        )
        self.assertEqual(
            info_client.get_subreddit_info(info_fixture["target"]),
            info_fixture["expected"],
        )

        rules_fixture = PUBLIC_CAPABILITIES_FIXTURE["subreddit_rules"]
        rules_client = RedditClient(
            session=FakeSession(
                [response(text="identity"), response(rules_fixture["response"])]
            ),
            retries=0,
        )
        self.assertEqual(
            rules_client.get_subreddit_rules(rules_fixture["target"]),
            rules_fixture["expected"],
        )

        trophies_fixture = PUBLIC_CAPABILITIES_FIXTURE["user_trophies"]
        trophies_client = RedditClient(
            session=FakeSession(
                [response(text="identity"), response(trophies_fixture["response"])]
            ),
            retries=0,
        )
        self.assertEqual(
            trophies_client.get_user_trophies(trophies_fixture["target"]),
            trophies_fixture["expected"],
        )

        settings_fixture = PUBLIC_CAPABILITIES_FIXTURE["subreddit_settings"]
        settings_client = RedditClient(
            session=FakeSession(
                [response(text="identity"), response(settings_fixture["response"])]
            ),
            retries=0,
        )
        self.assertEqual(
            settings_client.get_subreddit_settings(settings_fixture["target"]),
            settings_fixture["expected"],
        )

        typeahead_fixture = PUBLIC_CAPABILITIES_FIXTURE["typeahead"]
        typeahead_client = RedditClient(
            session=FakeSession(
                [response(text="identity"), response(typeahead_fixture["response"])]
            ),
            retries=0,
        )
        self.assertEqual(
            typeahead_client.typeahead(
                typeahead_fixture["target"], **typeahead_fixture["options"]
            ),
            typeahead_fixture["expected"],
        )

    def test_error_hierarchy_and_inputs_are_strict(self) -> None:
        self.assertTrue(issubclass(RedditInputError, RedditError))
        self.assertTrue(issubclass(RedditResponseError, RedditError))
        client = RedditClient(session=FakeSession([]), retries=0)

        self.assertEqual(client.resolve_subreddit("r/python"), "python")
        self.assertEqual(
            client.resolve_subreddit("https://www.reddit.com/r/Python/"), "Python"
        )
        self.assertEqual(client.resolve_username("u/test-user"), "test-user")
        self.assertEqual(client.resolve_post_id("https://redd.it/AbC123"), "abc123")
        self.assertEqual(
            client.resolve_post_id(
                "https://www.reddit.com/r/python/comments/AbC123/title/"
            ),
            "abc123",
        )
        with self.assertRaises(RedditInputError):
            client.resolve_subreddit("https://reddit.com.example/r/python")
        with self.assertRaises(RedditInputError):
            client.resolve_username("https://example.com/user/name")
        with self.assertRaises(RedditInputError):
            client.resolve_post_id("https://reddit.com/r/python")
        with self.assertRaises(RedditInputError):
            client.get_subreddit("python", sort="best")
        with self.assertRaises(RedditInputError):
            client.search("", limit=1)
        with self.assertRaises(RedditInputError):
            client.get_user_posts("name", after="bad")
        with self.assertRaises(RedditInputError):
            client.get_user_comments("name", after="t3_wrong")
        with self.assertRaises(RedditInputError):
            client.get_user_comments("name", sort="rising")
        with self.assertRaises(RedditInputError):
            client.get_user_comments("name", time_filter="decade")
        with self.assertRaises(RedditInputError):
            client.get_subreddit_info("https://example.com/r/python")

        result = client.get_subreddit("python", limit=0)
        self.assertEqual(result["posts"], [])
        comments = client.get_user_comments("name", limit=0, after="t1_start")
        self.assertEqual(comments["comments"], [])
        self.assertEqual(comments["after"], "t1_start")
        self.assertFalse(comments["has_more"])
        self.assertEqual(client.session.calls, [])  # type: ignore[attr-defined]

    def test_visitor_bootstrap_precedes_json_and_is_reused(self) -> None:
        session = FakeSession(
            [
                response(text="visitor cookies"),
                response(listing([post_child("abc123")], after=None)),
                response(listing([post_child("def456")], after=None)),
            ]
        )
        client = RedditClient(session=session, retries=0)

        first = client.get_subreddit("python", limit=1)
        second = client.get_subreddit("python", sort="new", limit=1)

        self.assertEqual(first["posts"][0]["title"], "post abc123")
        self.assertEqual(second["posts"][0]["id"], "def456")
        self.assertEqual(session.calls[0][0], "https://old.reddit.com/")
        self.assertEqual(session.calls[1][0], "https://www.reddit.com/r/python/hot/.json")
        self.assertEqual(session.calls[2][0], "https://www.reddit.com/r/python/new/.json")
        self.assertEqual(session.calls[1][1]["params"]["raw_json"], "1")
        self.assertEqual(session.calls[1][1]["params"]["limit"], 1)
        self.assertEqual(
            session.calls[1][1]["headers"],
            {
                "Referer": "https://www.reddit.com/",
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": DEFAULT_USER_AGENT,
            },
        )

    def test_bootstrap_403_does_not_skip_target_and_retains_both_bodies(self) -> None:
        target = listing([post_child("abc123")], after=None)
        session = FakeSession(
            [
                response(text="bootstrap blocked", status=403),
                response(target),
            ]
        )
        fetches: list[dict[str, object]] = []
        client = RedditClient(
            session=session,
            retries=0,
            on_fetch=fetches.append,
        )

        result = client.search("api relay")

        self.assertEqual(result["posts"][0]["id"], "abc123")
        self.assertEqual(
            [url for url, _ in session.calls],
            [
                "https://old.reddit.com/",
                "https://www.reddit.com/search/.json",
            ],
        )
        self.assertEqual([item["status_code"] for item in fetches], [403, 200])
        self.assertEqual(fetches[0]["response_text"], "bootstrap blocked")
        self.assertEqual(json.loads(str(fetches[1]["response_text"]))["data"]["children"][0]["data"]["id"], "abc123")

    def test_target_403_forces_same_session_bootstrap_then_retries_once(self) -> None:
        session = FakeSession(
            [
                response(text="identity"),
                response(text="target blocked", status=403),
                response(text="refreshed identity"),
                response(
                    [
                        listing([post_child("def456")], after=None),
                        listing([], after=None),
                    ]
                ),
            ]
        )
        fetches: list[dict[str, object]] = []
        client = RedditClient(session=session, retries=0, on_fetch=fetches.append)

        result = client.get_post("def456", comment_limit=1)

        self.assertEqual(result["post"]["id"], "def456")
        self.assertEqual(
            [url for url, _ in session.calls],
            [
                "https://old.reddit.com/",
                "https://www.reddit.com/comments/def456/.json",
                "https://old.reddit.com/",
                "https://www.reddit.com/comments/def456/.json",
            ],
        )
        self.assertEqual([item["status_code"] for item in fetches], [200, 403, 200, 200])

    def test_rate_limit_records_retry_after_without_retrying_or_sending_next_call(self) -> None:
        session = FakeSession(
            [
                response(text="identity"),
                response(
                    text="rate limited",
                    status=429,
                    headers={"Retry-After": "120"},
                ),
            ]
        )
        fetches: list[dict[str, object]] = []
        client = RedditClient(session=session, retries=2, on_fetch=fetches.append)

        with patch("reverse.reddit_reverse.client.time.sleep") as sleep:
            with self.assertRaisesRegex(RedditRateLimited, "retry after 120s") as raised:
                client.search("api relay")
            with self.assertRaises(RedditRateLimited):
                client.get_post("def456", comment_limit=1)

        sleep.assert_not_called()
        self.assertEqual(raised.exception.retry_after_seconds, 120)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual([item["status_code"] for item in fetches], [200, 429])
        self.assertEqual(fetches[-1]["retry_after_seconds"], 120)

    def test_proxy_is_explicit_per_request_and_redacted_from_records_and_errors(self) -> None:
        proxy = "socks5h://fixture-user:fixture-secret@proxy.example.test:1000"

        class FailingSession:
            def __init__(self) -> None:
                self.headers: dict[str, str] = {}
                self.calls: list[dict[str, object]] = []

            def get(self, _url: str, **kwargs: object) -> requests.Response:
                self.calls.append(kwargs)
                raise RuntimeError(f"connection failed through {proxy}")

        session = FailingSession()
        fetches: list[dict[str, object]] = []
        with patch.dict(
            "os.environ",
            {
                "REDDIT_OPPORTUNITY_PROXY": proxy,
                "HTTP_PROXY": "http://generic-proxy.example.test:8080",
            },
            clear=True,
        ):
            client = RedditClient(
                session=session,  # type: ignore[arg-type]
                retries=0,
                on_fetch=fetches.append,
            )

            with self.assertRaisesRegex(RedditResponseError, "configured-proxy") as raised:
                client.search("api relay")

        self.assertEqual(len(fetches), 2)
        self.assertEqual([call["proxy"] for call in session.calls], [proxy, proxy])
        self.assertTrue(all(item["error"] for item in fetches))
        self.assertTrue(all(proxy not in str(item["error"]) for item in fetches))
        self.assertTrue(all("fixture-secret" not in str(item["error"]) for item in fetches))
        self.assertNotIn(proxy, str(raised.exception))

    def test_listing_paginates_deduplicates_and_advances_after(self) -> None:
        session = FakeSession(
            [
                response(text="identity"),
                response(
                    listing(
                        [post_child("aaa111"), post_child("bbb222")],
                        after="t3_bbb222",
                    )
                ),
                response(
                    listing(
                        [post_child("bbb222"), post_child("ccc333")],
                        after=None,
                    )
                ),
            ]
        )
        client = RedditClient(session=session, retries=0)

        result = client.get_subreddit("python", limit=3)

        self.assertEqual(
            [item["id"] for item in result["posts"]],
            ["aaa111", "bbb222", "ccc333"],
        )
        self.assertFalse(result["has_more"])
        self.assertEqual(session.calls[2][1]["params"]["after"], "t3_bbb222")

    def test_listing_rejects_a_non_advancing_cursor(self) -> None:
        session = FakeSession(
            [
                response(text="identity"),
                response(listing([post_child("aaa111")], after="t3_same")),
            ]
        )
        client = RedditClient(session=session, retries=0)

        with self.assertRaisesRegex(RedditResponseError, "did not advance"):
            client.get_subreddit("python", limit=2, after="t3_same")

    def test_listing_rejects_non_string_response_cursors(self) -> None:
        for invalid_cursor in ({}, [], 0, 1, False, True, 1.5):
            with self.subTest(cursor=invalid_cursor):
                session = FakeSession(
                    [
                        response(text="identity"),
                        response(listing([], after=invalid_cursor)),
                    ]
                )
                client = RedditClient(session=session, retries=0)

                with self.assertRaisesRegex(
                    RedditResponseError, "must be a string or null"
                ):
                    client.get_subreddit("python", limit=1)

    def test_listing_normalizes_blank_input_and_response_cursors(self) -> None:
        session = FakeSession(
            [
                response(text="identity"),
                response(listing([post_child("aaa111")], after=" \t\n ")),
            ]
        )
        client = RedditClient(session=session, retries=0)

        result = client.get_subreddit("python", limit=2, after=" \t ")

        self.assertEqual(result["total"], 1)
        self.assertIsNone(result["after"])
        self.assertFalse(result["has_more"])
        self.assertNotIn("after", session.calls[1][1]["params"])

    def test_user_comments_paginate_t1_and_normalize_listing_context(self) -> None:
        first_comment = comment_child(
            "aaa111",
            author="[deleted]",
            author_fullname=None,
            permalink="/r/python/comments/post1/fixture/aaa111/?x=1&amp;y=2",
        )
        missing_fields = comment_child(
            "ccc333",
            author=None,
            body=None,
            created_utc=None,
            score=None,
            subreddit=None,
            subreddit_id=None,
            link_title=None,
            link_author=None,
            link_url=None,
            permalink=None,
        )
        session = FakeSession(
            [
                response(text="identity"),
                response(
                    listing(
                        [first_comment, comment_child("bbb222")],
                        after="t1_bbb222",
                    )
                ),
                response(
                    listing(
                        [comment_child("bbb222"), post_child("ignored"), missing_fields],
                        after=None,
                    )
                ),
            ]
        )
        client = RedditClient(session=session, retries=0)

        result = client.get_user_comments(
            "https://www.reddit.com/u/fixture-user/",
            sort="TOP",
            time_filter="YEAR",
            limit=3,
        )

        self.assertEqual(result["username"], "fixture-user")
        self.assertEqual(result["sort"], "top")
        self.assertEqual(result["time_filter"], "year")
        self.assertEqual(result["total"], 3)
        self.assertIsNone(result["after"])
        self.assertFalse(result["has_more"])
        self.assertEqual(
            [item["id"] for item in result["comments"]],
            ["aaa111", "bbb222", "ccc333"],
        )

        deleted = result["comments"][0]
        self.assertEqual(deleted["author"], "[deleted]")
        self.assertEqual(deleted["fullname"], "t1_aaa111")
        self.assertEqual(deleted["name"], "t1_aaa111")
        self.assertEqual(deleted["text"], "comment aaa111")
        self.assertEqual(deleted["body"], "comment aaa111")
        self.assertEqual(
            deleted["url"],
            "https://www.reddit.com/r/python/comments/post1/fixture/aaa111/?x=1&y=2",
        )
        self.assertEqual(deleted["link_url"], "https://example.test/post?x=1&y=2")

        empty = result["comments"][2]
        self.assertEqual(empty["author"], "")
        self.assertEqual(empty["body"], "")
        self.assertEqual(empty["created_utc"], 0)
        self.assertEqual(empty["score"], 0)
        self.assertEqual(empty["url"], "")
        self.assertEqual(empty["replies"], [])
        self.assertEqual(empty["more_reply_ids"], [])

        self.assertEqual(
            session.calls[1][0],
            "https://www.reddit.com/user/fixture-user/comments/.json",
        )
        self.assertEqual(session.calls[1][1]["params"]["sort"], "top")
        self.assertEqual(session.calls[1][1]["params"]["t"], "year")
        self.assertEqual(session.calls[2][1]["params"]["after"], "t1_bbb222")

    def test_user_comments_reject_a_non_advancing_t1_cursor(self) -> None:
        session = FakeSession(
            [
                response(text="identity"),
                response(listing([comment_child("aaa111")], after="t1_same")),
            ]
        )
        client = RedditClient(session=session, retries=0)

        with self.assertRaisesRegex(RedditResponseError, "did not advance"):
            client.get_user_comments("fixture", limit=2, after="t1_same")

    def test_user_comments_reject_a_cursor_cycle_at_the_exact_limit(self) -> None:
        session = FakeSession(
            [
                response(text="identity"),
                response(listing([comment_child("aaa111")], after="t1_page1")),
                response(listing([comment_child("aaa111")], after="t1_page2")),
                response(listing([comment_child("bbb222")], after="t1_page1")),
            ]
        )
        client = RedditClient(session=session, retries=0)

        with self.assertRaisesRegex(RedditResponseError, "repeated cursor t1_page1"):
            client.get_user_comments("fixture", limit=2)

    def test_forbidden_json_refreshes_visitor_identity_once(self) -> None:
        session = FakeSession(
            [
                response(text="first identity"),
                response(text="blocked", status=403),
                response(text="refreshed identity"),
                response(listing([post_child("abc123")], after=None)),
            ]
        )
        client = RedditClient(session=session, retries=0)

        result = client.get_subreddit("python", limit=1)

        self.assertEqual(result["posts"][0]["id"], "abc123")
        self.assertEqual(
            [url for url, _ in session.calls],
            [
                "https://old.reddit.com/",
                "https://www.reddit.com/r/python/hot/.json",
                "https://old.reddit.com/",
                "https://www.reddit.com/r/python/hot/.json",
            ],
        )

    def test_post_comments_and_media_are_normalized(self) -> None:
        raw_post = post_data("abc123")
        raw_post.update(
            {
                "is_video": True,
                "is_gallery": True,
                "preview": {
                    "images": [
                        {
                            "source": {
                                "url": "https://preview.test/a.jpg?x=1&amp;y=2",
                                "width": 100,
                                "height": 50,
                            },
                            "resolutions": [],
                        }
                    ]
                },
                "secure_media": {
                    "reddit_video": {
                        "fallback_url": "https://video.test/fallback.mp4?x=1&amp;y=2",
                        "hls_url": "https://video.test/hls.m3u8",
                        "width": 1920,
                        "height": 1080,
                        "duration": 12,
                        "has_audio": True,
                    }
                },
                "gallery_data": {
                    "items": [{"media_id": "media1", "caption": "gallery caption"}]
                },
                "media_metadata": {
                    "media1": {
                        "status": "valid",
                        "m": "image/jpg",
                        "s": {
                            "u": "https://gallery.test/a.jpg?x=1&amp;y=2",
                            "x": 800,
                            "y": 600,
                        },
                    }
                },
            }
        )
        nested_reply = {
            "kind": "t1",
            "data": {
                "id": "reply1",
                "name": "t1_reply1",
                "parent_id": "t1_root1",
                "link_id": "t3_abc123",
                "author": "reply_author",
                "body": "nested",
                "score": 2,
                "depth": 1,
                "replies": "",
            },
        }
        root_comment = {
            "kind": "t1",
            "data": {
                "id": "root1",
                "name": "t1_root1",
                "parent_id": "t3_abc123",
                "link_id": "t3_abc123",
                "author": "commenter",
                "body": "root",
                "score": 5,
                "depth": 0,
                "replies": listing([nested_reply]),
            },
        }
        more = {"kind": "more", "data": {"children": ["next1", "next2"]}}
        payload = [
            listing([{"kind": "t3", "data": raw_post}]),
            listing([root_comment, more]),
        ]
        session = FakeSession([response(text="identity"), response(payload)])
        client = RedditClient(session=session, retries=0)

        result = client.get_post("https://redd.it/abc123", comment_limit=10, depth=2)

        post = result["post"]
        self.assertEqual(post["images"][0]["source"]["url"], "https://preview.test/a.jpg?x=1&y=2")
        self.assertEqual(post["video"]["duration_seconds"], 12)
        self.assertTrue(post["video"]["has_audio"])
        self.assertEqual(post["gallery"][0]["source"]["url"], "https://gallery.test/a.jpg?x=1&y=2")
        self.assertEqual(result["comments"][0]["replies"][0]["id"], "reply1")
        self.assertEqual(result["more_comment_ids"], ["next1", "next2"])
        self.assertEqual(session.calls[1][1]["params"]["depth"], 2)

    def test_user_profile_and_search_contract(self) -> None:
        user_payload = {
            "kind": "t2",
            "data": {
                "id": "user1",
                "name": "fixture-user",
                "created_utc": 1_600_000_000,
                "comment_karma": 11,
                "link_karma": 22,
                "total_karma": 33,
                "subreddit": {
                    "title": "Fixture profile",
                    "public_description": "about fixture",
                    "icon_img": "https://avatar.test/a.png?x=1&amp;y=2",
                },
            },
        }
        session = FakeSession(
            [
                response(text="identity"),
                response(user_payload),
                response(listing([post_child("abc123")], after="t3_abc123")),
            ]
        )
        client = RedditClient(session=session, retries=0)

        user = client.get_user("u/fixture-user")
        search = client.search(
            "python typing",
            subreddit="python",
            sort="new",
            time_filter="week",
            limit=1,
        )

        self.assertEqual(user["total_karma"], 33)
        self.assertEqual(user["profile"]["icon"], "https://avatar.test/a.png?x=1&y=2")
        self.assertEqual(search["query"], "python typing")
        self.assertTrue(search["has_more"])
        url, options = session.calls[-1]
        self.assertEqual(url, "https://www.reddit.com/r/python/search/.json")
        self.assertEqual(options["params"]["restrict_sr"], "on")
        self.assertEqual(options["params"]["sort"], "new")

    def test_subreddit_info_normalizes_nulls_fallbacks_and_html_urls(self) -> None:
        payload = {
            "kind": "t5",
            "data": {
                "id": "2abc",
                "name": "t5_2abc",
                "title": None,
                "display_name": "Fixture",
                "description": None,
                "public_description": "Fixture public description",
                "subscribers": "12",
                "active_user_count": None,
                "accounts_active": "3",
                "over18": 1,
                "subreddit_type": None,
                "url": "/r/Fixture/?x=1&amp;y=2",
                "icon_img": "",
                "community_icon": "https://img.test/icon.png?x=1&amp;y=2",
                "banner_img": "",
                "banner_background_image": "https://img.test/banner.png?a=1&amp;b=2",
                "created_utc": None,
            },
        }
        minimal_payload = {
            "kind": "t5",
            "data": {"id": "minimal", "display_name": "Minimal"},
        }
        session = FakeSession(
            [
                response(text="identity"),
                response(payload),
                response(minimal_payload),
            ]
        )
        client = RedditClient(session=session, retries=0)

        result = client.get_subreddit_info("https://reddit.com/r/Fixture/")
        minimal = client.get_subreddit_info("r/Minimal")

        self.assertEqual(result["name"], "t5_2abc")
        self.assertEqual(result["id"], "2abc")
        self.assertEqual(result["display_name"], "Fixture")
        self.assertEqual(result["title"], "")
        self.assertEqual(result["description"], "")
        self.assertEqual(result["subscribers"], 12)
        self.assertEqual(result["active_users"], 3)
        self.assertTrue(result["over18"])
        self.assertEqual(result["subreddit_type"], "")
        self.assertEqual(
            result["url"], "https://www.reddit.com/r/Fixture/?x=1&y=2"
        )
        self.assertEqual(result["icon_url"], "https://img.test/icon.png?x=1&y=2")
        self.assertEqual(
            result["banner_url"], "https://img.test/banner.png?a=1&b=2"
        )
        self.assertEqual(result["created_utc"], 0)

        self.assertEqual(minimal["name"], "t5_minimal")
        self.assertEqual(minimal["title"], "")
        self.assertEqual(minimal["public_description"], "")
        self.assertEqual(minimal["url"], "https://www.reddit.com/r/Minimal/")
        self.assertEqual(minimal["icon_url"], "")
        self.assertEqual(minimal["banner_url"], "")
        self.assertEqual(minimal["active_users"], 0)

    def test_subreddit_rules_normalize_site_rules_and_missing_fields(self) -> None:
        payload = {
            "rules": [
                {
                    "kind": "all",
                    "short_name": "Be civil",
                    "description": "Fixture rule",
                    "violation_reason": "Incivility",
                    "created_utc": "1700000000.5",
                    "priority": "2",
                },
                {},
                None,
                "ignored",
            ],
            "site_rules": ["Spam", "", None, 7],
            "site_rules_flow": [],
        }
        session = FakeSession([response(text="identity"), response(payload)])
        client = RedditClient(session=session, retries=0)

        result = client.get_subreddit_rules("reddit.com/r/Python")

        self.assertEqual(result["subreddit"], "Python")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["site_rules"], ["Spam", "7"])
        self.assertEqual(
            result["rules"][0],
            {
                "kind": "all",
                "short_name": "Be civil",
                "description": "Fixture rule",
                "violation_reason": "Incivility",
                "created_utc": 1700000000.5,
                "priority": 2,
            },
        )
        self.assertEqual(
            result["rules"][1],
            {
                "kind": "",
                "short_name": "",
                "description": "",
                "violation_reason": "",
                "created_utc": 0,
                "priority": 0,
            },
        )
        self.assertEqual(
            session.calls[1][0],
            "https://www.reddit.com/r/Python/about/rules.json",
        )

    def test_trophies_settings_and_typeahead_use_strict_public_contracts(
        self,
    ) -> None:
        trophies_fixture = PUBLIC_CAPABILITIES_FIXTURE["user_trophies"]
        trophies_session = FakeSession(
            [response(text="identity"), response(trophies_fixture["response"])]
        )
        trophies_client = RedditClient(session=trophies_session, retries=0)
        trophies = trophies_client.get_user_trophies("u/fixture-user")
        self.assertEqual(trophies["trophies"][1]["granted_at"], None)
        self.assertEqual(
            trophies_session.calls[1][0],
            "https://www.reddit.com/user/fixture-user/trophies.json",
        )

        settings_fixture = PUBLIC_CAPABILITIES_FIXTURE["subreddit_settings"]
        settings_session = FakeSession(
            [response(text="identity"), response(settings_fixture["response"])]
        )
        settings_client = RedditClient(session=settings_session, retries=0)
        settings = settings_client.get_subreddit_settings("T5_2QH0Y")
        self.assertFalse(settings["user_flair_enabled"])
        self.assertTrue(settings["show_media_in_comments"])
        self.assertEqual(
            settings_session.calls[1][0],
            "https://www.reddit.com/api/info.json",
        )
        self.assertEqual(settings_session.calls[1][1]["params"]["id"], "t5_2qh0y")

        typeahead_fixture = PUBLIC_CAPABILITIES_FIXTURE["typeahead"]
        typeahead_session = FakeSession(
            [response(text="identity"), response(typeahead_fixture["response"])]
        )
        typeahead_client = RedditClient(session=typeahead_session, retries=0)
        typeahead = typeahead_client.typeahead(
            " fixture ", limit=4, safe_search="STRICT"
        )
        self.assertEqual(typeahead["total"], 3)
        self.assertEqual(
            [item["type"] for item in typeahead["suggestions"]],
            ["user", "subreddit", "subreddit"],
        )
        self.assertEqual(
            typeahead_session.calls[1][0],
            "https://www.reddit.com/api/subreddit_autocomplete_v2.json",
        )
        params = typeahead_session.calls[1][1]["params"]
        self.assertEqual(params["include_profiles"], "true")
        self.assertEqual(params["include_over_18"], "false")
        self.assertEqual(params["safe_search"], "strict")

    def test_trophies_settings_and_typeahead_reject_invalid_contracts(
        self,
    ) -> None:
        with self.assertRaisesRegex(RedditInputError, "t5_"):
            RedditClient(session=FakeSession([]), retries=0).get_subreddit_settings(
                "python"
            )

        mismatch = listing(
            [{"kind": "t5", "data": {"name": "t5_other", "id": "other"}}]
        )
        with self.assertRaisesRegex(RedditResponseError, "fullname mismatch"):
            RedditClient(
                session=FakeSession(
                    [response(text="identity"), response(mismatch)]
                ),
                retries=0,
            ).get_subreddit_settings("t5_2qh0y")

        invalid_trophies = {
            "kind": "TrophyList",
            "data": {"trophies": [{"kind": "t5", "data": {}}]},
        }
        with self.assertRaisesRegex(RedditResponseError, "t6"):
            RedditClient(
                session=FakeSession(
                    [response(text="identity"), response(invalid_trophies)]
                ),
                retries=0,
            ).get_user_trophies("fixture")

        empty_client = RedditClient(session=FakeSession([]), retries=0)
        self.assertEqual(
            empty_client.typeahead("fixture", limit=0)["suggestions"], []
        )
        self.assertEqual(empty_client.session.calls, [])  # type: ignore[attr-defined]
        for invalid_limit in (-1, 11, True):
            with self.subTest(limit=invalid_limit):
                with self.assertRaisesRegex(RedditInputError, "0 to 10"):
                    empty_client.typeahead("fixture", limit=invalid_limit)
        with self.assertRaisesRegex(RedditInputError, "conflicts"):
            empty_client.typeahead(
                "fixture", safe_search="strict", allow_nsfw=True
            )

    def test_more_comments_shared_fixture_expands_and_merges_tree(self) -> None:
        fixture = MORE_COMMENTS_FIXTURE
        session = FakeSession(
            [response(text="identity")]
            + [response(payload) for payload in fixture["responses"]]
        )
        client = RedditClient(session=session, retries=0)

        result = client.get_more_comments(
            fixture["post"],
            fixture["comment_ids"],
            sort=fixture["sort"],
        )

        expected = fixture["expected"]
        for key in (
            "post_id",
            "link_id",
            "sort",
            "requested",
            "requested_total",
            "total",
            "missing",
            "missing_total",
            "orphan_total",
        ):
            self.assertEqual(result[key], expected[key], key)
        self.assertEqual(tree_summary(result["comments"]), expected["root_tree"])
        self.assertEqual(
            tree_summary(result["orphan_comments"]), expected["orphan_tree"]
        )
        self.assertEqual(
            [call[0] for call in session.calls[1:]],
            [
                "https://www.reddit.com/api/morechildren.json",
                "https://www.reddit.com/api/morechildren.json",
                "https://www.reddit.com/api/morechildren.json",
            ],
        )
        self.assertEqual(
            [call[1]["params"]["children"] for call in session.calls[1:]],
            expected["request_batches"],
        )
        self.assertTrue(
            all(
                call[1]["params"]["link_id"] == "t3_post1"
                and call[1]["params"]["sort"] == "new"
                and call[1]["params"]["api_type"] == "json"
                for call in session.calls[1:]
            )
        )

    def test_more_comments_validates_ids_and_initial_boundary(self) -> None:
        client = RedditClient(session=FakeSession([]), retries=0)
        self.assertEqual(
            client._more_comment_ids([" T1_A,b ", "a"]), ["a", "b"]
        )
        self.assertEqual(
            len(client._more_comment_ids([str(index) for index in range(100)])),
            100,
        )
        with self.assertRaisesRegex(RedditInputError, "at most 100"):
            client._more_comment_ids([str(index) for index in range(101)])
        for invalid in ([], [""], ["t3_wrong"], ["bad-id"]):
            with self.subTest(ids=invalid):
                with self.assertRaises(RedditInputError):
                    client.get_more_comments("post1", invalid)
        with self.assertRaises(RedditInputError):
            client.get_more_comments("post1", ["child"], sort="best")
        self.assertEqual(client.session.calls, [])  # type: ignore[attr-defined]

    def test_more_comments_rejects_api_errors_cycles_and_mismatches(self) -> None:
        cycle = morechildren(
            [
                comment_child(
                    "a",
                    name="t1_a",
                    parent_id="t1_b",
                    link_id="t3_post1",
                ),
                comment_child(
                    "b",
                    name="t1_b",
                    parent_id="t1_a",
                    link_id="t3_post1",
                ),
            ]
        )
        cases = [
            (
                "API errors",
                morechildren([], errors=[["BAD_CHILDREN", "fixture", "children"]]),
                "API errors",
            ),
            ("no progress", morechildren([]), "no progress"),
            ("parent cycle", cycle, "cycle"),
            (
                "link mismatch",
                morechildren(
                    [
                        comment_child(
                            "a",
                            name="t1_a",
                            parent_id="t3_post1",
                            link_id="t3_other",
                        )
                    ]
                ),
                "link_id mismatch",
            ),
            (
                "name mismatch",
                morechildren(
                    [
                        comment_child(
                            "a",
                            name="t1_other",
                            parent_id="t3_post1",
                            link_id="t3_post1",
                        )
                    ]
                ),
                "ID/name mismatch",
            ),
        ]
        for name, payload, error_pattern in cases:
            with self.subTest(name=name):
                session = FakeSession(
                    [response(text="identity"), response(payload)]
                )
                with self.assertRaisesRegex(RedditResponseError, error_pattern):
                    RedditClient(session=session, retries=0).get_more_comments(
                        "post1", ["a"]
                    )

    def test_more_comments_fails_on_repeated_more_and_second_batch_error(
        self,
    ) -> None:
        repeated_more = morechildren(
            [{"kind": "more", "data": {"children": ["nested"]}}]
        )
        session = FakeSession(
            [
                response(text="identity"),
                response(repeated_more),
                response(repeated_more),
            ]
        )
        with self.assertRaisesRegex(RedditResponseError, "no progress"):
            RedditClient(session=session, retries=0).get_more_comments(
                "post1", ["root"]
            )

        second_batch = FakeSession(
            [
                response(text="identity"),
                response(repeated_more),
                response(text="rate limited", status=429),
            ]
        )
        with self.assertRaisesRegex(RedditResponseError, "HTTP 429"):
            RedditClient(session=second_batch, retries=0).get_more_comments(
                "post1", ["root"]
            )

        exhausted = FakeSession(
            [response(text="identity")]
            + [response(text="rate limited", status=429) for _ in range(3)]
        )
        with patch("reverse.reddit_reverse.client.time.sleep") as sleep:
            with self.assertRaisesRegex(RedditRateLimited, "HTTP 429"):
                RedditClient(session=exhausted, retries=2).get_more_comments(
                    "post1", ["root"]
                )
        sleep.assert_not_called()

    def test_more_comments_splits_nested_expansion_into_batches_of_100(
        self,
    ) -> None:
        nested_ids = [f"n{index}" for index in range(101)]
        first = morechildren(
            [{"kind": "more", "data": {"children": nested_ids}}]
        )

        def expanded_payload(ids: list[str]) -> dict[str, object]:
            return morechildren(
                [
                    comment_child(
                        comment_id,
                        name=f"t1_{comment_id}",
                        parent_id="t3_post1",
                        link_id="t3_post1",
                    )
                    for comment_id in ids
                ]
            )

        session = FakeSession(
            [
                response(text="identity"),
                response(first),
                response(expanded_payload(nested_ids[:100])),
                response(expanded_payload(nested_ids[100:])),
            ]
        )
        result = RedditClient(session=session, retries=0).get_more_comments(
            "post1", ["seed"]
        )

        self.assertEqual(result["total"], 101)
        self.assertEqual(result["missing"], ["seed"])
        self.assertEqual(
            [
                call[1]["params"]["children"].split(",")
                for call in session.calls[1:]
            ],
            [["seed"], nested_ids[:100], nested_ids[100:]],
        )

    def test_new_cli_commands_dispatch_all_arguments(self) -> None:
        with patch("reverse.reddit_reverse.cli.RedditClient") as client_class:
            client = client_class.return_value
            client.get_user_comments.return_value = {"comments": []}
            client.get_subreddit_info.return_value = {"id": "fixture"}
            client.get_subreddit_rules.return_value = {"rules": []}
            client.get_user_trophies.return_value = {"trophies": []}
            client.get_subreddit_settings.return_value = {"fullname": "t5_fixture"}
            client.typeahead.return_value = {"suggestions": []}
            client.get_more_comments.return_value = {"comments": []}

            comments = _parser().parse_args(
                [
                    "--timeout",
                    "5",
                    "--retries",
                    "1",
                    "--proxy",
                    "http://127.0.0.1:7890",
                    "user-comments",
                    "u/fixture",
                    "--sort",
                    "controversial",
                    "--time",
                    "month",
                    "--limit",
                    "4",
                    "--after",
                    "t1_next",
                ]
            )
            self.assertEqual(_run(comments), {"comments": []})
            client_class.assert_called_once_with(
                timeout=5.0,
                retries=1,
                proxy="http://127.0.0.1:7890",
            )
            client.get_user_comments.assert_called_once_with(
                "u/fixture",
                sort="controversial",
                time_filter="month",
                limit=4,
                after="t1_next",
            )

            self.assertEqual(
                _run(_parser().parse_args(["subreddit-info", "python"])),
                {"id": "fixture"},
            )
            self.assertEqual(
                _run(_parser().parse_args(["subreddit-rules", "python"])),
                {"rules": []},
            )
            self.assertEqual(
                _run(_parser().parse_args(["user-trophies", "u/fixture"])),
                {"trophies": []},
            )
            client.get_user_trophies.assert_called_once_with("u/fixture")
            self.assertEqual(
                _run(
                    _parser().parse_args(
                        ["subreddit-settings", "t5_fixture"]
                    )
                ),
                {"fullname": "t5_fixture"},
            )
            client.get_subreddit_settings.assert_called_once_with("t5_fixture")
            self.assertEqual(
                _run(
                    _parser().parse_args(
                        [
                            "typeahead",
                            "fixture",
                            "--limit",
                            "4",
                            "--safe-search",
                            "strict",
                        ]
                    )
                ),
                {"suggestions": []},
            )
            client.typeahead.assert_called_once_with(
                "fixture",
                limit=4,
                safe_search="strict",
                allow_nsfw=False,
            )
            self.assertEqual(
                _run(
                    _parser().parse_args(
                        [
                            "more-comments",
                            "post1",
                            "t1_a,b",
                            "c",
                            "--sort",
                            "new",
                        ]
                    )
                ),
                {"comments": []},
            )
            client.get_more_comments.assert_called_once_with(
                "post1",
                ["t1_a,b", "c"],
                sort="new",
            )

        with patch.dict(
            "os.environ",
            {"REDDIT_OPPORTUNITY_PROXY": "socks5://fixture-proxy.test:7891"},
            clear=True,
        ):
            client = RedditClient(session=FakeSession([]))
        self.assertEqual(client.proxy, "socks5://fixture-proxy.test:7891")

    def test_retry_and_deterministic_error_semantics(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture connection failure"),
                response(text="temporary", status=503),
                response(text="identity"),
                response(listing([post_child("abc123")], after=None)),
            ]
        )
        client = RedditClient(session=session, retries=2)

        with patch("reverse.reddit_reverse.client.time.sleep") as sleep:
            result = client.get_subreddit("python", limit=1)

        self.assertEqual(result["posts"][0]["id"], "abc123")
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])

        bootstrap_session = FakeSession(
            [
                response(text="blocked", status=403),
                response(text="identity"),
                response(listing([post_child("def456")], after=None)),
            ]
        )
        bootstrap_client = RedditClient(
            session=bootstrap_session,
            retries=2,
            proxy="http://127.0.0.1:7890",
        )
        with patch("reverse.reddit_reverse.client.time.sleep") as sleep:
            result = bootstrap_client.get_subreddit("python", limit=1)
        self.assertEqual(result["posts"][0]["id"], "def456")
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,)])
        self.assertTrue(
            all(
                options["proxy"] == "http://127.0.0.1:7890"
                for _, options in bootstrap_session.calls
            )
        )

        blocked_session = FakeSession(
            [response(text="blocked", status=403) for _ in range(3)]
        )
        blocked_client = RedditClient(session=blocked_session, retries=2)
        with patch("reverse.reddit_reverse.client.time.sleep") as sleep:
            self.assertFalse(blocked_client.initialize_session())
        self.assertEqual(len(blocked_session.calls), 3)
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])

        refresh_session = FakeSession(
            [
                response(text="identity"),
                response(text="blocked", status=403),
                response(text="recovered identity"),
            ]
        )
        refresh_client = RedditClient(session=refresh_session, retries=0)
        self.assertTrue(refresh_client.initialize_session())
        with patch("reverse.reddit_reverse.client.time.sleep") as sleep:
            self.assertFalse(refresh_client.initialize_session(force=True))
            self.assertTrue(refresh_client.initialize_session(force=True))
        self.assertEqual(len(refresh_session.calls), 3)
        sleep.assert_not_called()

        error_session = FakeSession([response(text="not found", status=404)])
        error_client = RedditClient(session=error_session, retries=2)
        with patch("reverse.reddit_reverse.client.time.sleep") as sleep:
            self.assertFalse(error_client.initialize_session())
        self.assertEqual(len(error_session.calls), 1)
        sleep.assert_not_called()

        with patch("reverse.reddit_reverse.client.requests.Session") as session_class:
            RedditClient()
        session_class.assert_called_once_with(
            impersonate="chrome146",
            trust_env=False,
            proxies={"all": ""},
        )

    def test_invalid_json_and_api_error_are_reported(self) -> None:
        session = FakeSession(
            [
                response(text="identity"),
                response(text="not-json"),
                response({"error": 429, "message": "rate limited"}),
            ]
        )
        client = RedditClient(session=session, retries=0)

        with self.assertRaisesRegex(RedditResponseError, "invalid JSON"):
            client.get_subreddit("python", limit=1)
        with self.assertRaisesRegex(RedditResponseError, "API error 429"):
            client.get_subreddit("python", limit=1)


if __name__ == "__main__":
    unittest.main()
