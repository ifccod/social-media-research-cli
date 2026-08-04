from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

from curl_cffi import requests

from reverse.netease_music_reverse.client import NeteaseMusicClient
from reverse.netease_music_reverse.errors import NeteaseMusicInputError, NeteaseMusicResponseError


class FakeResponse:
    def __init__(self, payload: Any, *, status: int = 200) -> None:
        self.payload = payload
        self.status_code = status

    def json(self) -> Any:
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(
        self,
        *,
        get: list[FakeResponse | BaseException] | None = None,
        post: list[FakeResponse | BaseException] | None = None,
    ) -> None:
        self.headers: dict[str, str] = {}
        self.get_responses = list(get or [])
        self.post_responses = list(post or [])
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.get_calls.append((url, kwargs))
        return self._next(self.get_responses)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append((url, kwargs))
        return self._next(self.post_responses)

    @staticmethod
    def _next(queue: list[FakeResponse | BaseException]) -> FakeResponse:
        if not queue:
            raise AssertionError("unexpected fake HTTP request")
        value = queue.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def response(payload: Mapping[str, Any], *, status: int = 200) -> FakeResponse:
    return FakeResponse(dict(payload), status=status)


def raw_song(song_id: int, name: str = "fixture") -> dict[str, Any]:
    return {
        "id": song_id,
        "name": name,
        "alias": ["alias"],
        "duration": 123456,
        "artists": [{"id": 7, "name": "Artist", "alias": ["A"]}],
        "album": {"id": 8, "name": "Album", "picUrl": "cover"},
        "popularity": 99.5,
        "fee": 1,
        "status": 0,
        "copyrightId": 10,
        "mvid": 11,
        "hMusic": {
            "bitrate": 320000,
            "size": 123,
            "sr": 44100,
            "extension": "mp3",
        },
    }


