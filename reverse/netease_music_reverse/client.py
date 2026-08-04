from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import parse_qs, urlsplit

from curl_cffi import requests

from .errors import NeteaseMusicInputError, NeteaseMusicResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

_API_BASE = "https://music.163.com"
_SEARCH_TYPES = {
    "song": (1, "songs", "songCount"),
    "album": (10, "albums", "albumCount"),
    "artist": (100, "artists", "artistCount"),
    "playlist": (1000, "playlists", "playlistCount"),
}


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _number(value: Any) -> int | float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0
    return int(number) if number.is_integer() else number


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _strings(value: Any) -> list[str]:
    result: list[str] = []
    for item in _list(value):
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


class NeteaseMusicClient:
    """面向稳定、未加密 NetEase Cloud Music API 的匿名客户端。"""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 20,
        retries: int = 2,
    ) -> None:
        self.session = session or requests.Session(impersonate="chrome")
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = max(0, retries)
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://music.163.com/",
                "User-Agent": user_agent,
            }
        )

    def get_song(self, song_url_or_id: str | int) -> dict[str, Any]:
        song_id = self._resolve_id(song_url_or_id, "song")
        result = self.get_songs([song_id])
        if not result["songs"]:
            raise NeteaseMusicResponseError(f"song {song_id} was not returned")
        return result["songs"][0]

    def get_songs(
        self,
        song_urls_or_ids: Iterable[str | int],
        *,
        batch_size: int = 200,
    ) -> dict[str, Any]:
        if isinstance(song_urls_or_ids, (str, bytes, bytearray)):
            raise NeteaseMusicInputError("song_urls_or_ids must be an iterable of song references")
        batch_size = self._positive_size(batch_size, "batch_size", maximum=200)
        song_ids: list[str] = []
        for value in song_urls_or_ids:
            song_id = self._resolve_id(value, "song")
            if song_id not in song_ids:
                song_ids.append(song_id)
        raw_songs = self._get_songs_raw(song_ids, batch_size=batch_size)
        by_id = {str(item.get("id") or ""): item for item in raw_songs}
        songs = [self._normalize_song(by_id[song_id]) for song_id in song_ids if song_id in by_id]
        return {
            "requested_ids": song_ids,
            "total": len(songs),
            "missing_ids": [song_id for song_id in song_ids if song_id not in by_id],
            "songs": songs,
        }

    def get_playlist(
        self,
        playlist_url_or_id: str | int,
        *,
        include_tracks: bool = True,
        limit: int | None = None,
        batch_size: int = 200,
    ) -> dict[str, Any]:
        playlist_id = self._resolve_id(playlist_url_or_id, "playlist")
        self._validate_limit(limit)
        batch_size = self._positive_size(batch_size, "batch_size", maximum=200)
        payload = self._get(
            "/api/v6/playlist/detail",
            params={"id": playlist_id, "n": "100000", "s": "0"},
        )
        raw_playlist = _mapping(payload.get("playlist"))
        if not raw_playlist or not raw_playlist.get("id"):
            raise NeteaseMusicResponseError("playlist response does not contain a playlist")

        raw_tracks = [item for item in _list(raw_playlist.get("tracks")) if isinstance(item, Mapping)]
        track_ids = self._playlist_track_ids(raw_playlist, raw_tracks)
        selected_ids = track_ids if limit is None else track_ids[:limit]
        normalized = self._normalize_playlist(raw_playlist)
        normalized["track_ids"] = selected_ids
        normalized["tracks_included"] = bool(include_tracks)
        normalized["tracks"] = []
        normalized["unavailable_track_ids"] = []
        normalized["total"] = 0
        if not include_tracks or not selected_ids:
            return normalized

        raw_by_id = {str(item.get("id") or ""): item for item in raw_tracks}
        missing = [song_id for song_id in selected_ids if song_id not in raw_by_id]
        for item in self._get_songs_raw(missing, batch_size=batch_size):
            raw_by_id[str(item.get("id") or "")] = item
        normalized["tracks"] = [
            self._normalize_song(raw_by_id[song_id])
            for song_id in selected_ids
            if song_id in raw_by_id
        ]
        normalized["unavailable_track_ids"] = [
            song_id for song_id in selected_ids if song_id not in raw_by_id
        ]
        normalized["total"] = len(normalized["tracks"])
        return normalized

    def get_playlist_tracks(
        self,
        playlist_url_or_id: str | int,
        *,
        limit: int | None = None,
        batch_size: int = 200,
    ) -> dict[str, Any]:
        playlist = self.get_playlist(
            playlist_url_or_id,
            include_tracks=True,
            limit=limit,
            batch_size=batch_size,
        )
        return {
            "playlist_id": playlist["id"],
            "playlist_name": playlist["name"],
            "track_count": playlist["track_count"],
            "total": playlist["total"],
            "track_ids": playlist["track_ids"],
            "unavailable_track_ids": playlist["unavailable_track_ids"],
            "tracks": playlist["tracks"],
        }

    def get_album(self, album_url_or_id: str | int) -> dict[str, Any]:
        album_id = self._resolve_id(album_url_or_id, "album")
        payload = self._get(f"/api/album/{album_id}")
        raw_album = _mapping(payload.get("album"))
        if not raw_album or not raw_album.get("id"):
            raise NeteaseMusicResponseError("album response does not contain an album")
        songs_value = payload.get("songs")
        if not isinstance(songs_value, Sequence) or isinstance(songs_value, (str, bytes, bytearray)):
            songs_value = raw_album.get("songs")
        songs = [
            self._normalize_song(item)
            for item in _list(songs_value)
            if isinstance(item, Mapping)
        ]
        result = self._normalize_album(raw_album)
        result["songs"] = songs
        result["total"] = len(songs)
        return result

    def get_artist(self, artist_url_or_id: str | int) -> dict[str, Any]:
        artist_id = self._resolve_id(artist_url_or_id, "artist")
        payload = self._get(f"/api/artist/{artist_id}")
        raw_artist = _mapping(payload.get("artist"))
        if not raw_artist or not raw_artist.get("id"):
            raise NeteaseMusicResponseError("artist response does not contain an artist")
        hot_songs = [
            self._normalize_song(item)
            for item in _list(payload.get("hotSongs"))
            if isinstance(item, Mapping)
        ]
        return {
            "artist": self._normalize_artist(raw_artist),
            "hot_song_count": len(hot_songs),
            "hot_songs": hot_songs,
        }

    def get_artist_albums(
        self,
        artist_url_or_id: str | int,
        *,
        limit: int | None = 50,
        page_size: int = 50,
    ) -> dict[str, Any]:
        artist_id = self._resolve_id(artist_url_or_id, "artist")
        self._validate_limit(limit)
        page_size = self._positive_size(page_size, "page_size", maximum=100)
        albums: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        offset = 0
        more = limit != 0
        artist: dict[str, Any] = {"id": artist_id}

        while more and (limit is None or len(albums) < limit):
            count = page_size if limit is None else min(page_size, limit - len(albums))
            payload = self._get(
                f"/api/artist/albums/{artist_id}",
                params={"offset": str(offset), "limit": str(count)},
            )
            raw_artist = _mapping(payload.get("artist"))
            if raw_artist:
                artist = self._normalize_artist(raw_artist)
            items = [item for item in _list(payload.get("hotAlbums")) if isinstance(item, Mapping)]
            for item in items:
                album_id = str(item.get("id") or "")
                if not album_id or album_id in seen_ids:
                    continue
                seen_ids.add(album_id)
                albums.append(self._normalize_album(item))
                if limit is not None and len(albums) >= limit:
                    break
            offset += len(items)
            more = bool(payload.get("more"))
            if not items:
                more = False

        return {
            "artist": artist,
            "total": len(albums),
            "offset": offset,
            "has_more": more,
            "albums": albums,
        }

    def search(
        self,
        keyword: str,
        *,
        search_type: str = "song",
        limit: int | None = 20,
        page_size: int = 30,
    ) -> dict[str, Any]:
        keyword = str(keyword or "").strip()
        if not keyword:
            raise NeteaseMusicInputError("keyword must not be empty")
        if search_type not in _SEARCH_TYPES:
            expected = ", ".join(sorted(_SEARCH_TYPES))
            raise NeteaseMusicInputError(f"search_type must be one of: {expected}")
        self._validate_limit(limit)
        page_size = self._positive_size(page_size, "page_size", maximum=100)
        type_code, items_key, total_key = _SEARCH_TYPES[search_type]
        items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        offset = 0
        total_available = 0
        has_more = bool(limit)

        while limit is None or len(items) < limit:
            count = page_size if limit is None else min(page_size, limit - len(items))
            payload = self._post(
                "/api/search/get/web",
                data={
                    "s": keyword,
                    "type": str(type_code),
                    "offset": str(offset),
                    "limit": str(count),
                },
            )
            result = _mapping(payload.get("result"))
            raw_items = [item for item in _list(result.get(items_key)) if isinstance(item, Mapping)]
            total_available = _integer(result.get(total_key))
            for item in raw_items:
                item_id = str(item.get("id") or "")
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                items.append(self._normalize_search_item(search_type, item))
                if limit is not None and len(items) >= limit:
                    break
            offset += len(raw_items)
            has_more = bool(raw_items) and offset < total_available
            if not raw_items or len(raw_items) < count or not has_more:
                break

        return {
            "keyword": keyword,
            "type": search_type,
            "total_available": total_available,
            "total": len(items),
            "offset": offset,
            "has_more": has_more,
            "items": items,
        }

    def _get_songs_raw(self, song_ids: Sequence[str], *, batch_size: int) -> list[Mapping[str, Any]]:
        songs: list[Mapping[str, Any]] = []
        for start in range(0, len(song_ids), batch_size):
            batch = list(song_ids[start : start + batch_size])
            payload = self._get(
                "/api/song/detail/",
                params={"ids": json.dumps([int(song_id) for song_id in batch], separators=(",", ":"))},
            )
            items = payload.get("songs")
            if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
                raise NeteaseMusicResponseError("song detail response songs is not a list")
            songs.extend(item for item in items if isinstance(item, Mapping))
        return songs

    def _get(self, path: str, *, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        return self._request("GET", path, params=params)

    def _post(self, path: str, *, data: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._request("POST", path, data=data)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        url = f"{_API_BASE}{path}"
        for attempt in range(self.retries + 1):
            try:
                if method == "POST":
                    response = self.session.post(url, data=data, timeout=self.timeout)
                else:
                    response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.exceptions.RequestException as exc:
                if attempt >= self.retries:
                    raise NeteaseMusicResponseError(f"{method} {path} failed: {exc}") from exc
                time.sleep(0.4 * (2**attempt))
                continue

            status = _integer(getattr(response, "status_code", 0))
            if status == 429 or status >= 500:
                if attempt < self.retries:
                    time.sleep(0.4 * (2**attempt))
                    continue
            if status < 200 or status >= 300:
                raise NeteaseMusicResponseError(f"{method} {path} returned HTTP {status}")
            try:
                payload = response.json()
            except (TypeError, ValueError) as exc:
                raise NeteaseMusicResponseError(f"{method} {path} returned invalid JSON") from exc
            if not isinstance(payload, Mapping):
                raise NeteaseMusicResponseError(f"{method} {path} returned a non-object payload")
            code = _integer(payload.get("code", 200))
            if code != 200:
                message = payload.get("message") or payload.get("msg") or "unknown API error"
                raise NeteaseMusicResponseError(f"{method} {path} returned API code {code}: {message}")
            return payload
        raise NeteaseMusicResponseError(f"{method} {path} exhausted retries")

    @staticmethod
    def _resolve_id(value: str | int, kind: str) -> str:
        text = str(value).strip()
        if text.isdigit():
            if int(text) <= 0:
                raise NeteaseMusicInputError(f"{kind} id must be positive")
            return text
        parsed = urlsplit(text if "://" in text else f"https://{text}")
        hostname = (parsed.hostname or "").lower()
        if hostname != "music.163.com" and not hostname.endswith(".music.163.com"):
            raise NeteaseMusicInputError(f"{kind} URL must use a music.163.com host")
        route = urlsplit(parsed.fragment) if parsed.fragment else parsed
        path_parts = [part.lower() for part in route.path.split("/") if part]
        if kind not in path_parts:
            raise NeteaseMusicInputError(f"URL is not a NetEase Cloud Music {kind} URL")
        query_id = (parse_qs(route.query).get("id") or parse_qs(parsed.query).get("id") or [""])[0]
        if not query_id and path_parts and path_parts[-1].isdigit():
            query_id = path_parts[-1]
        if not str(query_id).isdigit() or int(query_id) <= 0:
            raise NeteaseMusicInputError(f"{kind} URL does not contain a positive id")
        return str(query_id)

    @staticmethod
    def _positive_size(value: int, name: str, *, maximum: int) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise NeteaseMusicInputError(f"{name} must be an integer") from exc
        if result <= 0:
            raise NeteaseMusicInputError(f"{name} must be positive")
        return min(result, maximum)

    @staticmethod
    def _validate_limit(limit: int | None) -> None:
        if limit is not None and limit < 0:
            raise NeteaseMusicInputError("limit must be non-negative")

    @staticmethod
    def _playlist_track_ids(
        playlist: Mapping[str, Any],
        raw_tracks: Sequence[Mapping[str, Any]],
    ) -> list[str]:
        result: list[str] = []
        for item in _list(playlist.get("trackIds")):
            song_id = str(_mapping(item).get("id") if isinstance(item, Mapping) else item or "")
            if song_id.isdigit() and song_id not in result:
                result.append(song_id)
        if result:
            return result
        for item in raw_tracks:
            song_id = str(item.get("id") or "")
            if song_id.isdigit() and song_id not in result:
                result.append(song_id)
        return result

    @classmethod
    def _normalize_song(cls, item: Mapping[str, Any]) -> dict[str, Any]:
        artists_value = item.get("ar") if isinstance(item.get("ar"), Sequence) else item.get("artists")
        album_value = item.get("al") if isinstance(item.get("al"), Mapping) else item.get("album")
        aliases = _strings(item.get("alia") or item.get("alias"))
        for alias in _strings(item.get("transNames")):
            if alias not in aliases:
                aliases.append(alias)
        return {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "aliases": aliases,
            "duration_ms": _integer(item.get("dt", item.get("duration"))),
            "artists": [
                cls._normalize_artist(artist)
                for artist in _list(artists_value)
                if isinstance(artist, Mapping)
            ],
            "album": cls._normalize_album(_mapping(album_value)),
            "popularity": _number(item.get("pop", item.get("popularity"))),
            "fee": _integer(item.get("fee")),
            "status": _integer(item.get("st", item.get("status"))),
            "copyright_id": _integer(item.get("copyrightId")),
            "mv_id": str(item.get("mv", item.get("mvid")) or ""),
            "qualities": cls._normalize_qualities(item),
        }

    @staticmethod
    def _normalize_artist(item: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "aliases": _strings(item.get("alias")),
            "picture_url": item.get("picUrl") or None,
            "avatar_url": item.get("img1v1Url") or None,
            "brief_description": str(item.get("briefDesc") or ""),
            "music_count": _integer(item.get("musicSize")),
            "album_count": _integer(item.get("albumSize")),
            "mv_count": _integer(item.get("mvSize")),
            "followed": bool(item.get("followed")),
        }

    @classmethod
    def _normalize_album(cls, item: Mapping[str, Any]) -> dict[str, Any]:
        artists_value = item.get("artists")
        if not isinstance(artists_value, Sequence) or isinstance(artists_value, (str, bytes, bytearray)):
            artist = item.get("artist")
            artists_value = [artist] if isinstance(artist, Mapping) else []
        return {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "aliases": _strings(item.get("alias")),
            "type": str(item.get("type") or ""),
            "sub_type": str(item.get("subType") or ""),
            "size": _integer(item.get("size")),
            "cover_url": item.get("picUrl") or item.get("blurPicUrl") or None,
            "publish_time": _integer(item.get("publishTime")),
            "company": str(item.get("company") or ""),
            "description": str(item.get("description") or ""),
            "artists": [
                cls._normalize_artist(artist)
                for artist in _list(artists_value)
                if isinstance(artist, Mapping)
            ],
        }

    @staticmethod
    def _normalize_playlist(item: Mapping[str, Any]) -> dict[str, Any]:
        creator = _mapping(item.get("creator"))
        return {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "description": str(item.get("description") or ""),
            "cover_url": item.get("coverImgUrl") or None,
            "track_count": _integer(item.get("trackCount")),
            "play_count": _integer(item.get("playCount")),
            "subscribed_count": _integer(item.get("subscribedCount")),
            "create_time": _integer(item.get("createTime")),
            "update_time": _integer(item.get("updateTime")),
            "privacy": _integer(item.get("privacy")),
            "tags": _strings(item.get("tags")),
            "creator": {
                "id": str(creator.get("userId") or ""),
                "nickname": str(creator.get("nickname") or ""),
                "avatar_url": creator.get("avatarUrl") or None,
            },
        }

    @staticmethod
    def _normalize_qualities(item: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        field_names = {
            "standard": ("l", "lMusic"),
            "higher": ("m", "mMusic"),
            "exhigh": ("h", "hMusic"),
            "lossless": ("sq", "sqMusic"),
            "hires": ("hr", "hrMusic"),
        }
        result: dict[str, dict[str, Any]] = {}
        for name, candidates in field_names.items():
            quality: Mapping[str, Any] = {}
            for field in candidates:
                if isinstance(item.get(field), Mapping):
                    quality = _mapping(item.get(field))
                    break
            if not quality:
                continue
            result[name] = {
                "bitrate": _integer(quality.get("br", quality.get("bitrate"))),
                "size": _integer(quality.get("size")),
                "sample_rate": _integer(quality.get("sr")),
                "extension": str(quality.get("extension") or ""),
            }
        return result

    @classmethod
    def _normalize_search_item(cls, search_type: str, item: Mapping[str, Any]) -> dict[str, Any]:
        if search_type == "song":
            return cls._normalize_song(item)
        if search_type == "album":
            return cls._normalize_album(item)
        if search_type == "artist":
            return cls._normalize_artist(item)
        return cls._normalize_playlist(item)
