from __future__ import annotations

import json
import unittest
from collections import deque
from unittest.mock import patch

from curl_cffi import requests

from reverse.twitter_reverse import cli
from reverse.twitter_reverse.client import (
    GUEST_ACTIVATE_URL,
    SYNDICATION_FEATURES,
    SYNDICATION_URL,
    TRENDS_PLACE_URL,
    TREND_LOCATIONS_URL,
    TwitterClient,
    parse_tweet_id,
)
from reverse.twitter_reverse.errors import TwitterInputError, TwitterResponseError


def response(
    payload: object | None = None,
    *,
    text: str | None = None,
    status: int = 200,
    url: str = "",
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.content = (
        text.encode("utf-8") if text is not None else json.dumps(payload).encode("utf-8")
    )
    result.default_encoding = "utf-8"
    result.headers["content-type"] = "application/json; charset=utf-8"
    return result


class FakeSession(requests.Session):
    def __init__(self, results: list[requests.Response | Exception]) -> None:
        super().__init__()
        self.results = deque(results)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        self.calls.append((f"{method} {url}", kwargs))
        if not self.results:
            raise AssertionError(f"unexpected HTTP request: {url}")
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        if not result.url:
            result.url = url
        return result

    def get(self, url: str, **kwargs: object) -> requests.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: object) -> requests.Response:
        return self._request("POST", url, **kwargs)


class FakeSigner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def sign(self, tweet_id: str | int) -> dict[str, str]:
        identifier = str(tweet_id)
        self.calls.append(identifier)
        return {"id": identifier, "token": "fixture-token"}


def quoted_payload() -> dict[str, object]:
    return {
        "id_str": "333",
        "favorite_count": 8,
        "reply_count": 3,
        "retweet_count": 4,
        "lang": "en",
        "created_at": "2024-01-01T00:00:00.000Z",
        "display_text_range": [0, 12],
        "entities": {},
        "text": "Quoted post",
        "user": {
            "id_str": "30",
            "name": "Quoted Author",
            "screen_name": "quoted",
            "verified": True,
            "is_blue_verified": False,
            "profile_image_url_https": "https://img.example/quoted.jpg",
        },
        "edit_control": {"edit_tweet_ids": ["333"]},
        "isEdited": False,
    }


def tweet_payload() -> dict[str, object]:
    return {
        "__typename": "Tweet",
        "id_str": "111",
        "favorite_count": 12,
        "conversation_count": 7,
        "lang": "en",
        "possibly_sensitive": True,
        "created_at": "2024-01-02T03:04:05.000Z",
        # X 实体位置以 UTF-16 代码单元计数，表情符号占两个单元。
        "display_text_range": [0, 26],
        "text": "Hello 😀 https://t.co/link https://t.co/media",
        "entities": {
            "urls": [
                {
                    "url": "https://t.co/link",
                    "display_url": "example.test/article",
                    "expanded_url": "https://example.test/article",
                    "indices": [9, 26],
                }
            ],
            "hashtags": [{"text": "fixture", "indices": [0, 7]}],
            "user_mentions": [
                {
                    "id_str": "40",
                    "name": "Mention",
                    "screen_name": "mention",
                    "indices": [0, 7],
                }
            ],
            "symbols": [{"text": "TEST", "indices": [0, 5]}],
            "media": [
                {
                    "url": "https://t.co/media",
                    "expanded_url": "https://x.com/source/status/111/photo/1",
                    "indices": [26, 45],
                }
            ],
        },
        "user": {
            "id_str": "10",
            "name": "Source Author",
            "screen_name": "source",
            "verified": False,
            "is_blue_verified": True,
            "verified_type": "Business",
            "profile_image_shape": "Square",
            "profile_image_url_https": "https://img.example/source_normal.jpg",
        },
        "edit_control": {"edit_tweet_ids": ["111"], "edits_remaining": "4"},
        "isEdited": True,
        "in_reply_to_status_id_str": "99",
        "in_reply_to_user_id_str": "9",
        "in_reply_to_screen_name": "parent",
        "mediaDetails": [
            {
                "type": "photo",
                "media_url_https": "https://pbs.example/photo.jpg",
                "expanded_url": "https://x.com/source/status/111/photo/1",
                "ext_alt_text": "fixture photo",
                "ext_media_availability": {"status": "Available"},
                "original_info": {"width": 1600, "height": 900},
            },
            {
                "type": "video",
                "media_url_https": "https://pbs.example/poster.jpg",
                "expanded_url": "https://x.com/source/status/111/video/1",
                "ext_media_availability": {"status": "Available"},
                "original_info": {"width": 1280, "height": 720},
                "video_info": {
                    "duration_millis": 12345,
                    "aspect_ratio": [16, 9],
                    "variants": [
                        {
                            "content_type": "application/x-mpegURL",
                            "url": "https://video.example/master.m3u8",
                        },
                        {
                            "bitrate": 256000,
                            "content_type": "video/mp4",
                            "url": "https://video.example/low.mp4",
                        },
                        {
                            "bitrate": 2176000,
                            "content_type": "video/mp4",
                            "url": "https://video.example/high.mp4",
                        },
                    ],
                },
            },
        ],
        "quoted_tweet": quoted_payload(),
    }


