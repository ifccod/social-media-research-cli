from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .client import PinterestAdsClient
from .errors import PinterestAdsError, PinterestAdsInputError


def _add_bookmark(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bookmark", default="", help="从官方 opaque bookmark 继续")
    parser.add_argument("--page-size", type=int, default=50, help="官方单次请求条目数；最大 100")
    parser.add_argument("--limit", type=int, default=100, help="本次最多返回的去重条目数")
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="在归一化条目中保留官方原始字段",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pinterest Ads Repository、Lens 与公开 Pin 匿名素材客户端"
    )
    parser.add_argument("--timeout", type=float, default=30, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败重试次数")
    parser.add_argument(
        "--request-interval",
        type=float,
        default=0.5,
        help="同一 Pinterest 平台族请求之间的最小秒数",
    )
    parser.add_argument("--proxy", default="", help="可选的本机 http 或 https 代理 URL")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    visual = commands.add_parser(
        "visual-search",
        help="匿名上传本机商品图，以图搜索相似 Pin 素材",
    )
    visual.add_argument("image", type=Path, help="用于 Pinterest Lens 的本机图片")
    visual.add_argument("--x", type=float, default=0, help="裁剪区域左边界，范围 0 到 1")
    visual.add_argument("--y", type=float, default=0, help="裁剪区域上边界，范围 0 到 1")
    visual.add_argument("--width", type=float, default=1, help="裁剪区域宽度，范围 0 到 1")
    visual.add_argument("--height", type=float, default=1, help="裁剪区域高度，范围 0 到 1")
    visual.add_argument("--bookmark", default="", help="从官方 opaque bookmark 继续")
    visual.add_argument(
        "--search-identifier",
        default="",
        help="续页时使用上一响应的官方 search_identifier",
    )
    visual.add_argument("--page-size", type=int, default=50, help="官方单次请求条目数；最大 100")
    visual.add_argument("--limit", type=int, default=50, help="本次最多返回的去重相似 Pin 数")
    visual.add_argument(
        "--sort-by",
        choices=("repins", "recent", "upstream"),
        default="repins",
        help="在本次样本内按保存数或日期排序，或保留上游顺序",
    )
    visual.add_argument(
        "--max-image-bytes",
        type=int,
        default=20 * 1024 * 1024,
        help="本机输入图片最大字节数；默认 20971520",
    )
    visual.add_argument(
        "--include-raw",
        action="store_true",
        help="在归一化条目中保留官方原始字段",
    )

    ads = commands.add_parser(
        "search-ads",
        help="按近期日期、国家、广告主和受众筛选官方广告库",
    )
    ads.add_argument("--start-date", default="", help="开始日期 YYYY-MM-DD；默认最近 30 天")
    ads.add_argument("--end-date", default="", help="结束日期 YYYY-MM-DD；默认今天")
    ads.add_argument("--country", default="FR", help="官方广告库两字母国家代码")
    ads.add_argument(
        "--advertiser-name",
        default="",
        help="付费广告主名称；该接口不执行跨广告主正文关键词搜索",
    )
    ads.add_argument("--vertical", default="", help="可选的官方广告类别标识")
    ads.add_argument("--gender", default="", help="可选的官方性别受众标识")
    ads.add_argument("--age-bucket", default="", help="可选的官方年龄段标识")
    ads.add_argument(
        "--sort-by",
        choices=("reach", "start_date", "upstream"),
        default="reach",
        help="在本次样本内按公开触达区间或日期排序，或保留上游顺序",
    )
    _add_bookmark(ads)
    ads.set_defaults(page_size=24)

    ad = commands.add_parser(
        "get-ad",
        help="按广告 ID 读取官方详情、触达区间、受众和素材",
    )
    ad.add_argument("ad_id", help="Pinterest Ads Repository 数字广告 ID")
    ad.add_argument(
        "--include-raw",
        action="store_true",
        help="在归一化条目中保留官方原始字段",
    )

    search = commands.add_parser(
        "search-pins",
        help="按关键词匿名搜索自然 Pin 或视频并返回联想词",
    )
    search.add_argument("query", help="Pinterest 自然内容搜索词")
    search.add_argument(
        "--scope",
        choices=("pins", "videos"),
        default="pins",
        help="搜索全部 Pin 或只搜索视频",
    )
    search.add_argument(
        "--sort-by",
        choices=("saves", "recent", "upstream"),
        default="upstream",
        help="在本次样本内按保存数或日期排序，或保留上游顺序",
    )
    _add_bookmark(search)

    pin = commands.add_parser(
        "pin",
        help="按 Pin ID 刷新公开详情、互动和最高质量媒体地址",
    )
    pin.add_argument("pin_id", help="Pinterest 数字 Pin ID")
    pin.add_argument(
        "--include-raw",
        action="store_true",
        help="在归一化条目中保留官方原始字段",
    )

    download = commands.add_parser(
        "download-media",
        help="下载 Pinterest CDN 素材并计算 SHA-256",
    )
    download.add_argument("url", help="搜索或详情结果返回的 Pinterest CDN URL")
    download.add_argument("destination", type=Path, help="本机素材文件路径")
    download.add_argument(
        "--max-bytes",
        type=int,
        default=512 * 1024 * 1024,
        help="允许下载的最大字节数；默认 536870912",
    )
    download.add_argument("--overwrite", action="store_true", help="覆盖已有目标文件")
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = PinterestAdsClient(
        timeout=args.timeout,
        retries=args.retries,
        request_interval=args.request_interval,
        proxy=args.proxy,
    )
    if args.command == "visual-search":
        return client.visual_search(
            args.image,
            x=args.x,
            y=args.y,
            width=args.width,
            height=args.height,
            bookmark=args.bookmark,
            search_identifier=args.search_identifier,
            page_size=args.page_size,
            limit=args.limit,
            sort_by=args.sort_by,
            max_image_bytes=args.max_image_bytes,
            include_raw=args.include_raw,
        )
    if args.command == "search-ads":
        return client.search_ads(
            start_date=args.start_date,
            end_date=args.end_date,
            country=args.country,
            advertiser_name=args.advertiser_name,
            vertical=args.vertical,
            gender=args.gender,
            age_bucket=args.age_bucket,
            bookmark=args.bookmark,
            page_size=args.page_size,
            limit=args.limit,
            sort_by=args.sort_by,
            include_raw=args.include_raw,
        )
    if args.command == "get-ad":
        return client.get_ad(args.ad_id, include_raw=args.include_raw)
    if args.command == "search-pins":
        return client.search_pins(
            args.query,
            scope=args.scope,
            bookmark=args.bookmark,
            page_size=args.page_size,
            limit=args.limit,
            sort_by=args.sort_by,
            include_raw=args.include_raw,
        )
    if args.command == "pin":
        return client.pin(args.pin_id, include_raw=args.include_raw)
    if args.command == "download-media":
        if (
            args.output
            and args.output.expanduser().resolve()
            == args.destination.expanduser().resolve()
        ):
            raise PinterestAdsInputError("JSON output 不得与媒体 destination 使用同一路径")
        return client.download_media(
            args.url,
            args.destination,
            max_bytes=args.max_bytes,
            overwrite=args.overwrite,
        )
    raise AssertionError(args.command)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _run(args)
    except PinterestAdsError as exc:
        print(f"错误[{exc.code}]: {exc}", file=sys.stderr)
        return 1
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
