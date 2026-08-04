from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .client import FacebookAdsClient
from .errors import FacebookAdsError, FacebookAdsInputError


def _add_ad_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--country",
        dest="countries",
        help="单个两字母国家代码或 ALL；默认 US",
    )
    parser.add_argument(
        "--status",
        dest="active_status",
        choices=("ACTIVE", "INACTIVE", "ALL"),
        default="ACTIVE",
        help="广告投放状态",
    )
    parser.add_argument(
        "--ad-type",
        choices=(
            "ALL",
            "POLITICAL_AND_ISSUE_ADS",
            "HOUSING_ADS",
            "EMPLOYMENT_ADS",
            "CREDIT_ADS",
            "FINANCIAL_PRODUCTS_AND_SERVICES_ADS",
        ),
        default="ALL",
        help="Meta 广告类别",
    )
    parser.add_argument(
        "--media-type",
        choices=("ALL", "IMAGE", "VIDEO", "MEME", "IMAGE_AND_MEME", "NONE"),
        default="ALL",
        help="素材媒体类型",
    )
    parser.add_argument(
        "--publisher-platform",
        dest="publisher_platforms",
        action="append",
        choices=(
            "FACEBOOK",
            "INSTAGRAM",
            "MESSENGER",
            "AUDIENCE_NETWORK",
            "WHATSAPP",
            "THREADS",
        ),
        help="可重复指定投放平台",
    )
    parser.add_argument(
        "--content-language",
        dest="content_languages",
        action="append",
        help="可重复指定广告内容的 BCP 47 语言代码",
    )
    parser.add_argument(
        "--start-date",
        default="",
        help="筛选与该日期起的区间重叠的广告，格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--end-date",
        default="",
        help="筛选与截至该日期的区间重叠的广告，格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--sort",
        choices=(
            "total_impressions",
            "relevancy_monthly_grouped",
        ),
        default="total_impressions",
        help="Meta 服务端的曝光或月度相关性排序",
    )
    parser.add_argument(
        "--sort-direction",
        choices=("ASCENDING", "DESCENDING"),
        default="DESCENDING",
        help="曝光排序方向；relevancy 时忽略",
    )
    parser.add_argument("--cursor", default="", help="从指定 GraphQL cursor 继续")
    parser.add_argument(
        "--page-size",
        type=int,
        default=10,
        help="每次匿名 GraphQL 续页的结果数，最大 10",
    )
    parser.add_argument("--limit", type=int, default=60, help="本次最多返回的去重广告数")
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="在每条归一化广告中保留原始 GraphQL 字段",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Meta Ads Library 匿名 GraphQL 广告素材客户端"
    )
    parser.add_argument("--timeout", type=float, default=30, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败重试次数")
    parser.add_argument(
        "--request-interval",
        type=float,
        default=2,
        help="同一 Meta GraphQL 请求之间的最小秒数",
    )
    parser.add_argument("--proxy", default="", help="可选的本机 http 或 https 代理 URL")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    suggest = commands.add_parser(
        "search-suggest",
        help="匿名搜索 Facebook Page 联想词与 Page id",
    )
    suggest.add_argument("query", help="品牌、店铺或广告主页名称")
    suggest.add_argument("--country", default="US", help="两字母国家代码；默认 US")
    suggest.add_argument("--limit", type=int, default=10, help="最多返回的 Page 数")

    ads = commands.add_parser(
        "search-ads",
        help="按关键词匿名搜索 Meta Ads Library 素材",
    )
    ads.add_argument("query", help="清洗后的广告搜索词")
    ads.add_argument(
        "--search-type",
        choices=("KEYWORD_EXACT_PHRASE", "KEYWORD_UNORDERED"),
        default="KEYWORD_UNORDERED",
        help="精确短语或无序关键词搜索",
    )
    ads.add_argument(
        "--page-id",
        dest="page_ids",
        action="append",
        help="可重复指定 Page id，进一步约束关键词搜索",
    )
    _add_ad_filters(ads)

    page_ads = commands.add_parser(
        "page-ads",
        help="按一个或多个 Page id 匿名读取近期广告素材",
    )
    page_ads.add_argument("page_ids", nargs="+", help="数字 Page id，可一次提供多个")
    _add_ad_filters(page_ads)

    details = commands.add_parser(
        "ad-details",
        help="匿名读取单条广告的地区触达、定向和付费主体",
    )
    details.add_argument("ad_id", help="search-ads 返回的十进制广告 id")
    details.add_argument(
        "--page-id",
        default="",
        help="可选的 Page id；默认从广告详情 SSR 自动解析",
    )
    details.add_argument(
        "--country",
        default="US",
        help="页面支出上下文使用的两字母国家代码；默认 US",
    )
    details.add_argument(
        "--political",
        action="store_true",
        help="按政治或议题广告请求额外投放洞察",
    )
    details.add_argument(
        "--include-raw",
        action="store_true",
        help="保留原始 GraphQL 详情字段",
    )

    download = commands.add_parser(
        "download-media",
        help="匿名下载搜索结果中的 Meta CDN 图片或视频并计算 SHA-256",
    )
    download.add_argument("url", help="search-ads 或 page-ads 返回的临时媒体 URL")
    download.add_argument("destination", type=Path, help="本机素材文件路径")
    download.add_argument(
        "--max-bytes",
        type=int,
        default=512 * 1024 * 1024,
        help="允许下载的最大字节数；默认 536870912",
    )
    download.add_argument("--overwrite", action="store_true", help="覆盖已有目标文件")
    return parser


def _ad_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "countries": args.countries,
        "ad_type": args.ad_type,
        "active_status": args.active_status,
        "media_type": args.media_type,
        "publisher_platforms": args.publisher_platforms,
        "content_languages": args.content_languages,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "sort": args.sort,
        "sort_direction": args.sort_direction,
        "cursor": args.cursor,
        "page_size": args.page_size,
        "limit": args.limit,
        "include_raw": args.include_raw,
    }


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = FacebookAdsClient(
        timeout=args.timeout,
        retries=args.retries,
        request_interval=args.request_interval,
        proxy=args.proxy,
    )
    if args.command == "search-suggest":
        return client.search_pages(args.query, country=args.country, limit=args.limit)
    if args.command == "search-ads":
        return client.search_ads(
            args.query,
            search_type=args.search_type,
            page_ids=args.page_ids,
            **_ad_kwargs(args),
        )
    if args.command == "page-ads":
        return client.page_ads(args.page_ids, **_ad_kwargs(args))
    if args.command == "ad-details":
        return client.ad_details(
            args.ad_id,
            page_id=args.page_id,
            country=args.country,
            political=args.political,
            include_raw=args.include_raw,
        )
    if args.command == "download-media":
        if (
            args.output
            and args.output.expanduser().resolve()
            == args.destination.expanduser().resolve()
        ):
            raise FacebookAdsInputError("JSON output 不能与媒体 destination 使用同一路径")
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
    except FacebookAdsError as exc:
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