class TwitterClientTest(unittest.TestCase):
    def test_ids_and_direct_status_urls_are_parsed_without_network(self) -> None:
        references = {
            "20": "20",
            20: "20",
            "https://x.com/jack/status/20": "20",
            "http://www.twitter.com/jack/statuses/20/photo/1?ref_src=twsrc": "20",
            "mobile.twitter.com/i/web/status/20": "20",
            "https://x.com/i/status/20/": "20",
        }
        for reference, expected in references.items():
            with self.subTest(reference=reference):
                self.assertEqual(parse_tweet_id(reference), expected)

        for reference in (
            True,
            "",
            "https://example.com/jack/status/20",
            "https://x.com/jack",
            "https://user@x.com/jack/status/20",
            "https://x.com:444/jack/status/20",
            "https://x.com:80/jack/status/20",
            "http://x.com:443/jack/status/20",
            "https://fake-x.com/jack/status/20",
            "https://x.com/jack/status/0",
        ):
            with self.subTest(reference=reference):
                with self.assertRaises(TwitterInputError):
                    parse_tweet_id(reference)  # type: ignore[arg-type]

    def test_normalization_covers_utf16_text_author_media_quote_and_retweet(self) -> None:
        tweet = TwitterClient.normalize_tweet(tweet_payload(), requested_id="222")

        self.assertEqual(tweet["id"], "111")
        self.assertEqual(tweet["requested_id"], "222")
        self.assertEqual(tweet["text"], "Hello 😀 https://t.co/link")
        self.assertTrue(tweet["raw_text"].endswith("https://t.co/media"))
        self.assertEqual(tweet["created_timestamp"], 1704164645)
        self.assertEqual(tweet["author"]["username"], "source")
        self.assertTrue(tweet["author"]["verified"])
        self.assertFalse(tweet["author"]["legacy_verified"])
        self.assertEqual(
            tweet["stats"], {"likes": 12, "replies": 7, "reposts": None}
        )
        self.assertEqual(tweet["links"][0]["expanded_url"], "https://example.test/article")
        self.assertEqual(tweet["entities"]["mentions"][0]["username"], "mention")
        self.assertEqual(tweet["media"][0]["type"], "photo")
        self.assertEqual(tweet["media"][0]["alt_text"], "fixture photo")
        self.assertEqual(tweet["media"][1]["url"], "https://video.example/high.mp4")
        self.assertEqual(tweet["media"][1]["duration_ms"], 12345)
        self.assertEqual(tweet["quoted_tweet"]["id"], "333")
        self.assertEqual(
            tweet["quoted_tweet"]["stats"],
            {"likes": 8, "replies": 3, "reposts": 4},
        )
        self.assertEqual(tweet["reply_to"]["tweet_id"], "99")
        self.assertEqual(tweet["reply_to"]["url"], "https://x.com/parent/status/99")
        self.assertTrue(tweet["is_retweet"])
        self.assertEqual(tweet["retweet"]["source_tweet_id"], "111")
        self.assertEqual(tweet["retweet"]["id"], "222")
        self.assertTrue(tweet["possibly_sensitive"])
        self.assertTrue(tweet["edited"])

    def test_full_note_text_wins_and_edit_resolution_is_not_a_retweet(self) -> None:
        payload = tweet_payload()
        payload["edit_control"] = {"edit_tweet_ids": ["110", "111"]}
        payload["note_tweet"] = {
            "note_tweet_results": {
                "result": {
                    "id": "note-111",
                    "text": "Complete note 😀 with an expanded link",
                    "entity_set": {
                        "urls": [
                            {
                                "url": "https://t.co/note",
                                "display_url": "example.test/note",
                                "expanded_url": "https://example.test/note",
                                "indices": [22, 40],
                            }
                        ]
                    },
                }
            }
        }

        tweet = TwitterClient.normalize_tweet(payload, requested_id="110")

        self.assertEqual(tweet["text"], "Complete note 😀 with an expanded link")
        self.assertEqual(tweet["raw_text"], "Complete note 😀 with an expanded link")
        self.assertFalse(tweet["text_truncated"])
        self.assertEqual(tweet["note_tweet_id"], "note-111")
        self.assertEqual(tweet["links"][0]["expanded_url"], "https://example.test/note")
        self.assertTrue(tweet["resolved_from_edit"])
        self.assertFalse(tweet["is_retweet"])
        self.assertIsNone(tweet["retweet"])

    def test_request_uses_signed_syndication_contract(self) -> None:
        session = FakeSession([response(tweet_payload())])
        signer = FakeSigner()
        client = TwitterClient(
            session=session,
            signer=signer,  # type: ignore[arg-type]
            timeout=7,
            retries=0,
        )

        tweet = client.get_tweet("https://x.com/retweeter/status/222", language="zh-CN")

        self.assertEqual(tweet["id"], "111")
        self.assertEqual(signer.calls, ["222"])
        self.assertEqual(session.calls[0][0], f"GET {SYNDICATION_URL}")
        self.assertEqual(
            session.calls[0][1]["params"],
            {
                "id": "222",
                "lang": "zh-CN",
                "features": SYNDICATION_FEATURES,
                "token": "fixture-token",
            },
        )
        self.assertEqual(session.calls[0][1]["timeout"], 7)
        self.assertEqual(session.headers["Accept"], "application/json,text/plain,*/*")

    def test_transient_errors_retry_with_exponential_backoff(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture connection failure"),
                response({"error": "temporary"}, status=503),
                response(tweet_payload()),
            ]
        )
        client = TwitterClient(
            session=session,
            signer=FakeSigner(),  # type: ignore[arg-type]
            retries=2,
        )

        with patch("reverse.twitter_reverse.client.time.sleep") as sleep:
            tweet = client.get_tweet("222")

        self.assertEqual(tweet["id"], "111")
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])
        self.assertEqual(len(session.calls), 3)

    def test_rate_limit_response_retries(self) -> None:
        session = FakeSession(
            [response({"error": "rate limited"}, status=429), response(tweet_payload())]
        )
        client = TwitterClient(
            session=session,
            signer=FakeSigner(),  # type: ignore[arg-type]
            retries=1,
        )

        with patch("reverse.twitter_reverse.client.time.sleep") as sleep:
            tweet = client.get_tweet("222")

        self.assertEqual(tweet["id"], "111")
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,)])
        self.assertEqual(len(session.calls), 2)

    def test_deterministic_http_and_payload_errors_fail_cleanly(self) -> None:
        missing = TwitterClient(
            session=FakeSession([response({}, status=404), response(tweet_payload())]),
            signer=FakeSigner(),  # type: ignore[arg-type]
            retries=2,
        )
        with self.assertRaisesRegex(TwitterResponseError, "not found"):
            missing.get_tweet("222")
        self.assertEqual(len(missing.session.calls), 1)  # type: ignore[attr-defined]

        cases = [
            response({}),
            response({"__typename": "TweetTombstone"}),
            response({"__typename": "Unexpected", "id_str": "111"}),
            response([{"id_str": "111"}]),
            response(text="not json"),
        ]
        for result in cases:
            with self.subTest(content=result.text):
                client = TwitterClient(
                    session=FakeSession([result]),
                    signer=FakeSigner(),  # type: ignore[arg-type]
                    retries=0,
                )
                with self.assertRaises(TwitterResponseError):
                    client.get_tweet("222")

    def test_language_and_payload_ids_are_validated(self) -> None:
        client = TwitterClient(
            session=FakeSession([]),
            signer=FakeSigner(),  # type: ignore[arg-type]
        )
        for language in ("", "english", "en_US", "a", "en-toolongsegment"):
            with self.subTest(language=language):
                with self.assertRaises(TwitterInputError):
                    client.get_tweet("222", language=language)
        self.assertEqual(client.session.calls, [])  # type: ignore[attr-defined]

        malformed = tweet_payload()
        malformed["id_str"] = "not-an-id"
        with self.assertRaisesRegex(TwitterResponseError, "invalid id_str"):
            TwitterClient.normalize_tweet(malformed)

    def test_cli_token_command_stays_offline(self) -> None:
        args = cli._parser().parse_args(["token", "https://x.com/jack/status/20"])

        self.assertEqual(
            cli._run(args),
            {"id": "20", "token": "6dq1a2xwd93"},
        )

    def test_trending_activates_guest_resolves_location_and_normalizes_items(
        self,
    ) -> None:
        session = FakeSession(
            [
                response({"guest_token": "1234567890123456789"}),
                response(
                    [
                        {
                            "name": "Worldwide",
                            "placeType": {"code": 19, "name": "Supername"},
                            "url": "http://where.yahooapis.com/v1/place/1",
                            "parentid": 0,
                            "country": "",
                            "woeid": 1,
                            "countryCode": None,
                        },
                        {
                            "name": "United States",
                            "placeType": {"code": 12, "name": "Country"},
                            "url": "http://where.yahooapis.com/v1/place/23424977",
                            "parentid": 1,
                            "country": "United States",
                            "woeid": 23424977,
                            "countryCode": "US",
                        },
                    ]
                ),
                response(
                    [
                        {
                            "trends": [
                                {
                                    "name": "#Fixture",
                                    "url": "http://twitter.com/search?q=%23Fixture",
                                    "promoted_content": None,
                                    "query": "%23Fixture",
                                    "tweet_volume": 12345,
                                },
                                {
                                    "name": "Quoted Topic",
                                    "url": "http://twitter.com/search?q=%22Quoted+Topic%22",
                                    "promoted_content": None,
                                    "query": "%22Quoted+Topic%22",
                                    "tweet_volume": None,
                                },
                            ],
                            "as_of": "2026-07-25T06:09:33Z",
                            "created_at": "2026-07-24T11:14:00Z",
                            "locations": [
                                {"name": "United States", "woeid": 23424977}
                            ],
                        }
                    ]
                ),
            ]
        )
        client = TwitterClient(session=session, retries=0)

        result = client.get_trending("US", limit=2)

        self.assertEqual(result["kind"], "trend_list")
        self.assertEqual(result["location"]["woeid"], 23424977)
        self.assertEqual(result["raw_count"], 2)
        self.assertEqual(result["items"][0]["query"], "#Fixture")
        self.assertEqual(result["items"][0]["tweet_volume"], 12345)
        self.assertEqual(
            result["items"][0]["url"],
            "https://x.com/search?q=%23Fixture&src=trend_click",
        )
        self.assertEqual(
            [call[0] for call in session.calls],
            [
                f"POST {GUEST_ACTIVATE_URL}",
                f"GET {TREND_LOCATIONS_URL}",
                f"GET {TRENDS_PLACE_URL}",
            ],
        )
        self.assertEqual(
            session.calls[2][1]["params"],
            {"id": "23424977"},
        )
        for _, kwargs in session.calls:
            headers = kwargs["headers"]
            self.assertIn("Authorization", headers)
        self.assertNotIn("X-Guest-Token", session.calls[0][1]["headers"])
        self.assertEqual(
            session.calls[1][1]["headers"]["X-Guest-Token"],
            "1234567890123456789",
        )

    def test_trend_locations_filter_limit_and_numeric_woeid_skip_resolution(
        self,
    ) -> None:
        locations = [
            {
                "name": "Toronto",
                "placeType": {"code": 7, "name": "Town"},
                "parentid": 23424775,
                "country": "Canada",
                "woeid": 4118,
                "countryCode": "CA",
            },
            {
                "name": "United States",
                "placeType": {"code": 12, "name": "Country"},
                "parentid": 1,
                "country": "United States",
                "woeid": 23424977,
                "countryCode": "US",
            },
        ]
        session = FakeSession(
            [
                response({"guest_token": "1234567890123456789"}),
                response(locations),
            ]
        )
        client = TwitterClient(session=session, retries=0)
        result = client.get_trend_locations(country="ca", limit=1)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["name"], "Toronto")

        numeric_session = FakeSession(
            [
                response({"guest_token": "1234567890123456789"}),
                response(
                    [
                        {
                            "trends": [
                                {
                                    "name": "Fixture",
                                    "url": "http://twitter.com/search?q=Fixture",
                                    "query": "Fixture",
                                    "tweet_volume": None,
                                }
                            ],
                            "locations": [{"name": "Worldwide", "woeid": 1}],
                        }
                    ]
                ),
            ]
        )
        numeric = TwitterClient(session=numeric_session, retries=0)
        self.assertEqual(numeric.get_trending(1, limit=1)["location"]["woeid"], 1)
        self.assertEqual(
            [call[0] for call in numeric_session.calls],
            [f"POST {GUEST_ACTIVATE_URL}", f"GET {TRENDS_PLACE_URL}"],
        )

    def test_trend_inputs_and_malformed_protocol_responses_fail_cleanly(self) -> None:
        client = TwitterClient(session=FakeSession([]), retries=0)
        for location in ("", True, "x" * 101, 0):
            with self.subTest(location=location):
                with self.assertRaises(TwitterInputError):
                    client.get_trending(location, limit=1)  # type: ignore[arg-type]
        for limit in (0, 51, True):
            with self.subTest(limit=limit):
                with self.assertRaises(TwitterInputError):
                    client.get_trending("US", limit=limit)  # type: ignore[arg-type]
        self.assertEqual(client.session.calls, [])  # type: ignore[attr-defined]

        malformed_guest = TwitterClient(
            session=FakeSession([response({"guest_token": "bad"})]),
            retries=0,
        )
        with self.assertRaisesRegex(TwitterResponseError, "guest_token"):
            malformed_guest.get_trend_locations()

        malformed_locations = TwitterClient(
            session=FakeSession(
                [
                    response({"guest_token": "1234567890123456789"}),
                    response({"locations": []}),
                ]
            ),
            retries=0,
        )
        with self.assertRaisesRegex(TwitterResponseError, "must be an array"):
            malformed_locations.get_trend_locations()

    def test_cli_trend_commands_route_without_tweet_id_parsing(self) -> None:
        trending_args = cli._parser().parse_args(
            ["trending", "Worldwide", "--limit", "3"]
        )
        locations_args = cli._parser().parse_args(
            ["trend-locations", "--country", "US", "--limit", "2"]
        )
        with patch.object(
            TwitterClient,
            "get_trending",
            return_value={"kind": "trend_list"},
        ) as trending:
            self.assertEqual(cli._run(trending_args), {"kind": "trend_list"})
        trending.assert_called_once_with("Worldwide", limit=3)

        with patch.object(
            TwitterClient,
            "get_trend_locations",
            return_value={"kind": "trend_locations"},
        ) as locations_call:
            self.assertEqual(
                cli._run(locations_args),
                {"kind": "trend_locations"},
            )
        locations_call.assert_called_once_with(country="US", limit=2)


if __name__ == "__main__":
    unittest.main()
