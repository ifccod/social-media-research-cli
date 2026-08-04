from __future__ import annotations

import json
import unittest
from collections import deque
from pathlib import Path
from typing import Any
from unittest.mock import patch

from curl_cffi import requests

from reverse.youtube_reverse.cli import _parser, _run
from reverse.youtube_reverse.client import YouTubeClient
from reverse.youtube_reverse.errors import YouTubeError, YouTubeInputError, YouTubeResponseError

FIXTURE_DIR = Path(__file__).with_name("fixtures")
FIXTURE = (FIXTURE_DIR / "watch_page.html").read_text(encoding="utf-8")
SEARCH_FIXTURE = (FIXTURE_DIR / "discovery_search.html").read_text(encoding="utf-8")
CHANNEL_FIXTURE = (FIXTURE_DIR / "channel_videos.html").read_text(encoding="utf-8")
COMMENTS_WATCH_FIXTURE = (FIXTURE_DIR / "comments_watch.html").read_text(
    encoding="utf-8"
)
DISCOVERY_CONTINUATION = json.loads(
    (FIXTURE_DIR / "discovery_continuation.json").read_text(encoding="utf-8")
)
COMMENTS_PAGE = json.loads(
    (FIXTURE_DIR / "comments_page.json").read_text(encoding="utf-8")
)
COMMENTS_DIRECT = json.loads(
    (FIXTURE_DIR / "comments_direct.json").read_text(encoding="utf-8")
)
TRENDING_CHART = json.loads(
    (FIXTURE_DIR / "trending_chart.json").read_text(encoding="utf-8")
)


class FakeResponse:
    def __init__(
        self,
        *,
        text: str = "",
        payload: Any = None,
        status: int = 200,
        url: str = "",
    ) -> None:
        self.text = text
        self.payload = payload
        self.status_code = status
        self.url = url

    def json(self) -> Any:
        if isinstance(self.payload, BaseException):
            raise self.payload
        if self.payload is not None:
            return self.payload
        return json.loads(self.text)


class FakeSession:
    def __init__(
        self,
        *,
        get: list[FakeResponse | BaseException] | None = None,
        post: list[FakeResponse | BaseException] | None = None,
    ) -> None:
        self.headers: dict[str, str] = {}
        self.get_results = deque(get or [])
        self.post_results = deque(post or [])
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.get_calls.append((url, kwargs))
        return self._next(self.get_results)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append((url, kwargs))
        return self._next(self.post_results)

    @staticmethod
    def _next(queue: deque[FakeResponse | BaseException]) -> FakeResponse:
        if not queue:
            raise AssertionError("unexpected fake HTTP request")
        value = queue.popleft()
        if isinstance(value, BaseException):
            raise value
        return value


def page(source: str = FIXTURE, *, status: int = 200) -> FakeResponse:
    return FakeResponse(text=source, status=status)


def player_payload() -> dict[str, Any]:
    return YouTubeClient.extract_player_response(FIXTURE)


