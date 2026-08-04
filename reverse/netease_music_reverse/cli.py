from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import NeteaseMusicClient
from .errors import NeteaseMusicError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="NetEase Cloud Music 匿名公开数据客户端"
    )
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    song = commands.add_parser("song", help="查询单首公开歌曲")
    song.add_argument("song_url_or_id")

    songs = commands.add_parser("songs", help="批量查询公开歌曲")
    songs.add_argument("song_urls_or_ids", nargs="+")
    songs.add_argument("--batch-size", type=int, default=200)

    playlist = commands.add_parser("playlist", help="查询公开歌单及其曲目")
    playlist.add_argument("playlist_url_or_id")
    playlist.add_argument("--limit", type=int)
    playlist.add_argument("--batch-size", type=int, default=200)
    playlist.add_argument("--metadata-only", action="store_true")

    tracks = commands.add_parser("playlist-tracks", help="查询公开歌单曲目")
    tracks.add_argument("playlist_url_or_id")
    tracks.add_argument("--limit", type=int)
    tracks.add_argument("--batch-size", type=int, default=200)

    album = commands.add_parser("album", help="查询公开专辑及其歌曲")
    album.add_argument("album_url_or_id")

    artist = commands.add_parser("artist", help="查询公开艺人及热门歌曲")
    artist.add_argument("artist_url_or_id")

    albums = commands.add_parser("artist-albums", help="查询艺人的公开专辑")
    albums.add_argument("artist_url_or_id")
    albums.add_argument("--limit", type=int, default=50)
    albums.add_argument("--page-size", type=int, default=50)

    search = commands.add_parser("search", help="搜索公开音乐数据")
    search.add_argument("keyword")
    search.add_argument("--type", dest="search_type", choices=("song", "album", "artist", "playlist"), default="song")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--page-size", type=int, default=30)
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = NeteaseMusicClient(timeout=args.timeout)
    if args.command == "song":
        return client.get_song(args.song_url_or_id)
    if args.command == "songs":
        return client.get_songs(args.song_urls_or_ids, batch_size=args.batch_size)
    if args.command == "playlist":
        return client.get_playlist(
            args.playlist_url_or_id,
            include_tracks=not args.metadata_only,
            limit=args.limit,
            batch_size=args.batch_size,
        )
    if args.command == "playlist-tracks":
        return client.get_playlist_tracks(
            args.playlist_url_or_id,
            limit=args.limit,
            batch_size=args.batch_size,
        )
    if args.command == "album":
        return client.get_album(args.album_url_or_id)
    if args.command == "artist":
        return client.get_artist(args.artist_url_or_id)
    if args.command == "artist-albums":
        return client.get_artist_albums(
            args.artist_url_or_id,
            limit=args.limit,
            page_size=args.page_size,
        )
    return client.search(
        args.keyword,
        search_type=args.search_type,
        limit=args.limit,
        page_size=args.page_size,
    )


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except NeteaseMusicError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
