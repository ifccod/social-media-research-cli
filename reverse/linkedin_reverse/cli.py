from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import LinkedInClient
from .errors import LinkedInError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LinkedIn 匿名公开页面 JSON-LD 与 SSR 客户端"
    )
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败重试次数")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    post = commands.add_parser("post", help="查询并归一化公开帖子")
    post.add_argument("post_reference", help="activity id、URN、帖子 slug 或公开 URL")

    resolve_post = commands.add_parser(
        "resolve-post", help="不发起请求，仅归一化帖子引用"
    )
    resolve_post.add_argument(
        "post_reference", help="activity id、URN、帖子 slug 或公开 URL"
    )

    article = commands.add_parser("article", help="查询公开 Pulse 文章")
    article.add_argument("article_reference", help="Pulse slug 或公开 URL")

    person = commands.add_parser("person", help="查询公开个人资料")
    person.add_argument("person_reference", help="资料 slug 或 /in/ URL")

    author_articles = commands.add_parser(
        "author-articles", help="查询公开资料中的有限文章子集"
    )
    author_articles.add_argument(
        "person_reference", help="资料 slug、/in/ URL 或作者文章 URL"
    )
    author_articles.add_argument("--limit", type=int, default=10)

    company = commands.add_parser("company", help="查询公开公司资料")
    company.add_argument("company_reference", help="公司 slug 或 /company/ URL")

    company_posts = commands.add_parser(
        "company-posts", help="查询有限的公司公开帖子子集"
    )
    company_posts.add_argument(
        "company_reference", help="公司 slug 或 /company/ URL"
    )
    company_posts.add_argument("--limit", type=int, default=10)

    company_people = commands.add_parser(
        "company-people", help="查询公司页面中的公开员工子集"
    )
    company_people.add_argument(
        "company_reference", help="公司 slug 或 /company/ URL"
    )

    company_affiliates = commands.add_parser(
        "company-affiliates", help="查询公司的公开关联页面"
    )
    company_affiliates.add_argument(
        "company_reference", help="公司 slug 或 /company/ URL"
    )

    ad = commands.add_parser("ad", help="查询单个公开 Ad Library 条目")
    ad.add_argument("ad_reference", help="广告 id 或 /ad-library/detail/ URL")

    ads = commands.add_parser("ads", help="搜索公开 Ad Library 条目")
    ads.add_argument("keyword", nargs="?", default="")
    ads.add_argument("--advertiser-name")
    ads.add_argument(
        "--country",
        dest="countries",
        action="append",
        help="可重复指定，或使用逗号分隔的两字母国家代码",
    )
    ads.add_argument(
        "--date-option",
        choices=(
            "last-30-days",
            "current-month",
            "current-year",
            "last-year",
            "custom-date-range",
        ),
    )
    ads.add_argument("--sort-order", choices=("newest", "oldest"))
    ads.add_argument("--payer")
    ads.add_argument("--start-date", "--startdate", dest="startdate")
    ads.add_argument("--end-date", "--enddate", dest="enddate")
    ads.add_argument("--impressions-min")
    ads.add_argument("--impressions-max")
    ads.add_argument("--include-facets", dest="included_facets")
    ads.add_argument("--exclude-facets", dest="excluded_facets")
    ads.add_argument("--pagination-token")
    ads.add_argument("--limit", type=int, default=20)

    job = commands.add_parser("job", help="查询单个公开职位")
    job.add_argument("job_reference", help="职位 id、URN 或 /jobs/view/ URL")

    jobs = commands.add_parser("jobs", help="搜索公开职位")
    jobs.add_argument(
        "jobs_reference",
        nargs="?",
        default="",
        help="关键词或 LinkedIn /jobs/search URL",
    )
    jobs.add_argument("--location")
    jobs.add_argument("--geo-id")
    jobs.add_argument("--company-id", help="单个 id 或逗号分隔的公司 id")
    jobs.add_argument(
        "--time-range",
        choices=("day", "week", "month", "past_24h", "past_week", "past_month"),
    )
    jobs.add_argument(
        "--job-type",
        help="逗号分隔的 F/P/C/T/I/V/O 代码或职位类型名",
    )
    jobs.add_argument(
        "--experience-level",
        help="逗号分隔的级别名或 1 到 6 的数字级别",
    )
    jobs.add_argument(
        "--remote", help="一个或多个 on-site、remote、hybrid 或 1/2/3"
    )
    jobs.add_argument("--sort-by", choices=("relevant", "R", "recent", "DD"))
    jobs.add_argument("--easy-apply", action="store_true", default=None)
    jobs.add_argument("--under-10-applicants", action="store_true", default=None)
    jobs.add_argument("--start", type=int)
    jobs.add_argument("--count", type=int, default=25)

    company_jobs = commands.add_parser(
        "company-jobs", help="按公司 id 查询公开职位"
    )
    company_jobs.add_argument("company_id", help="LinkedIn 数字公司 id")
    company_jobs.add_argument("--location")
    company_jobs.add_argument("--geo-id")
    company_jobs.add_argument(
        "--time-range",
        choices=("day", "week", "month", "past_24h", "past_week", "past_month"),
    )
    company_jobs.add_argument(
        "--job-type",
        help="逗号分隔的 F/P/C/T/I/V/O 代码或职位类型名",
    )
    company_jobs.add_argument(
        "--experience-level",
        help="逗号分隔的级别名或 1 到 6 的数字级别",
    )
    company_jobs.add_argument(
        "--remote", help="一个或多个 on-site、remote、hybrid 或 1/2/3"
    )
    company_jobs.add_argument("--sort-by", choices=("relevant", "R", "recent", "DD"))
    company_jobs.add_argument("--easy-apply", action="store_true", default=None)
    company_jobs.add_argument(
        "--under-10-applicants", action="store_true", default=None
    )
    company_jobs.add_argument("--start", type=int)
    company_jobs.add_argument("--count", type=int, default=25)

    company_job_count = commands.add_parser(
        "company-job-count", help="查询指定公司 id 的公开职位数"
    )
    company_job_count.add_argument("company_id", help="LinkedIn 数字公司 id")

    location_suggest = commands.add_parser(
        "location-suggest", help="查询 LinkedIn 公开职位地点建议"
    )
    location_suggest.add_argument("keyword")
    location_suggest.add_argument("--count", type=int, default=10)

    job_suggest = commands.add_parser(
        "job-suggest", help="查询公开混合职位建议"
    )
    job_suggest.add_argument("keyword")
    job_suggest.add_argument("--count", type=int, default=10)

    company_suggest = commands.add_parser(
        "company-suggest", help="查询公开公司建议"
    )
    company_suggest.add_argument("keyword")
    company_suggest.add_argument("--count", type=int, default=10)
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = LinkedInClient(timeout=args.timeout, retries=args.retries)
    if args.command == "resolve-post":
        return client.parse_post_reference(args.post_reference)
    if args.command == "post":
        return client.get_post(args.post_reference)
    if args.command == "article":
        return client.get_article(args.article_reference)
    if args.command == "person":
        return client.get_person(args.person_reference)
    if args.command == "author-articles":
        return client.get_author_articles(args.person_reference, limit=args.limit)
    if args.command == "company":
        return client.get_company(args.company_reference)
    if args.command == "company-posts":
        return client.get_company_posts(args.company_reference, limit=args.limit)
    if args.command == "company-people":
        return client.get_company_people(args.company_reference)
    if args.command == "company-affiliates":
        return client.get_company_affiliates(args.company_reference)
    if args.command == "ad":
        return client.get_ad(args.ad_reference)
    if args.command == "ads":
        return client.search_ads(
            keyword=args.keyword,
            advertiser_name=args.advertiser_name,
            countries=args.countries,
            date_option=args.date_option,
            sort_order=args.sort_order,
            payer=args.payer,
            startdate=args.startdate,
            enddate=args.enddate,
            impressions_min=args.impressions_min,
            impressions_max=args.impressions_max,
            included_facets=args.included_facets,
            excluded_facets=args.excluded_facets,
            pagination_token=args.pagination_token,
            limit=args.limit,
        )
    if args.command == "job":
        return client.get_job(args.job_reference)
    if args.command == "jobs":
        return client.search_jobs(
            args.jobs_reference,
            location=args.location,
            geo_id=args.geo_id,
            company_id=args.company_id,
            time_range=args.time_range,
            job_type=args.job_type,
            experience_level=args.experience_level,
            remote=args.remote,
            sort_by=args.sort_by,
            easy_apply=args.easy_apply,
            under_10_applicants=args.under_10_applicants,
            start=args.start,
            count=args.count,
        )
    if args.command == "company-jobs":
        return client.get_company_jobs(
            args.company_id,
            location=args.location,
            geo_id=args.geo_id,
            time_range=args.time_range,
            job_type=args.job_type,
            experience_level=args.experience_level,
            remote=args.remote,
            sort_by=args.sort_by,
            easy_apply=args.easy_apply,
            under_10_applicants=args.under_10_applicants,
            start=args.start,
            count=args.count,
        )
    if args.command == "company-job-count":
        return client.get_company_job_count(args.company_id)
    if args.command == "location-suggest":
        return client.suggest_job_locations(args.keyword, count=args.count)
    if args.command == "job-suggest":
        return client.suggest_job_keywords(args.keyword, count=args.count)
    if args.command == "company-suggest":
        return client.suggest_job_companies(args.keyword, count=args.count)
    raise AssertionError(f"unsupported command: {args.command}")


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except LinkedInError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
