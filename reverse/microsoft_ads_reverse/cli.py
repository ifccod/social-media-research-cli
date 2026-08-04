from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .client import MicrosoftAdsClient
from .errors import MicrosoftAdsError


def _add_pagination(parser: argparse.ArgumentParser, *, default_limit: int) -> None:
    parser.add_argument("--offset", type=int, default=0, help="从此结果偏移量继续")
    parser.add_argument(
        "--limit",
        type=int,
        default=default_limit,
        help="本次最多返回的去重条目数；最大 500",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=24,
        help="匿名 API 单页条目数；最大 24",
    )
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="在归一化条目中保留官方原始字段",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Microsoft Advertising 官方 Ad Library 匿名 OData API 客户端"
    )
    parser.add_argument("--timeout", type=float, default=30, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败重试次数")
    parser.add_argument(
        "--request-interval",
        type=float,
        default=1,
        help="同一 Microsoft Ad Library 请求之间的最小秒数",
    )
    parser.add_argument("--proxy", default="", help="可选的本机 http 或 https 代理 URL")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    advertisers = commands.add_parser(
        "search-advertisers",
        help="按名称匿名搜索 Bing 广告主",
    )
    advertisers.add_argument("query", help="广告主名称")
    _add_pagination(advertisers, default_limit=24)

    advertiser = commands.add_parser(
        "get-advertiser",
        help="按广告主 id 匿名读取公开身份",
    )
    advertiser.add_argument("advertiser_id", help="Microsoft Ad Library 广告主 id")
    advertiser.add_argument(
        "--include-raw",
        action="store_true",
        help="保留官方原始字段",
    )

    ads = commands.add_parser(
        "search-ads",
        help="按广告文案或广告主匿名搜索 EEA Bing 广告",
    )
    ads.add_argument(
        "query",
        nargs="?",
        default="",
        help="广告标题或正文关键词；也可只传 advertiser-id",
    )
    ads.add_argument(
        "--advertiser-id",
        default="",
        help="只读取指定 Microsoft 广告主的广告",
    )
    ads.add_argument("--start-date", default="", help="开始日期 YYYY-MM-DD")
    ads.add_argument("--end-date", default="", help="结束日期 YYYY-MM-DD")
    ads.add_argument(
        "--country-code",
        dest="country_codes",
        action="append",
        help="可重复传入 Microsoft Ad Library 的数字国家代码",
    )
    _add_pagination(ads, default_limit=48)

    ad = commands.add_parser(
        "get-ad",
        help="按广告 id 读取曝光区间、国家占比和定向详情",
    )
    ad.add_argument("ad_id", help="Microsoft Ad Library 广告 id")
    ad.add_argument(
        "--include-raw",
        action="store_true",
        help="保留官方原始字段",
    )
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = MicrosoftAdsClient(
        timeout=args.timeout,
        retries=args.retries,
        request_interval=args.request_interval,
        proxy=args.proxy,
    )
    if args.command == "search-advertisers":
        return client.search_advertisers(
            args.query,
            offset=args.offset,
            limit=args.limit,
            page_size=args.page_size,
            include_raw=args.include_raw,
        )
    if args.command == "get-advertiser":
        return client.get_advertiser(
            args.advertiser_id,
            include_raw=args.include_raw,
        )
    if args.command == "search-ads":
        return client.search_ads(
            args.query,
            advertiser_id=args.advertiser_id,
            start_date=args.start_date,
            end_date=args.end_date,
            country_codes=args.country_codes,
            offset=args.offset,
            limit=args.limit,
            page_size=args.page_size,
            include_raw=args.include_raw,
        )
    if args.command == "get-ad":
        return client.get_ad(args.ad_id, include_raw=args.include_raw)
    raise AssertionError(args.command)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _run(args)
    except MicrosoftAdsError as exc:
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