class YouTubeClientTest(unittest.TestCase):
    def test_error_types_share_the_public_base(self) -> None:
        self.assertTrue(issubclass(YouTubeInputError, YouTubeError))
        self.assertTrue(issubclass(YouTubeResponseError, YouTubeError))

    def test_resolve_video_id_accepts_common_urls_and_short_links(self) -> None:
        expected = "dQw4w9WgXcQ"
        references = [
            expected,
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=fixture",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ?t=10",
            "youtu.be/dQw4w9WgXcQ",
            "youtube.com/shorts/dQw4w9WgXcQ?feature=share",
            "https://www.youtube.com/live/dQw4w9WgXcQ",
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
            "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        ]
        self.assertEqual(
            [YouTubeClient.resolve_video_id(item) for item in references],
            [expected] * len(references),
        )

    def test_invalid_and_similar_domain_urls_are_rejected(self) -> None:
        for value in [
            "short",
            "https://youtube.com.example/watch?v=dQw4w9WgXcQ",
            "https://notyoutube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be.example/dQw4w9WgXcQ",
            "https://www.youtube.com/playlist?list=dQw4w9WgXcQ",
        ]:
            with self.subTest(value=value), self.assertRaises(YouTubeInputError):
                YouTubeClient.resolve_video_id(value)

    def test_language_and_region_are_validated_before_headers_are_set(self) -> None:
        with self.assertRaises(YouTubeInputError):
            YouTubeClient(session=FakeSession(), language="en\r\nX-Test: yes")  # type: ignore[arg-type]
        with self.assertRaises(YouTubeInputError):
            YouTubeClient(session=FakeSession(), region="USA")  # type: ignore[arg-type]
        client = YouTubeClient(
            session=FakeSession(), language="zh-Hans", region="cn"  # type: ignore[arg-type]
        )
        self.assertEqual(client.language, "zh-Hans")
        self.assertEqual(client.region, "CN")
        self.assertEqual(client.session.headers["Accept-Language"], "zh-Hans,en;q=0.8")

    def test_channel_references_are_normalized_and_lookalike_hosts_are_rejected(self) -> None:
        references = [
            "@fixture",
            "fixture",
            "https://www.youtube.com/@fixture/videos",
            "youtube.com/c/fixture",
            "https://m.youtube.com/user/fixture",
        ]
        resolved = [YouTubeClient.resolve_channel_reference(item) for item in references]
        self.assertEqual([item["handle"] for item in resolved[:3]], ["fixture"] * 3)
        self.assertEqual(resolved[2]["videos_url"], "https://www.youtube.com/@fixture/videos")
        self.assertEqual(resolved[3]["videos_url"], "https://www.youtube.com/c/fixture/videos")
        self.assertEqual(resolved[4]["kind"], "user")

        channel_id = "UCbbbbbbbbbbbbbbbbbbbbbb"
        self.assertEqual(
            YouTubeClient.resolve_channel_reference(channel_id)["id"], channel_id
        )
        for value in [
            "https://youtube.com.example/@fixture",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "@bad handle",
        ]:
            with self.subTest(value=value), self.assertRaises(YouTubeInputError):
                YouTubeClient.resolve_channel_reference(value)

    def test_discovery_and_comment_fixtures_cover_current_and_legacy_shapes(self) -> None:
        search_data = YouTubeClient.extract_initial_data(SEARCH_FIXTURE)
        search_items = YouTubeClient.normalize_discovery_items(search_data)
        self.assertEqual([item["type"] for item in search_items], ["video", "channel", "playlist"])
        self.assertEqual(search_items[0]["description"], "First snippet second snippet")
        self.assertEqual(search_items[0]["thumbnails"][0]["url"], "https://i.example/search.jpg")
        self.assertEqual(search_items[1]["handle"], "@fixture-channel")
        self.assertEqual(search_items[1]["subscribers_text"], "12K subscribers")
        self.assertEqual(search_items[1]["video_count_text"], "42 videos")
        self.assertEqual(YouTubeClient.next_continuation(search_data), "SEARCH_NEXT")

        channel_data = YouTubeClient.extract_initial_data(CHANNEL_FIXTURE)
        channel_items = YouTubeClient.normalize_discovery_items(
            channel_data, videos_only=True
        )
        self.assertEqual([item["id"] for item in channel_items], ["BBBBBBBBBBB", "CCCCCCCCCCC"])
        self.assertEqual(channel_items[0]["duration_text"], "12:34")
        self.assertEqual(channel_items[0]["views_text"], "2.3K views")
        self.assertEqual(channel_items[1]["title"], "Fixture legacy channel video")

        comments = YouTubeClient.normalize_comments(COMMENTS_PAGE)
        self.assertEqual([item["id"] for item in comments], ["COMMENT_MODERN", "COMMENT_LEGACY"])
        self.assertEqual(comments[0]["likes"], 2500)
        self.assertEqual(comments[0]["reply_count"], 7)
        self.assertTrue(comments[0]["is_pinned"])
        self.assertEqual(comments[0]["replies_cursor"], "REPLIES_CURSOR")
        self.assertEqual(comments[1]["likes"], 1200)
        self.assertEqual(YouTubeClient.next_continuation(COMMENTS_PAGE), "COMMENTS_NEXT")

        direct = YouTubeClient.normalize_comments(COMMENTS_DIRECT)
        self.assertEqual(len(direct), 1)
        self.assertEqual(direct[0]["id"], "COMMENT_DIRECT")
        self.assertTrue(direct[0]["is_pinned"])
        self.assertEqual(direct[0]["replies_cursor"], "DIRECT_REPLIES_CURSOR")

        watch_data = YouTubeClient.extract_initial_data(COMMENTS_WATCH_FIXTURE)
        self.assertEqual(
            YouTubeClient.initial_comments_continuation(watch_data),
            "COMMENTS_INITIAL",
        )
        transcript_only = {"engagementPanels": [watch_data["engagementPanels"][0]]}
        self.assertEqual(
            YouTubeClient.initial_comments_continuation(transcript_only), ""
        )

        main_before_reply = {
            "continuationItems": [
                {
                    "continuationItemRenderer": {
                        "continuationEndpoint": {
                            "continuationCommand": {"token": "MAIN_CURSOR"}
                        }
                    }
                },
                {
                    "commentRepliesRenderer": {
                        "contents": [
                            {
                                "continuationItemRenderer": {
                                    "continuationEndpoint": {
                                        "continuationCommand": {
                                            "token": "REPLY_AFTER_MAIN"
                                        }
                                    }
                                }
                            }
                        ]
                    }
                },
            ]
        }
        self.assertEqual(
            YouTubeClient.next_continuation(main_before_reply), "MAIN_CURSOR"
        )

        fallback = {
            "continuationItemRenderer": {
                "continuationEndpoint": {
                    "continuationCommand": {"token": "FALLBACK_CURSOR"}
                }
            }
        }
        primary = {
            "onResponseReceivedCommands": [
                {
                    "appendContinuationItemsAction": {
                        "continuationItems": [
                            {
                                "continuationItemRenderer": {
                                    "continuationEndpoint": {
                                        "continuationCommand": {
                                            "token": "PRIMARY_CURSOR"
                                        }
                                    }
                                }
                            }
                        ]
                    }
                }
            ]
        }
        for multiple in [
            {"contents": [fallback], **primary},
            {**primary, "contents": [fallback]},
        ]:
            self.assertEqual(
                YouTubeClient.next_continuation(multiple), "PRIMARY_CURSOR"
            )

    def test_player_and_config_are_extracted_independently(self) -> None:
        config_only = FIXTURE.split("</head>", 1)[0]
        player_only = FIXTURE.split("<body>", 1)[1]

        config = YouTubeClient.extract_innertube_config(config_only)
        player = YouTubeClient.extract_player_response(player_only)

        self.assertEqual(config["api_key"], "fixture-api-key")
        self.assertEqual(config["client_version"], "2.20260715.00.00")
        self.assertEqual(config["client_name_id"], 1)
        self.assertEqual(config["visitor_data"], "fixture-visitor")
        self.assertEqual(config["signature_timestamp"], 20649)
        self.assertEqual(config["context"]["request"], {"useSsl": True})
        self.assertEqual(player["videoDetails"]["videoId"], "dQw4w9WgXcQ")

        with self.assertRaises(YouTubeResponseError):
            YouTubeClient.extract_player_response(config_only)
        empty_config = YouTubeClient.extract_innertube_config(player_only)
        self.assertEqual(empty_config["api_key"], "")

    def test_nested_player_json_and_trailing_script_are_decoded_structurally(self) -> None:
        video = YouTubeClient.parse_watch_html(
            FIXTURE, expected_video_id="dQw4w9WgXcQ"
        )

        self.assertEqual(video["title"], "Fixture video")
        self.assertIn("}; still data", video["description"])
        self.assertEqual(video["duration_seconds"], 213)
        self.assertEqual(video["author"]["id"], "UC-fixture-channel")
        self.assertEqual(video["author"]["url"], "https://www.youtube.com/@fixture")
        self.assertEqual(video["stats"], {"views": 1234567, "likes": 7654})
        self.assertEqual(video["thumbnail_url"], "https://i.example/1280.jpg")
        self.assertEqual(video["publish_date"], "2024-01-02")
        self.assertEqual(video["available_countries"], ["US", "GB"])

    def test_formats_preserve_direct_plain_and_encrypted_cipher_boundaries(self) -> None:
        streams = YouTubeClient.parse_watch_html(FIXTURE)["streams"]
        direct = streams["formats"][0]
        plain = streams["adaptive_formats"][0]
        encrypted = streams["adaptive_formats"][1]
        sabr_only = streams["adaptive_formats"][2]

        self.assertEqual(streams["total"], 4)
        self.assertEqual(direct["type"], "muxed")
        self.assertTrue(direct["has_direct_url"])
        self.assertTrue(direct["requires_n_transform"])
        self.assertEqual(plain["type"], "audio")
        self.assertIn("sig=plain-signature", plain["url"])
        self.assertFalse(plain["requires_signature"])
        self.assertEqual(plain["content_length"], 34567)
        self.assertEqual(encrypted["type"], "video")
        self.assertTrue(encrypted["requires_signature"])
        self.assertEqual(encrypted["encrypted_signature"], "encrypted-signature")
        self.assertNotIn("sig=encrypted-signature", encrypted["url"])
        self.assertFalse(sabr_only["has_direct_url"])
        self.assertEqual(sabr_only["url"], "")

    def test_caption_tracks_audio_mapping_and_translations_are_normalized(self) -> None:
        captions = YouTubeClient.parse_watch_html(FIXTURE)["captions"]

        self.assertEqual(captions["total"], 2)
        self.assertEqual(captions["tracks"][0]["language_code"], "en")
        self.assertEqual(captions["tracks"][1]["name"], "Spanish (auto-generated)")
        self.assertTrue(captions["tracks"][1]["is_auto_generated"])
        self.assertEqual(captions["audio_tracks"][0]["caption_track_indices"], [0, 1])
        self.assertEqual(captions["translation_languages"][0]["language_code"], "zh-Hans")
        self.assertEqual(captions["default_audio_track_index"], 0)

    def test_watch_request_returns_normalized_video_without_fallback(self) -> None:
        session = FakeSession(get=[page()])
        client = YouTubeClient(session=session, retries=0)  # type: ignore[arg-type]

        video = client.get_video("https://youtu.be/dQw4w9WgXcQ")

        self.assertEqual(video["source"], "watch_html")
        self.assertEqual(video["id"], "dQw4w9WgXcQ")
        self.assertEqual(len(session.get_calls), 1)
        self.assertEqual(session.post_calls, [])
        self.assertEqual(session.get_calls[0][0], "https://www.youtube.com/watch")
        self.assertEqual(session.get_calls[0][1]["params"]["v"], "dQw4w9WgXcQ")
        self.assertEqual(session.get_calls[0][1]["params"]["gl"], "US")
        self.assertIn("text/html", session.get_calls[0][1]["headers"]["Accept"])

    def test_public_innertube_fallback_reuses_watch_configuration(self) -> None:
        config_only = FIXTURE.split("</head>", 1)[0] + "</head></html>"
        session = FakeSession(
            get=[page(config_only)],
            post=[FakeResponse(payload=player_payload())],
        )
        client = YouTubeClient(session=session, retries=0)  # type: ignore[arg-type]

        video = client.get_video("dQw4w9WgXcQ")

        self.assertEqual(video["source"], "innertube")
        self.assertEqual(len(session.post_calls), 1)
        url, kwargs = session.post_calls[0]
        self.assertEqual(url, "https://www.youtube.com/youtubei/v1/player")
        self.assertEqual(kwargs["params"], {"key": "fixture-api-key", "prettyPrint": "false"})
        self.assertEqual(kwargs["json"]["videoId"], "dQw4w9WgXcQ")
        self.assertEqual(kwargs["json"]["context"]["client"]["visitorData"], "fixture-visitor")
        self.assertEqual(
            kwargs["json"]["playbackContext"]["contentPlaybackContext"]["signatureTimestamp"],
            20649,
        )
        self.assertEqual(kwargs["headers"]["X-YouTube-Client-Name"], "1")
        self.assertEqual(kwargs["headers"]["X-Goog-Visitor-Id"], "fixture-visitor")

    def test_innertube_fallback_failure_reports_both_failed_stages(self) -> None:
        config_only = FIXTURE.split("</head>", 1)[0] + "</head></html>"
        session = FakeSession(
            get=[page(config_only)],
            post=[FakeResponse(text="busy", status=503)],
        )
        client = YouTubeClient(session=session, retries=0)  # type: ignore[arg-type]

        with self.assertRaisesRegex(
            YouTubeResponseError,
            "does not contain ytInitialPlayerResponse; Innertube fallback failed:.*HTTP 503",
        ):
            client.get_video("dQw4w9WgXcQ")

    def test_oembed_basic_metadata_is_normalized(self) -> None:
        session = FakeSession(
            get=[
                FakeResponse(
                    payload={
                        "title": "Fixture oEmbed",
                        "author_name": "Fixture creator",
                        "author_url": "https://www.youtube.com/@fixture",
                        "provider_name": "YouTube",
                        "provider_url": "https://www.youtube.com/",
                        "type": "video",
                        "version": "1.0",
                        "thumbnail_url": "https://i.example/hq.jpg",
                        "thumbnail_width": 480,
                        "thumbnail_height": 360,
                        "html": "<iframe></iframe>",
                        "width": 200,
                        "height": 113,
                    }
                )
            ]
        )
        client = YouTubeClient(session=session, retries=0)  # type: ignore[arg-type]

        result = client.get_oembed("dQw4w9WgXcQ")

        self.assertEqual(result["title"], "Fixture oEmbed")
        self.assertEqual(result["author"]["name"], "Fixture creator")
        self.assertEqual(result["thumbnail"]["width"], 480)
        self.assertEqual(session.get_calls[0][0], "https://www.youtube.com/oembed")
        self.assertEqual(session.get_calls[0][1]["params"]["format"], "json")

    def test_429_and_5xx_retry_with_backoff(self) -> None:
        session = FakeSession(
            get=[page("rate", status=429), page("busy", status=502), page()]
        )
        client = YouTubeClient(session=session, retries=2)  # type: ignore[arg-type]

        with patch("reverse.youtube_reverse.client.time.sleep") as sleep:
            video = client.get_video("dQw4w9WgXcQ")

        self.assertEqual(video["id"], "dQw4w9WgXcQ")
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])
        self.assertEqual(len(session.get_calls), 3)

    def test_network_exception_retries_and_4xx_does_not_retry(self) -> None:
        recovering = FakeSession(
            get=[requests.exceptions.ConnectionError("fixture disconnect"), page()]
        )
        client = YouTubeClient(session=recovering, retries=1)  # type: ignore[arg-type]
        with patch("reverse.youtube_reverse.client.time.sleep") as sleep:
            self.assertEqual(client.get_video("dQw4w9WgXcQ")["id"], "dQw4w9WgXcQ")
        sleep.assert_called_once_with(0.4)

        rejected = FakeSession(get=[page("missing", status=404), page()])
        client = YouTubeClient(session=rejected, retries=3)  # type: ignore[arg-type]
        with self.assertRaisesRegex(YouTubeResponseError, "HTTP 404"):
            client.get_video("dQw4w9WgXcQ")
        self.assertEqual(len(rejected.get_calls), 1)

    def test_malformed_responses_and_video_mismatch_fail_cleanly(self) -> None:
        with self.assertRaisesRegex(YouTubeResponseError, "watch HTML is empty"):
            YouTubeClient.extract_player_response("")
        with self.assertRaisesRegex(YouTubeResponseError, "video ID mismatch"):
            YouTubeClient.parse_watch_html(
                FIXTURE, expected_video_id="aaaaaaaaaaa"
            )

        session = FakeSession(get=[FakeResponse(text="not-json")])
        client = YouTubeClient(session=session, retries=0)  # type: ignore[arg-type]
        with self.assertRaisesRegex(YouTubeResponseError, "not valid JSON"):
            client.get_oembed("dQw4w9WgXcQ")

        unavailable = {
            "playabilityStatus": {
                "status": "LOGIN_REQUIRED",
                "reason": "Sign in to confirm",
            }
        }
        with self.assertRaisesRegex(
            YouTubeResponseError, "LOGIN_REQUIRED: Sign in to confirm"
        ):
            YouTubeClient.normalize_player_response(unavailable)

    def test_caption_tracks_public_method_returns_compact_container(self) -> None:
        client = YouTubeClient(session=FakeSession(get=[page()]), retries=0)  # type: ignore[arg-type]

        result = client.get_caption_tracks("dQw4w9WgXcQ")

        self.assertEqual(result["video_id"], "dQw4w9WgXcQ")
        self.assertEqual(result["source"], "watch_html")
        self.assertEqual(result["total"], 2)
        self.assertNotIn("title", result)

    def test_search_collects_ssr_and_continuation_with_locale_contract(self) -> None:
        session = FakeSession(
            get=[page(SEARCH_FIXTURE)],
            post=[FakeResponse(payload=DISCOVERY_CONTINUATION)],
        )
        client = YouTubeClient(
            session=session, retries=0, language="zh-Hans", region="CN"  # type: ignore[arg-type]
        )

        result = client.search("fixture query", limit=4, continuation="")

        self.assertEqual(result["kind"], "search")
        self.assertEqual(result["requested_limit"], 4)
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["pages_fetched"], 2)
        self.assertFalse(result["has_more"])
        self.assertEqual(result["items"][-1]["id"], "DDDDDDDDDDD")
        get_url, get_kwargs = session.get_calls[0]
        self.assertEqual(get_url, "https://www.youtube.com/results")
        self.assertEqual(get_kwargs["params"]["search_query"], "fixture query")
        self.assertEqual(get_kwargs["params"]["hl"], "zh-Hans")
        self.assertEqual(get_kwargs["params"]["gl"], "CN")
        post_url, post_kwargs = session.post_calls[0]
        self.assertEqual(post_url, "https://www.youtube.com/youtubei/v1/search")
        self.assertEqual(post_kwargs["json"]["continuation"], "SEARCH_NEXT")
        self.assertEqual(post_kwargs["json"]["context"]["client"]["hl"], "zh-Hans")
        self.assertEqual(post_kwargs["json"]["context"]["client"]["gl"], "CN")
        self.assertEqual(post_kwargs["headers"]["X-Goog-Visitor-Id"], "fixture-discovery-visitor")

    def test_discovery_page_truncation_clears_cursor_instead_of_skipping_items(self) -> None:
        session = FakeSession(get=[page(SEARCH_FIXTURE)])
        client = YouTubeClient(session=session, retries=0)  # type: ignore[arg-type]

        result = client.search("fixture", limit=2)

        self.assertEqual(result["total"], 2)
        self.assertTrue(result["page_truncated"])
        self.assertFalse(result["has_more"])
        self.assertIsNone(result["next_cursor"])
        self.assertEqual(session.post_calls, [])

    def test_explicit_search_continuation_skips_initial_items(self) -> None:
        session = FakeSession(
            get=[page(SEARCH_FIXTURE)],
            post=[FakeResponse(payload=DISCOVERY_CONTINUATION)],
        )
        client = YouTubeClient(session=session, retries=0)  # type: ignore[arg-type]

        result = client.search("fixture", limit=5, continuation="EXPLICIT_CURSOR")

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["pages_fetched"], 1)
        self.assertEqual(result["items"][0]["id"], "DDDDDDDDDDD")
        self.assertEqual(session.post_calls[0][1]["json"]["continuation"], "EXPLICIT_CURSOR")

    def test_comments_use_main_cursor_and_preserve_reply_cursor(self) -> None:
        session = FakeSession(
            get=[page(COMMENTS_WATCH_FIXTURE)],
            post=[FakeResponse(payload=COMMENTS_PAGE)],
        )
        client = YouTubeClient(session=session, retries=0)  # type: ignore[arg-type]

        result = client.get_comments("dQw4w9WgXcQ", limit=2)

        self.assertEqual(result["kind"], "comments")
        self.assertEqual(result["count_text"], "2 comments")
        self.assertFalse(result["comments_disabled"])
        self.assertEqual(result["total"], 2)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_cursor"], "COMMENTS_NEXT")
        self.assertEqual(result["items"][0]["replies_cursor"], "REPLIES_CURSOR")
        post_url, post_kwargs = session.post_calls[0]
        self.assertEqual(post_url, "https://www.youtube.com/youtubei/v1/next")
        self.assertEqual(post_kwargs["json"]["continuation"], "COMMENTS_INITIAL")
        self.assertIn("watch?v=dQw4w9WgXcQ", post_kwargs["headers"]["Referer"])

    def test_missing_comment_continuation_reports_disabled_without_post(self) -> None:
        disabled = COMMENTS_WATCH_FIXTURE.replace(
            '"continuationCommand":{"token":"COMMENTS_INITIAL"}', '"noop":{}'
        )
        session = FakeSession(get=[page(disabled)])
        client = YouTubeClient(session=session, retries=0)  # type: ignore[arg-type]

        result = client.get_comments("dQw4w9WgXcQ", limit=5)

        self.assertTrue(result["comments_disabled"])
        self.assertEqual(result["items"], [])
        self.assertEqual(result["pages_fetched"], 0)
        self.assertEqual(session.post_calls, [])

    def test_channel_videos_normalizes_identity_and_browse_continuation(self) -> None:
        session = FakeSession(
            get=[page(CHANNEL_FIXTURE)],
            post=[FakeResponse(payload=DISCOVERY_CONTINUATION)],
        )
        client = YouTubeClient(session=session, retries=0)  # type: ignore[arg-type]

        result = client.get_channel_videos("@fixture-channel", limit=3)

        self.assertEqual(result["kind"], "channel_videos")
        self.assertEqual(result["channel"]["id"], "UCbbbbbbbbbbbbbbbbbbbbbb")
        self.assertEqual(result["channel"]["name"], "Fixture Channel")
        self.assertEqual(result["channel"]["handle"], "fixture-channel")
        self.assertEqual([item["id"] for item in result["items"]], [
            "BBBBBBBBBBB",
            "CCCCCCCCCCC",
            "DDDDDDDDDDD",
        ])
        self.assertEqual(session.get_calls[0][0], "https://www.youtube.com/@fixture-channel/videos")
        self.assertEqual(session.post_calls[0][0], "https://www.youtube.com/youtubei/v1/browse")
        self.assertEqual(session.post_calls[0][1]["json"]["continuation"], "CHANNEL_NEXT")

    def test_search_suggestions_supports_string_and_metadata_rows(self) -> None:
        payload = [
            "fixture",
            ["fixture one", ["fixture two", 0], "fixture one", "fixture three"],
        ]
        session = FakeSession(get=[FakeResponse(payload=payload)])
        client = YouTubeClient(
            session=session, retries=0, language="en-GB", region="GB"  # type: ignore[arg-type]
        )

        result = client.get_search_suggestions("fixture", limit=2)

        self.assertEqual(result["items"], ["fixture one", "fixture two"])
        self.assertTrue(result["page_truncated"])
        self.assertEqual(session.get_calls[0][0], "https://suggestqueries-clients6.youtube.com/complete/search")
        self.assertEqual(session.get_calls[0][1]["params"]["client"], "firefox")
        self.assertEqual(session.get_calls[0][1]["params"]["hl"], "en-GB")
        self.assertEqual(session.get_calls[0][1]["params"]["gl"], "GB")

        duplicate_session = FakeSession(
            get=[FakeResponse(payload=["fixture", ["same", "same"]])]
        )
        duplicate_result = YouTubeClient(
            session=duplicate_session, retries=0  # type: ignore[arg-type]
        ).get_search_suggestions("fixture", limit=10)
        self.assertEqual(duplicate_result["items"], ["same"])
        self.assertFalse(duplicate_result["page_truncated"])

    def test_trending_chart_uses_current_music_analytics_contract(self) -> None:
        session = FakeSession(post=[FakeResponse(payload=TRENDING_CHART)])
        client = YouTubeClient(
            session=session, retries=0, language="en-GB", region="US"  # type: ignore[arg-type]
        )

        result = client.get_trending_videos("Music", limit=2)

        self.assertEqual(result["kind"], "trending_videos")
        self.assertEqual(result["source"], "youtube_music_analytics_charts")
        self.assertEqual(result["transport"], "web_api")
        self.assertEqual(result["section"], "music")
        self.assertEqual(result["chart"], "Trending Music")
        self.assertEqual(result["chart_type"], "CHART_TYPE_TRENDING_VIDEOS")
        self.assertEqual(result["region"], "US")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["raw_count"], 3)
        self.assertEqual(result["available_count"], 2)
        self.assertTrue(result["has_more"])
        first = result["items"][0]
        self.assertEqual(first["rank"], 1)
        self.assertEqual(first["id"], "AAAAAAAAAAA")
        self.assertEqual(
            first["url"],
            "https://www.youtube.com/watch?v=AAAAAAAAAAA",
        )
        self.assertEqual(first["duration_seconds"], 170)
        self.assertEqual(first["release_date"], "2026-07-20")
        self.assertEqual(first["artists"][0]["id"], "/g/fixture-one")
        self.assertEqual(first["channel"]["id"], "UCaaaaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(
            first["channel"]["url"],
            "https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaa",
        )
        self.assertEqual(first["songwriters"], ["Writer One"])
        self.assertEqual(first["producers"], ["Producer One"])

        post_url, post_kwargs = session.post_calls[0]
        self.assertEqual(
            post_url,
            "https://charts.youtube.com/youtubei/v1/browse",
        )
        self.assertEqual(post_kwargs["params"], {"prettyPrint": "false"})
        self.assertEqual(
            post_kwargs["json"]["browseId"],
            "FEmusic_analytics_charts_home",
        )
        self.assertIn(
            "chart_params_chart_type=TRENDING_VIDEOS",
            post_kwargs["json"]["query"],
        )
        self.assertIn(
            "chart_params_country_code=us",
            post_kwargs["json"]["query"],
        )
        self.assertEqual(
            post_kwargs["json"]["context"]["client"],
            {
                "clientName": "WEB_MUSIC_ANALYTICS",
                "clientVersion": "2.0",
                "hl": "en-GB",
                "gl": "US",
            },
        )
        self.assertEqual(
            post_kwargs["headers"]["Referer"],
            "https://charts.youtube.com/charts/TrendingVideos/us/daily",
        )
        self.assertEqual(post_kwargs["headers"]["X-YouTube-Client-Name"], "31")

    def test_trending_movies_and_retired_sections_are_explicit(self) -> None:
        movies = json.loads(json.dumps(TRENDING_CHART))
        content = (
            movies["contents"]["sectionListRenderer"]["contents"][0]
            ["musicAnalyticsSectionRenderer"]["content"]
        )
        content["perspectiveMetadata"]["requestParams"]["chartParams"][
            "chartType"
        ] = "CHART_TYPE_TRENDING_MOVIES"
        session = FakeSession(post=[FakeResponse(payload=movies)])
        client = YouTubeClient(session=session, retries=0)  # type: ignore[arg-type]

        result = client.get_trending_videos("movies", limit=1)

        self.assertEqual(result["section"], "movies")
        self.assertEqual(result["chart"], "Trending Movie Trailers")
        self.assertIn(
            "chart_params_chart_type=TRENDING_MOVIES",
            session.post_calls[0][1]["json"]["query"],
        )
        self.assertIn(
            "/TrendingTrailers/us/daily",
            session.post_calls[0][1]["headers"]["Referer"],
        )

        offline = YouTubeClient(session=FakeSession(), retries=0)  # type: ignore[arg-type]
        for section in ("", "now", "gaming", "sports"):
            with self.subTest(section=section), self.assertRaises(YouTubeInputError):
                offline.get_trending_videos(section, limit=1)
        for limit in (0, 31, True):
            with self.subTest(limit=limit), self.assertRaises(YouTubeInputError):
                offline.get_trending_videos("music", limit=limit)  # type: ignore[arg-type]

    def test_trending_chart_rejects_protocol_drift(self) -> None:
        mismatched = json.loads(json.dumps(TRENDING_CHART))
        content = (
            mismatched["contents"]["sectionListRenderer"]["contents"][0]
            ["musicAnalyticsSectionRenderer"]["content"]
        )
        content["perspectiveMetadata"]["requestParams"]["chartParams"][
            "chartType"
        ] = "CHART_TYPE_VIDEOS"
        client = YouTubeClient(
            session=FakeSession(post=[FakeResponse(payload=mismatched)]),
            retries=0,
        )  # type: ignore[arg-type]
        with self.assertRaisesRegex(YouTubeResponseError, "chart type"):
            client.get_trending_videos("music")

        missing = YouTubeClient(
            session=FakeSession(post=[FakeResponse(payload={"contents": {}})]),
            retries=0,
        )  # type: ignore[arg-type]
        with self.assertRaisesRegex(YouTubeResponseError, "video chart"):
            missing.get_trending_videos("music")

    def test_discovery_limits_and_continuation_are_bounded_before_network(self) -> None:
        client = YouTubeClient(session=FakeSession(), retries=0)  # type: ignore[arg-type]
        calls = [
            lambda: client.search("", limit=1),
            lambda: client.search("fixture", limit=0),
            lambda: client.get_comments("dQw4w9WgXcQ", limit=101),
            lambda: client.get_channel_videos("@fixture", continuation="bad token"),
            lambda: client.get_channel_videos("@fixture", continuation="bad\u00a0token"),
            lambda: client.get_search_suggestions("fixture", limit=51),
        ]
        for call in calls:
            with self.subTest(call=call), self.assertRaises(YouTubeInputError):
                call()

    def test_repeated_continuation_is_reported_as_stalled(self) -> None:
        payload = YouTubeClient.extract_initial_data(SEARCH_FIXTURE)
        result = YouTubeClient(session=FakeSession(), retries=0)._collect_pages(  # type: ignore[arg-type]
            initial_payload=payload,
            initial_cursor="",
            limit=10,
            parser=YouTubeClient.normalize_discovery_items,
            item_key=lambda item: (item["type"], item["id"]),
            fetch=lambda _token: payload,
        )
        self.assertTrue(result["cursor_stalled"])
        self.assertFalse(result["has_more"])
        self.assertIsNone(result["next_cursor"])
        self.assertEqual(result["pages_fetched"], 2)

    def test_cli_wires_all_discovery_commands(self) -> None:
        cases = [
            (
                ["--language", "zh-Hans", "--region", "CN", "search", "open ai", "--limit", "3", "--continuation", "TOKEN"],
                "search",
                ("open ai",),
                {"limit": 3, "continuation": "TOKEN"},
            ),
            (
                ["comments", "dQw4w9WgXcQ", "--limit", "4"],
                "get_comments",
                ("dQw4w9WgXcQ",),
                {"limit": 4, "continuation": None},
            ),
            (
                ["channel-videos", "@fixture", "--continuation", "NEXT"],
                "get_channel_videos",
                ("@fixture",),
                {"limit": 20, "continuation": "NEXT"},
            ),
            (
                ["search-suggest", "fixture", "--limit", "2"],
                "get_search_suggestions",
                ("fixture",),
                {"limit": 2},
            ),
            (
                ["--region", "GB", "trending", "movies", "--limit", "12"],
                "get_trending_videos",
                ("movies",),
                {"limit": 12},
            ),
        ]
        for argv, method, positional, keyword in cases:
            with self.subTest(command=argv[0]), patch(
                "reverse.youtube_reverse.cli.YouTubeClient"
            ) as client_type:
                getattr(client_type.return_value, method).return_value = {"ok": True}
                result = _run(_parser().parse_args(argv))
                self.assertEqual(result, {"ok": True})
                getattr(client_type.return_value, method).assert_called_once_with(
                    *positional, **keyword
                )


if __name__ == "__main__":
    unittest.main()