class NeteaseMusicClientTest(unittest.TestCase):
    def test_resolve_ids_accepts_plain_and_canonical_urls(self) -> None:
        self.assertEqual(NeteaseMusicClient._resolve_id("347230", "song"), "347230")
        self.assertEqual(
            NeteaseMusicClient._resolve_id("https://music.163.com/song?id=347230", "song"),
            "347230",
        )
        self.assertEqual(
            NeteaseMusicClient._resolve_id("https://music.163.com/#/playlist?id=19723756", "playlist"),
            "19723756",
        )
        self.assertEqual(
            NeteaseMusicClient._resolve_id("music.163.com/album/34720827", "album"),
            "34720827",
        )
        with self.assertRaises(NeteaseMusicInputError):
            NeteaseMusicClient._resolve_id("https://music.163.com/artist?id=6452", "album")
        with self.assertRaises(NeteaseMusicInputError):
            NeteaseMusicClient._resolve_id("https://music.163.com.example/song?id=1", "song")
        with self.assertRaises(NeteaseMusicInputError):
            NeteaseMusicClient._resolve_id("0", "song")

    def test_song_detail_normalizes_legacy_fields_and_headers(self) -> None:
        session = FakeSession(get=[response({"code": 200, "songs": [raw_song(347230)]})])
        client = NeteaseMusicClient(session=session, retries=0)

        song = client.get_song("https://music.163.com/song?id=347230")

        self.assertEqual(song["id"], "347230")
        self.assertEqual(song["duration_ms"], 123456)
        self.assertEqual(song["artists"][0]["name"], "Artist")
        self.assertEqual(song["album"]["cover_url"], "cover")
        self.assertEqual(song["qualities"]["exhigh"]["bitrate"], 320000)
        self.assertEqual(session.headers["Referer"], "https://music.163.com/")
        self.assertEqual(session.get_calls[0][0], "https://music.163.com/api/song/detail/")
        self.assertEqual(json.loads(session.get_calls[0][1]["params"]["ids"]), [347230])

    def test_multiple_song_batches_preserve_order_and_report_missing(self) -> None:
        session = FakeSession(
            get=[
                response({"code": 200, "songs": [raw_song(2), raw_song(1)]}),
                response({"code": 200, "songs": [raw_song(4)]}),
            ]
        )
        client = NeteaseMusicClient(session=session, retries=0)

        result = client.get_songs([1, 2, 2, 3, 4], batch_size=3)

        self.assertEqual(result["requested_ids"], ["1", "2", "3", "4"])
        self.assertEqual([song["id"] for song in result["songs"]], ["1", "2", "4"])
        self.assertEqual(result["missing_ids"], ["3"])
        self.assertEqual(len(session.get_calls), 2)

    def test_playlist_fills_missing_tracks_and_preserves_playlist_order(self) -> None:
        session = FakeSession(
            get=[
                response(
                    {
                        "code": 200,
                        "playlist": {
                            "id": 99,
                            "name": "Playlist",
                            "trackCount": 4,
                            "creator": {"userId": 8, "nickname": "Owner"},
                            "trackIds": [{"id": 3}, {"id": 1}, {"id": 2}, {"id": 4}],
                            "tracks": [raw_song(1), raw_song(3)],
                        },
                    }
                ),
                response({"code": 200, "songs": [raw_song(2), raw_song(4)]}),
            ]
        )
        client = NeteaseMusicClient(session=session, retries=0)

        playlist = client.get_playlist(99)

        self.assertEqual(playlist["creator"]["nickname"], "Owner")
        self.assertEqual(playlist["track_ids"], ["3", "1", "2", "4"])
        self.assertEqual([song["id"] for song in playlist["tracks"]], ["3", "1", "2", "4"])
        self.assertEqual(playlist["unavailable_track_ids"], [])
        self.assertEqual(
            json.loads(session.get_calls[1][1]["params"]["ids"]),
            [2, 4],
        )

    def test_playlist_metadata_only_does_not_fetch_missing_tracks(self) -> None:
        session = FakeSession(
            get=[
                response(
                    {
                        "code": 200,
                        "playlist": {
                            "id": 99,
                            "name": "Playlist",
                            "trackCount": 2,
                            "trackIds": [{"id": 1}, {"id": 2}],
                            "tracks": [],
                        },
                    }
                )
            ]
        )
        client = NeteaseMusicClient(session=session, retries=0)

        playlist = client.get_playlist(99, include_tracks=False, limit=1)

        self.assertFalse(playlist["tracks_included"])
        self.assertEqual(playlist["track_ids"], ["1"])
        self.assertEqual(playlist["tracks"], [])
        self.assertEqual(len(session.get_calls), 1)

    def test_album_and_artist_responses_are_normalized(self) -> None:
        session = FakeSession(
            get=[
                response(
                    {
                        "code": 200,
                        "album": {
                            "id": 8,
                            "name": "Album",
                            "size": 1,
                            "artists": [{"id": 7, "name": "Artist"}],
                            "songs": [raw_song(1)],
                        },
                    }
                ),
                response(
                    {
                        "code": 200,
                        "artist": {"id": 7, "name": "Artist", "musicSize": 10},
                        "hotSongs": [raw_song(1)],
                    }
                ),
            ]
        )
        client = NeteaseMusicClient(session=session, retries=0)

        album = client.get_album(8)
        artist = client.get_artist(7)

        self.assertEqual(album["total"], 1)
        self.assertEqual(album["songs"][0]["id"], "1")
        self.assertEqual(artist["artist"]["music_count"], 10)
        self.assertEqual(artist["hot_song_count"], 1)

    def test_artist_album_pagination_deduplicates(self) -> None:
        session = FakeSession(
            get=[
                response(
                    {
                        "code": 200,
                        "artist": {"id": 7, "name": "Artist"},
                        "hotAlbums": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
                        "more": True,
                    }
                ),
                response(
                    {
                        "code": 200,
                        "artist": {"id": 7, "name": "Artist"},
                        "hotAlbums": [{"id": 2, "name": "B"}, {"id": 3, "name": "C"}],
                        "more": False,
                    }
                ),
            ]
        )
        client = NeteaseMusicClient(session=session, retries=0)

        result = client.get_artist_albums(7, limit=3, page_size=2)

        self.assertEqual([album["id"] for album in result["albums"]], ["1", "2", "3"])
        self.assertEqual(session.get_calls[0][1]["params"]["offset"], "0")
        self.assertEqual(session.get_calls[1][1]["params"]["offset"], "2")

    def test_search_posts_legacy_form_and_paginates(self) -> None:
        session = FakeSession(
            post=[
                response(
                    {
                        "code": 200,
                        "result": {"songs": [raw_song(1), raw_song(2)], "songCount": 4},
                    }
                ),
                response(
                    {
                        "code": 200,
                        "result": {"songs": [raw_song(2), raw_song(3)], "songCount": 4},
                    }
                ),
            ]
        )
        client = NeteaseMusicClient(session=session, retries=0)

        result = client.search("fixture", limit=3, page_size=2)

        self.assertEqual([song["id"] for song in result["items"]], ["1", "2", "3"])
        self.assertEqual(session.post_calls[0][0], "https://music.163.com/api/search/get/web")
        self.assertEqual(session.post_calls[0][1]["data"]["type"], "1")
        self.assertEqual(session.post_calls[1][1]["data"]["offset"], "2")

    def test_transient_failures_retry_with_backoff(self) -> None:
        session = FakeSession(
            get=[
                requests.exceptions.ConnectionError("connection fixture"),
                response({}, status=503),
                response({"code": 200, "songs": [raw_song(1)]}),
            ]
        )
        client = NeteaseMusicClient(session=session, retries=2)

        with patch("reverse.netease_music_reverse.client.time.sleep") as sleep:
            song = client.get_song(1)

        self.assertEqual(song["id"], "1")
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])

    def test_deterministic_http_api_and_json_errors_are_reported(self) -> None:
        cases = [
            (FakeSession(get=[response({}, status=404)]), "HTTP 404"),
            (FakeSession(get=[response({"code": 404, "message": "not found"})]), "API code 404"),
            (FakeSession(get=[FakeResponse(ValueError("bad json"))]), "invalid JSON"),
        ]
        for session, message in cases:
            with self.subTest(message=message):
                client = NeteaseMusicClient(session=session, retries=0)
                with self.assertRaisesRegex(NeteaseMusicResponseError, message):
                    client.get_song(1)

    def test_input_limits_and_search_types_are_validated(self) -> None:
        client = NeteaseMusicClient(session=FakeSession(), retries=0)
        empty = client.get_artist_albums(1, limit=0)
        self.assertEqual(empty["albums"], [])
        self.assertFalse(empty["has_more"])
        with self.assertRaises(NeteaseMusicInputError):
            client.get_playlist(1, limit=-1)
        with self.assertRaises(NeteaseMusicInputError):
            client.get_songs([1], batch_size=0)
        with self.assertRaises(NeteaseMusicInputError):
            client.search("", search_type="song")
        with self.assertRaises(NeteaseMusicInputError):
            client.search("x", search_type="user")


if __name__ == "__main__":
    unittest.main()
