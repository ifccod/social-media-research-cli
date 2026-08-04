from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .client import SnapchatAdsClient
from .errors import SnapchatAdsError, SnapchatAdsInputError


def _add_pagination(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cursor", default="", help="从官方 opaque cursor 继续")
    parser.add_argument("--limit", type=int, default=50, help="本次最多返回的去重条目数")
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="在归一化条目中保留官方原始字段",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Snapchat 官方 Ads Gallery 匿名 JSON API 客户端"
    )
    parser.add_argument("--timeout", type=float, default=30, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败重试次数")
    parser.add_argument(
        "--request-interval",
        type=float,
        default=0.5,
        help="同一 Snapchat Ads Gallery 请求之间的最小秒数",
    )
    parser.add_argument("--proxy", default="", help="可选的本机 http 或 https 代理 URL")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    search_ads = commands.add_parser(
        "search-ads",
        help="按付费广告主、国家、日期和状态搜索公开广告",
    )
    search_ads.add_argument(
        "paying_advertiser_name",
        nargs="?",
        default="",
        help="广告费用支付方名称；Snapchat 不支持商品正文关键词搜索",
    )
    search_ads.add_argument(
        "--country",
        dest="countries",
        action="append",
        help="可重复指定官方 EEA 两字母国家代码；希腊使用 el 或 GR",
    )
    search_ads.add_argument(
        "--start-date",
        default="",
        help="开始日期，使用 YYYY-MM-DD 或带时区的 ISO 8601 时间",
    )
    search_ads.add_argument(
        "--end-date",
        default="",
        help="结束日期，使用 YYYY-MM-DD 或带时区的 ISO 8601 时间",
    )
    search_ads.add_argument(
        "--status",
        choices=("ACTIVE", "PAUSED"),
        default="ACTIVE",
        help="广告状态",
    )
    search_ads.add_argument(
        "--sort-by",
        choices=("impressions", "start_date", "upstream"),
        default="impressions",
        help="在本次采集样本内按真实曝光或日期排序，或保留上游顺序",
    )
    search_ads.add_argument(
        "--product-limit",
        type=int,
        default=20,
        help="每条动态商品广告最多保留的商品数；最大 100",
    )
    _add_pagination(search_ads)

    get_ad = commands.add_parser(
        "get-ad",
        help="按广告 UUID 读取公开详情、曝光、targeting 和素材",
    )
    get_ad.add_argument("ad_id", help="Snapchat Ads Gallery 广告 UUID")
    get_ad.add_argument(
        "--product-limit",
        type=int,
        default=20,
        help="动态商品广告最多保留的商品数；最大 100",
    )
    get_ad.add_argument(
        "--include-raw",
        action="store_true",
        help="在归一化条目中保留官方原始字段",
    )

    sponsored = commands.add_parser(
        "sponsored-content",
        help="匿名读取公开赞助内容流",
    )
    _add_pagination(sponsored)

    sponsored_search = commands.add_parser(
        "search-sponsored-content",
        help="按创作者名称匿名搜索公开赞助内容",
    )
    sponsored_search.add_argument("creator_name", help="Snapchat 创作者名称")
    sponsored_search.add_argument(
        "--page-size",
        type=int,
        default=50,
        help="官方单页结果数；最大 100",
    )
    _add_pagination(sponsored_search)

    download = commands.add_parser(
        "download-media",
        help="下载官方结果中的 Snapchat CDN 素材并计算 SHA-256",
    )
    download.add_argument(
        "url",
        help="搜索或详情结果返回的 top snap、图片、视频、缩略图或 Lens URL",
    )
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
    client = SnapchatAdsClient(
        timeout=args.timeout,
        retries=args.retries,
        request_interval=args.request_interval,
        proxy=args.proxy,
    )
    if args.command == "search-ads":
        return client.search_ads(
            paying_advertiser_name=args.paying_advertiser_name,
            countries=args.countries,
            start_date=args.start_date,
            end_date=args.end_date,
            status=args.status,
            cursor=args.cursor,
            limit=args.limit,
            product_limit=args.product_limit,
            sort_by=args.sort_by,
            include_raw=args.include_raw,
        )
    if args.command == "get-ad":
        return client.get_ad(
            args.ad_id,
            product_limit=args.product_limit,
            include_raw=args.include_raw,
        )
    if args.command == "sponsored-content":
        return client.sponsored_content(
            cursor=args.cursor,
            limit=args.limit,
            include_raw=args.include_raw,
        )
    if args.command == "search-sponsored-content":
        return client.search_sponsored_content(
            args.creator_name,
            cursor=args.cursor,
            page_size=args.page_size,
            limit=args.limit,
            include_raw=args.include_raw,
        )
    if args.command == "download-media":
        if (
            args.output
            and args.output.expanduser().resolve()
            == args.destination.expanduser().resolve()
        ):
            raise SnapchatAdsInputError(
                "JSON output 不能与媒体 destination 使用同一路径"
            )
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
    except SnapchatAdsError as exc:
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
