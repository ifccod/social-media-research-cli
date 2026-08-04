from __future__ import annotations

import unittest
from collections import deque
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from curl_cffi import requests

from reverse.linkedin_reverse.client import DEFAULT_USER_AGENT, LinkedInClient
from reverse.linkedin_reverse.cli import _parser, _run
from reverse.linkedin_reverse.errors import LinkedInError, LinkedInInputError, LinkedInResponseError

FIXTURES = Path(__file__).with_name("fixtures")
VIDEO_HTML = (FIXTURES / "video_post.html").read_text(encoding="utf-8")
SOCIAL_HTML = (FIXTURES / "social_post.html").read_text(encoding="utf-8")
ARTICLE_HTML = (FIXTURES / "article.html").read_text(encoding="utf-8")
PERSON_HTML = (FIXTURES / "person.html").read_text(encoding="utf-8")
COMPANY_HTML = (FIXTURES / "company.html").read_text(encoding="utf-8")
COMPANY_PUBLIC_HTML = (FIXTURES / "company_public_sections.html").read_text(
    encoding="utf-8"
)
FEED_UPDATES_HTML = (FIXTURES / "feed_updates.html").read_text(encoding="utf-8")
JOB_HTML = (FIXTURES / "job_detail.html").read_text(encoding="utf-8")
JOB_SEARCH_HTML = (FIXTURES / "job_search.html").read_text(encoding="utf-8")
LOCATION_SUGGESTIONS_JSON = (FIXTURES / "location_suggestions.json").read_text(
    encoding="utf-8"
)
JOB_SUGGESTIONS_JSON = (FIXTURES / "job_suggestions.json").read_text(encoding="utf-8")
COMPANY_SUGGESTIONS_JSON = (FIXTURES / "company_suggestions.json").read_text(
    encoding="utf-8"
)

POST_ID = "7481083645374631936"
POST_URN = f"urn:li:activity:{POST_ID}"
POST_SLUG = f"satyanadella_fixture-video-activity-{POST_ID}-lAvZ"
SOCIAL_ID = "7483216848923045888"
ARTICLE_SLUG = (
    "how-do-we-build-frontier-intelligence-ecosystem-satya-nadella-73jhc"
)
JOB_ID = "4438850133"
SECOND_JOB_ID = "4439496395"


def response(
    source: str,
    *,
    status: int = 200,
    url: str = "",
    headers: dict[str, str] | None = None,
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers = requests.Headers(headers or {})
    result.content = source.encode("utf-8")
    result.default_encoding = "utf-8"
    return result


class FakeSession(requests.Session):
    def __init__(self, results: list[requests.Response | Exception]) -> None:
        super().__init__()
        self.results = deque(results)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> requests.Response:
        self.calls.append((url, kwargs))
        if not self.results:
            raise AssertionError("unexpected HTTP request")
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        if not result.url:
            result.url = url
        return result


class LinkedInClientTest(unittest.TestCase):
    def test_error_types_share_the_public_base(self) -> None:
        self.assertTrue(issubclass(LinkedInInputError, LinkedInError))
        self.assertTrue(issubclass(LinkedInResponseError, LinkedInError))

    def test_post_reference_accepts_id_urn_slug_and_public_routes(self) -> None:
        raw_id = LinkedInClient.parse_post_reference(7481083645374631936)
        self.assertEqual(raw_id["id"], POST_ID)
        self.assertEqual(raw_id["urn"], POST_URN)
        self.assertEqual(
            raw_id["url"], f"https://www.linkedin.com/feed/update/{POST_URN}"
        )

        slug = LinkedInClient.parse_post_reference(POST_SLUG)
        self.assertEqual(slug["slug"], POST_SLUG)
        self.assertEqual(slug["id"], POST_ID)

        for urn in (
            POST_URN,
            f"urn:li:share:{POST_ID}",
            f"urn:li:ugcPost:{POST_ID}",
        ):
            with self.subTest(urn=urn):
                self.assertEqual(LinkedInClient.parse_post_reference(urn)["urn"], urn)

        post_url = f"https://uk.linkedin.com/posts/{POST_SLUG}?trk=public_post"
        self.assertEqual(LinkedInClient.parse_post_reference(post_url)["slug"], POST_SLUG)
        feed_url = f"https://www.linkedin.com/feed/update/{POST_URN}/?trk=fixture"
        self.assertEqual(LinkedInClient.parse_post_reference(feed_url)["urn"], POST_URN)
        embed_url = f"https://www.linkedin.com/embed/feed/update/{POST_URN}/"
        self.assertEqual(LinkedInClient.parse_post_reference(embed_url)["id"], POST_ID)

        share_text = f"Read this {post_url} and continue."
        self.assertEqual(LinkedInClient.parse_post_reference(share_text)["id"], POST_ID)

    def test_person_company_and_article_references_are_strict(self) -> None:
        self.assertEqual(
            LinkedInClient.parse_person_reference("satyanadella")["url"],
            "https://www.linkedin.com/in/satyanadella",
        )
        self.assertEqual(
            LinkedInClient.parse_person_reference(
                "linkedin.com/in/satyanadella/?trk=public_profile"
            )["slug"],
            "satyanadella",
        )
        self.assertEqual(
            LinkedInClient.parse_author_articles_reference(
                "https://www.linkedin.com/in/satyanadella/recent-activity/articles/"
            )["slug"],
            "satyanadella",
        )
        self.assertEqual(
            LinkedInClient.parse_company_reference(
                "https://www.linkedin.com/company/openai/about/"
            )["slug"],
            "openai",
        )
        self.assertEqual(
            LinkedInClient.parse_article_reference(ARTICLE_SLUG)["slug"], ARTICLE_SLUG
        )
        self.assertEqual(
            LinkedInClient.parse_article_reference(
                f"https://www.linkedin.com/pulse/{ARTICLE_SLUG}?trk=fixture"
            )["url"],
            f"https://www.linkedin.com/pulse/{ARTICLE_SLUG}",
        )

    def test_malformed_or_unowned_references_are_rejected(self) -> None:
        bad_posts: list[str | int | bool] = [
            True,
            123,
            "0" * 19,
            "urn:li:profile:7481083645374631936",
            "urn:li:activity:0000000000000000001",
            "https://example.com/posts/" + POST_SLUG,
            "https://www.linkedin.com.example.com/posts/" + POST_SLUG,
            "https://user@www.linkedin.com/posts/" + POST_SLUG,
            "https://www.linkedin.com:444/posts/" + POST_SLUG,
            "https://www.linkedin.com/posts/fixture-without-an-activity-id",
            "https://www.linkedin.com/jobs/view/7481083645374631936",
            "not a post",
        ]
        for value in bad_posts:
            with self.subTest(value=value), self.assertRaises(LinkedInInputError):
                LinkedInClient.parse_post_reference(value)  # type: ignore[arg-type]

        bad_entities = [
            lambda: LinkedInClient.parse_person_reference(
                "https://www.linkedin.com/company/openai"
            ),
            lambda: LinkedInClient.parse_company_reference(
                "https://www.linkedin.com/in/satyanadella"
            ),
            lambda: LinkedInClient.parse_person_reference("bad slug"),
            lambda: LinkedInClient.parse_author_articles_reference(
                "https://www.linkedin.com/company/openai/posts/"
            ),
            lambda: LinkedInClient.parse_company_reference("openai%2Fjobs"),
            lambda: LinkedInClient.parse_article_reference(
                "https://www.linkedin.com/in/not-an-article"
            ),
        ]
        for call in bad_entities:
            with self.assertRaises(LinkedInInputError):
                call()

    def test_job_reference_accepts_id_urn_and_public_routes(self) -> None:
        for value in (JOB_ID, int(JOB_ID), f"urn:li:jobPosting:{JOB_ID}"):
            with self.subTest(value=value):
                reference = LinkedInClient.parse_job_reference(value)
                self.assertEqual(reference["id"], JOB_ID)
                self.assertEqual(reference["urn"], f"urn:li:jobPosting:{JOB_ID}")
                self.assertEqual(
                    reference["request_url"],
                    f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{JOB_ID}",
                )

        public = LinkedInClient.parse_job_reference(
            f"https://fr.linkedin.com/jobs/view/software-engineer-at-fixture-{JOB_ID}"
            "?trk=fixture"
        )
        self.assertEqual(public["id"], JOB_ID)
        self.assertEqual(
            public["url"],
            f"https://www.linkedin.com/jobs/view/software-engineer-at-fixture-{JOB_ID}",
        )
        guest = LinkedInClient.parse_job_reference(
            f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{JOB_ID}"
        )
        self.assertEqual(guest["id"], JOB_ID)

        bad: list[str | int | bool] = [
            True,
            123,
            "0000000001",
            f"urn:li:activity:{JOB_ID}",
            f"https://example.com/jobs/view/fixture-{JOB_ID}",
            f"https://user@www.linkedin.com/jobs/view/fixture-{JOB_ID}",
            f"https://www.linkedin.com:444/jobs/view/fixture-{JOB_ID}",
            "https://www.linkedin.com/jobs/view/not-a-job",
            f"https://www.linkedin.com/posts/fixture-activity-{JOB_ID}",
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(LinkedInInputError):
                LinkedInClient.parse_job_reference(value)  # type: ignore[arg-type]

    def test_jobs_reference_normalizes_url_filters_and_company_only_search(self) -> None:
        reference = LinkedInClient.parse_jobs_reference(
            "https://fr.linkedin.com/jobs/search/?keywords=platform+engineer"
            "&location=Paris&geoId=105015875&f_C=1441%2C1035"
            "&f_TPR=r604800&f_JT=F%2CC&f_E=2%2C4&f_WT=2"
            "&sortBy=DD&f_AL=true&f_EA=TRUE&start=20"
            "&trackingId=ignored",
            remote="hybrid",
            count=30,
        )

        self.assertEqual(reference["keyword"], "platform engineer")
        self.assertEqual(reference["start"], 20)
        self.assertEqual(reference["count"], 30)
        self.assertEqual(
            reference["filters"],
            {
                "location": "Paris",
                "geo_id": "105015875",
                "company_id": "1441,1035",
                "time_range": "r604800",
                "job_type": "F,C",
                "experience_level": "2,4",
                "remote": "3",
                "sort_by": "DD",
                "easy_apply": True,
                "under_10_applicants": True,
            },
        )
        query = parse_qs(urlsplit(reference["url"]).query)
        self.assertEqual(query["keywords"], ["platform engineer"])
        self.assertEqual(query["f_WT"], ["3"])
        self.assertEqual(query["sortBy"], ["DD"])
        self.assertEqual(query["f_AL"], ["true"])
        self.assertEqual(query["f_EA"], ["true"])
        self.assertNotIn("trackingId", query)

        company = LinkedInClient.parse_jobs_reference(
            "",
            company_id=[1441, "1035"],
            time_range="past_24h",
            experience_level="entry_level,mid_senior",
            remote="on_site",
            sort_by="relevant",
            easy_apply=True,
            under_10_applicants=True,
        )
        self.assertIsNone(company["keyword"])
        self.assertEqual(company["filters"]["company_id"], "1441,1035")
        self.assertEqual(company["filters"]["time_range"], "r86400")
        self.assertEqual(company["filters"]["experience_level"], "2,4")
        self.assertEqual(company["filters"]["remote"], "1")
        self.assertEqual(company["filters"]["sort_by"], "R")
        self.assertTrue(company["filters"]["easy_apply"])
        self.assertTrue(company["filters"]["under_10_applicants"])
        self.assertIn("f_C=1441%2C1035", company["url"])

        disabled = LinkedInClient.parse_jobs_reference(
            "https://www.linkedin.com/jobs/search?sortBy=R"
            "&f_AL=true&f_EA=true",
            sort_by="recent",
            easy_apply=False,
            under_10_applicants=False,
        )
        self.assertEqual(disabled["filters"]["sort_by"], "DD")
        self.assertIsNone(disabled["filters"]["easy_apply"])
        self.assertIsNone(disabled["filters"]["under_10_applicants"])
        disabled_query = parse_qs(urlsplit(disabled["url"]).query)
        self.assertNotIn("f_AL", disabled_query)
        self.assertNotIn("f_EA", disabled_query)

        seo = LinkedInClient.parse_jobs_reference(
            "https://www.linkedin.com/jobs/software-engineer-jobs?f_TPR=r3600"
        )
        self.assertEqual(seo["keyword"], "software engineer")
        self.assertEqual(seo["filters"]["time_range"], "r3600")

        location_only = LinkedInClient.parse_jobs_reference("", location="Paris")
        self.assertIsNone(location_only["keyword"])
        self.assertEqual(location_only["filters"]["location"], "Paris")
        empty = LinkedInClient.parse_jobs_reference("")
        self.assertEqual(empty["url"], f"{location_only['url'].split('?')[0]}?start=0")

        localized = LinkedInClient.parse_jobs_reference(
            "fr.linkedin.com/jobs/search?keywords=data+engineer"
        )
        self.assertEqual(localized["keyword"], "data engineer")

        explicit_zero = LinkedInClient.parse_jobs_reference(
            "https://www.linkedin.com/jobs/search?keywords=data&start=25", start=0
        )
        self.assertEqual(explicit_zero["start"], 0)
        maximum = LinkedInClient.parse_jobs_reference("engineer", start=999)
        self.assertEqual(maximum["start"], 999)

    def test_jobs_reference_rejects_invalid_filters_and_unowned_urls(self) -> None:
        calls = [
            lambda: LinkedInClient.parse_jobs_reference("engineer", count=0),
            lambda: LinkedInClient.parse_jobs_reference("engineer", count=101),
            lambda: LinkedInClient.parse_jobs_reference("engineer", start=-1),
            lambda: LinkedInClient.parse_jobs_reference("engineer", start=1000),
            lambda: LinkedInClient.parse_jobs_reference(
                "https://www.linkedin.com/jobs/search?keywords=engineer&start=1000"
            ),
            lambda: LinkedInClient.parse_jobs_reference("engineer", geo_id="bad"),
            lambda: LinkedInClient.parse_jobs_reference("engineer", time_range="year"),
            lambda: LinkedInClient.parse_jobs_reference("engineer", job_type="unknown"),
            lambda: LinkedInClient.parse_jobs_reference(
                "engineer", experience_level="7"
            ),
            lambda: LinkedInClient.parse_jobs_reference("engineer", remote="4"),
            lambda: LinkedInClient.parse_jobs_reference("engineer", sort_by="oldest"),
            lambda: LinkedInClient.parse_jobs_reference("engineer", sort_by="R,DD"),
            lambda: LinkedInClient.parse_jobs_reference("engineer", easy_apply="yes"),
            lambda: LinkedInClient.parse_jobs_reference(
                "https://www.linkedin.com/jobs/search?f_AL=false"
            ),
            lambda: LinkedInClient.parse_jobs_reference(
                "engineer", under_10_applicants=1  # type: ignore[arg-type]
            ),
            lambda: LinkedInClient.parse_jobs_reference(
                "https://example.com/jobs/search?keywords=engineer"
            ),
            lambda: LinkedInClient.parse_jobs_reference(
                f"https://www.linkedin.com/jobs/view/fixture-{JOB_ID}"
            ),
        ]
        for call in calls:
            with self.subTest(call=call), self.assertRaises(LinkedInInputError):
                call()

    def test_video_object_fields_comments_stats_and_media_are_normalized(self) -> None:
        post = LinkedInClient.parse_post_html(VIDEO_HTML, expected_id=POST_ID)

        self.assertEqual(post["source"], "json_ld")
        self.assertEqual(post["schema_type"], "VideoObject")
        self.assertEqual(post["id"], POST_ID)
        self.assertEqual(post["urn"], POST_URN)
        self.assertEqual(post["author"]["name"], "Satya Fixture")
        self.assertEqual(post["author"]["slug"], "satyanadella")
        self.assertEqual(post["author"]["followers"], 12_345_678)
        self.assertEqual(
            post["stats"], {"likes": 1_234, "comments": 42, "reposts": 17}
        )
        self.assertEqual(post["published_at"], "2026-07-16T15:30:45+00:00")
        self.assertEqual(post["media_type"], "video")
        self.assertEqual(post["video"]["duration"], 77.5)
        self.assertEqual(post["video"]["width"], 1920)
        self.assertEqual(post["video"]["url"], "https://dms.licdn.com/fixture/video.mp4")
        self.assertEqual(post["images"][0]["role"], "thumbnail")
        self.assertEqual(post["comments_total"], 42)
        self.assertEqual(post["comments_embedded"], 2)
        self.assertEqual(post["comments"][0]["likes"], 9)
        self.assertEqual(post["comments"][1]["author"]["kind"], "company")

    def test_social_media_post_uses_full_body_and_image_metadata(self) -> None:
        post = LinkedInClient.parse_post_html(SOCIAL_HTML, expected_id=SOCIAL_ID)

        self.assertEqual(post["schema_type"], "SocialMediaPosting")
        self.assertEqual(post["title"], "Introducing Fixture Red")
        self.assertIn("Second paragraph", post["body"])
        self.assertEqual(post["author"]["kind"], "company")
        self.assertEqual(post["author"]["slug"], "openai")
        self.assertEqual(post["stats"]["likes"], 9001)
        self.assertEqual(post["media_type"], "image")
        self.assertEqual(
            post["images"][0]["url"],
            "https://media.licdn.com/fixture/social-image.jpg",
        )

    def test_open_graph_post_fallback_is_explicit_and_limited(self) -> None:
        source = f"""
        <html><head>
          <link rel="canonical" href="https://www.linkedin.com/posts/{POST_SLUG}">
          <meta property="og:title" content="Fallback title">
          <meta property="og:description"
                content="Fallback body | 1,234 comments on LinkedIn">
          <meta property="og:image" content="https://media.licdn.com/fallback.jpg">
        </head></html>
        """
        post = LinkedInClient.parse_post_html(source, expected_id=POST_ID)

        self.assertEqual(post["source"], "open_graph")
        self.assertEqual(post["body"], "Fallback body")
        self.assertEqual(post["comments_total"], 1_234)
        self.assertIsNone(post["stats"]["likes"])
        self.assertIsNone(post["published_at"])
        self.assertEqual(post["author"]["kind"], None)
        self.assertEqual(post["images"][0]["role"], "open_graph")

    def test_pulse_article_ssr_body_media_and_hidden_urns_are_normalized(self) -> None:
        article = LinkedInClient.parse_article_html(
            ARTICLE_HTML, expected_slug=ARTICLE_SLUG
        )

        self.assertEqual(article["source"], "json_ld+ssr_html")
        self.assertEqual(article["title"], "How do we build a fixture ecosystem?")
        self.assertIn("First fixture paragraph with inline emphasis.", article["body"])
        self.assertIn("First fixture point", article["body"])
        self.assertIn("Final fixture paragraph.", article["body"])
        self.assertEqual(article["author"]["slug"], "satyanadella")
        self.assertEqual(article["stats"]["comments"], 14)
        self.assertEqual(article["reading_time_minutes"], 6)
        self.assertEqual(article["article_id"], "7467640896965210113")
        self.assertEqual(
            article["article_urn"], "urn:li:linkedInArticle:7467640896965210113"
        )
        self.assertEqual(article["legacy_article_urn"], "urn:li:article:fixture-legacy")
        self.assertEqual(article["ugc_post_urn"], "urn:li:ugcPost:7467643123456789012")
        self.assertEqual(len(article["images"]), 2)
        self.assertEqual(article["images"][1]["role"], "inline")
        self.assertEqual(article["videos"][0]["language"], "en_US")
        self.assertEqual(article["videos"][0]["sources"][0]["bitrate"], 1_800_000)
        self.assertEqual(article["embeds"], ["https://www.youtube.com/embed/FIXTURE"])

    def test_person_profile_and_embedded_lists_are_normalized(self) -> None:
        person = LinkedInClient.parse_person_html(
            PERSON_HTML, expected_slug="satyanadella"
        )

        self.assertEqual(person["source"], "json_ld")
        self.assertEqual(person["name"], "Satya Fixture")
        self.assertEqual(person["headline"][0], "Chairman and CEO")
        self.assertEqual(person["followers"], 12_345_678)
        self.assertEqual(person["connections"], 500)
        self.assertEqual(person["connections_text"], "500+")
        self.assertEqual(person["location"]["name"], "Redmond")
        self.assertEqual(person["works_for"][0]["start_date"], "2014-02")
        self.assertEqual(person["alumni_of"][0]["end_date"], "1990")
        self.assertEqual(person["languages"], ["English", "Telugu"])
        self.assertEqual(person["embedded_posts"][0]["id"], POST_ID)
        self.assertEqual(person["embedded_posts"][0]["likes"], 88)
        self.assertEqual(person["embedded_articles"][0]["slug"], ARTICLE_SLUG)
        self.assertTrue(person["embedded_lists_partial"])

    def test_author_articles_exposes_bounded_embedded_subset(self) -> None:
        session = FakeSession([response(PERSON_HTML)])
        result = LinkedInClient(session=session, retries=0).get_author_articles(
            "https://www.linkedin.com/in/satyanadella/recent-activity/articles/",
            limit=1,
        )

        self.assertEqual(result["kind"], "author_articles")
        self.assertEqual(result["source"], "person_json_ld")
        self.assertEqual(result["author"]["slug"], "satyanadella")
        self.assertEqual(result["articles_url"], "https://www.linkedin.com/in/satyanadella/recent-activity/articles/")
        self.assertEqual(result["requested_limit"], 1)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["slug"], ARTICLE_SLUG)
        self.assertTrue(result["partial"])
        self.assertTrue(result["embedded_lists_partial"])
        self.assertEqual(session.calls[0][0], "https://www.linkedin.com/in/satyanadella")

        for invalid in (0, 101, True):
            with self.subTest(limit=invalid), self.assertRaises(LinkedInInputError):
                LinkedInClient(session=FakeSession([])).get_author_articles(
                    "satyanadella", limit=invalid
                )

    def test_company_profile_and_embedded_posts_are_normalized(self) -> None:
        company = LinkedInClient.parse_company_html(COMPANY_HTML, expected_slug="openai")

        self.assertEqual(company["source"], "json_ld")
        self.assertEqual(company["name"], "OpenAI Fixture")
        self.assertEqual(company["website"], "https://openai.example/")
        self.assertEqual(company["followers"], 8_765_432)
        self.assertEqual(company["employee_count"], 4_200)
        self.assertEqual(company["address"]["locality"], "San Francisco")
        self.assertEqual(company["embedded_posts"][0]["id"], SOCIAL_ID)
        self.assertEqual(company["embedded_posts"][0]["likes"], 777)
        self.assertTrue(company["embedded_lists_partial"])

    def test_company_posts_uses_ssr_then_bounded_guest_feed(self) -> None:
        session = FakeSession(
            [response(COMPANY_PUBLIC_HTML), response(FEED_UPDATES_HTML)]
        )
        result = LinkedInClient(session=session, retries=0).get_company_posts(
            "fixture-cloud", limit=3
        )

        self.assertEqual(result["kind"], "company_posts")
        self.assertEqual(result["source"], "company_ssr+organization_guest")
        self.assertEqual(result["company"]["id"], "11130470")
        self.assertEqual(result["company"]["slug"], "fixture-cloud")
        self.assertEqual(result["requested_limit"], 3)
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["pages_fetched"], 2)
        self.assertTrue(result["partial"])
        self.assertTrue(result["embedded_lists_partial"])
        self.assertEqual(
            [item["id"] for item in result["items"]],
            [
                "7485000000000000001",
                "7485000000000000002",
                "7485000000000000003",
            ],
        )
        first = result["items"][0]
        self.assertEqual(first["source"], "ssr_html")
        self.assertEqual(first["author"]["slug"], "fixture-cloud")
        self.assertEqual(first["likes"], 1234)
        self.assertEqual(first["comments"], 56)
        self.assertEqual(len(first["media"]), 1)
        self.assertEqual(first["media"][0]["type"], "image")
        third = result["items"][2]
        self.assertEqual(third["media"][0]["type"], "video")
        self.assertEqual(
            third["media"][0]["url"],
            "https://media.licdn.com/fixture/video.mp4",
        )
        self.assertEqual(third["media"][0]["sources"][0]["bitrate"], 900000)
        query = parse_qs(urlsplit(session.calls[1][0]).query)
        self.assertEqual(query["paginationStart"], ["10"])
        self.assertEqual(query["paginationToken"], ["0-fixture-token"])
        self.assertNotIn("paginationStart", urlsplit(session.calls[0][0]).query)

    def test_company_posts_treats_origin_400_as_bounded_end(self) -> None:
        session = FakeSession(
            [response(COMPANY_PUBLIC_HTML), response("", status=400)]
        )
        result = LinkedInClient(session=session, retries=0).get_company_posts(
            "fixture-cloud", limit=3
        )

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["pages_fetched"], 2)
        self.assertEqual(len(result["requested_urls"]), 2)

    def test_company_posts_never_requests_beyond_the_six_public_fragments(self) -> None:
        session = FakeSession(
            [response(COMPANY_PUBLIC_HTML)]
            + [response(FEED_UPDATES_HTML) for _ in range(6)]
        )
        result = LinkedInClient(session=session, retries=0).get_company_posts(
            "fixture-cloud", limit=70
        )

        self.assertEqual(result["count"], 3)
        self.assertEqual(result["pages_fetched"], 7)
        starts = [
            parse_qs(urlsplit(call[0]).query)["paginationStart"][0]
            for call in session.calls[1:]
        ]
        self.assertEqual(starts, ["10", "20", "30", "40", "50", "60"])

    def test_company_posts_stops_at_an_empty_public_fragment(self) -> None:
        empty_fragment = '<div data-id="entire-feed-card-link"></div>'
        session = FakeSession(
            [
                response(COMPANY_PUBLIC_HTML),
                response(empty_fragment),
                AssertionError("must not request paginationStart=20"),
            ]
        )
        result = LinkedInClient(session=session, retries=0).get_company_posts(
            "fixture-cloud", limit=70
        )

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["pages_fetched"], 2)
        self.assertEqual(len(session.calls), 2)

    def test_company_public_people_and_affiliates_are_partial(self) -> None:
        people = LinkedInClient(
            session=FakeSession([response(COMPANY_PUBLIC_HTML)]), retries=0
        ).get_company_people("https://www.linkedin.com/company/fixture-cloud/")
        self.assertEqual(people["kind"], "company_people")
        self.assertEqual(people["company"]["id"], "11130470")
        self.assertEqual(people["count"], 2)
        self.assertEqual(people["items"][0]["slug"], "alice-fixture")
        self.assertEqual(people["items"][0]["headline"], "Principal Engineer")
        self.assertTrue(people["partial"])
        self.assertTrue(people["embedded_lists_partial"])

        affiliates = LinkedInClient(
            session=FakeSession([response(COMPANY_PUBLIC_HTML)]), retries=0
        ).get_company_affiliates("fixture-cloud")
        self.assertEqual(affiliates["kind"], "company_affiliates")
        self.assertEqual(affiliates["count"], 2)
        self.assertEqual(affiliates["items"][0]["kind"], "showcase")
        self.assertEqual(affiliates["items"][0]["industry"], "Research Services")
        self.assertEqual(affiliates["items"][0]["location"], "London, UK")
        self.assertEqual(affiliates["items"][1]["kind"], "company")
        self.assertTrue(affiliates["partial"])
        self.assertTrue(affiliates["embedded_lists_partial"])

        without_feed_codes = COMPANY_PUBLIC_HTML.replace(
            '    <code id="feedUpdatesBaseUrl"><!--"/organization-guest/api/feedUpdates/11130470?paginationToken=0-fixture-token"--></code>\n',
            "",
        ).replace(
            '    <code id="paginationToken"><!--"0-fixture-token"--></code>\n',
            "",
        )
        people_without_feed = LinkedInClient(
            session=FakeSession([response(without_feed_codes)]), retries=0
        ).get_company_people("fixture-cloud")
        self.assertIsNone(people_without_feed["company"]["id"])
        self.assertEqual(people_without_feed["count"], 2)

    def test_company_feed_rejects_token_url_and_author_identity_errors(self) -> None:
        foreign_feed = COMPANY_PUBLIC_HTML.replace(
            '"/organization-guest/api/feedUpdates/11130470?paginationToken=0-fixture-token"',
            '"https://example.com/organization-guest/api/feedUpdates/11130470?paginationToken=0-fixture-token"',
        )
        mismatched_token = COMPANY_PUBLIC_HTML.replace(
            '<!--"0-fixture-token"--></code>',
            '<!--"different-token"--></code>',
            1,
        )
        wrong_author = FEED_UPDATES_HTML.replace(
            'href="/company/fixture-cloud/"', 'href="/company/other-company/"', 1
        )
        share_urn = COMPANY_PUBLIC_HTML.replace(
            "urn:li:activity:7485000000000000001",
            "urn:li:share:7485000000000000001",
            1,
        )
        url_without_activity = COMPANY_PUBLIC_HTML.replace(
            "/posts/fixture-cloud_first-activity-7485000000000000001-abcd",
            "/company/fixture-cloud/",
            1,
        )
        cases = [
            ([response(foreign_feed)], "owned hosts"),
            ([response(mismatched_token)], "tokens do not match"),
            ([response(share_urn)], "invalid activity URN"),
            ([response(url_without_activity)], "no activity id"),
            (
                [response(COMPANY_PUBLIC_HTML), response(wrong_author)],
                "identity mismatch",
            ),
        ]
        for responses, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                LinkedInResponseError, message
            ):
                LinkedInClient(
                    session=FakeSession(responses), retries=0
                ).get_company_posts("fixture-cloud", limit=3)

    def test_company_sections_reject_foreign_links_and_wrong_page_identity(self) -> None:
        foreign_employee = COMPANY_PUBLIC_HTML.replace(
            'href="/in/alice-fixture/"',
            'href="https://example.com/in/alice-fixture/"',
            1,
        )
        foreign_affiliate = COMPANY_PUBLIC_HTML.replace(
            'href="/showcase/fixture-research/"',
            'href="https://example.com/showcase/fixture-research/"',
            1,
        )
        wrong_company = COMPANY_PUBLIC_HTML.replace(
            'rel="canonical" href="https://www.linkedin.com/company/fixture-cloud/"',
            'rel="canonical" href="https://www.linkedin.com/company/other-company/"',
            1,
        )
        cases = [
            ("get_company_people", foreign_employee, "owned hosts"),
            ("get_company_affiliates", foreign_affiliate, "owned hosts"),
            ("get_company_people", wrong_company, "expected fixture-cloud"),
        ]
        for method, source, message in cases:
            with self.subTest(method=method), self.assertRaisesRegex(
                LinkedInResponseError, message
            ):
                getattr(
                    LinkedInClient(
                        session=FakeSession([response(source)]), retries=0
                    ),
                    method,
                )("fixture-cloud")

    def test_company_public_commands_reject_bad_limits_empty_and_login_pages(self) -> None:
        for limit in (0, 71, True):
            with self.subTest(limit=limit), self.assertRaises(LinkedInInputError):
                LinkedInClient(session=FakeSession([])).get_company_posts(
                    "fixture-cloud", limit=limit
                )

        with self.assertRaisesRegex(LinkedInResponseError, "empty"):
            LinkedInClient(
                session=FakeSession([response("")]), retries=0
            ).get_company_affiliates("fixture-cloud")
        with self.assertRaisesRegex(LinkedInResponseError, "login page"):
            LinkedInClient(
                session=FakeSession(
                    [response("<title>Sign in | LinkedIn</title>")]
                ),
                retries=0,
            ).get_company_people("fixture-cloud")

    def test_company_public_cli_commands_forward_arguments(self) -> None:
        posts_args = _parser().parse_args(
            ["company-posts", "fixture-cloud", "--limit", "7"]
        )
        people_args = _parser().parse_args(
            ["company-people", "https://www.linkedin.com/company/fixture-cloud/"]
        )
        affiliates_args = _parser().parse_args(
            ["company-affiliates", "fixture-cloud"]
        )
        with patch("reverse.linkedin_reverse.cli.LinkedInClient") as client_type:
            client_type.return_value.get_company_posts.return_value = {"items": []}
            self.assertEqual(_run(posts_args), {"items": []})
            client_type.return_value.get_company_posts.assert_called_once_with(
                "fixture-cloud", limit=7
            )

            client_type.return_value.get_company_people.return_value = {"items": []}
            self.assertEqual(_run(people_args), {"items": []})
            client_type.return_value.get_company_people.assert_called_once_with(
                "https://www.linkedin.com/company/fixture-cloud/"
            )

            client_type.return_value.get_company_affiliates.return_value = {
                "items": []
            }
            self.assertEqual(_run(affiliates_args), {"items": []})
            client_type.return_value.get_company_affiliates.assert_called_once_with(
                "fixture-cloud"
            )

    def test_author_articles_cli_forwards_limit(self) -> None:
        args = _parser().parse_args(
            ["author-articles", "satyanadella", "--limit", "4"]
        )
        with patch("reverse.linkedin_reverse.cli.LinkedInClient") as client_type:
            client_type.return_value.get_author_articles.return_value = {"items": []}
            self.assertEqual(_run(args), {"items": []})
            client_type.return_value.get_author_articles.assert_called_once_with(
                "satyanadella", limit=4
            )

    def test_job_detail_fragment_is_structurally_normalized(self) -> None:
        job = LinkedInClient.parse_job_html(JOB_HTML, expected_id=JOB_ID)

        self.assertEqual(job["source"], "guest_job")
        self.assertEqual(job["id"], JOB_ID)
        self.assertEqual(job["urn"], f"urn:li:jobPosting:{JOB_ID}")
        self.assertEqual(job["title"], "Software Engineer")
        self.assertEqual(job["company"]["name"], "Fixture Labs")
        self.assertEqual(job["company"]["slug"], "fixture-labs")
        self.assertEqual(job["location"], "New York, NY")
        self.assertEqual(job["posted_text"], "2 days ago")
        self.assertEqual(job["applicants_text"], "Over 200 applicants")
        self.assertTrue(job["closed"])
        self.assertEqual(job["salary"], "$150,000/yr - $220,000/yr")
        self.assertIn("Ship reliable parsers", job["description"])
        self.assertEqual(job["seniority_level"], "Entry level")
        self.assertEqual(job["employment_type"], "Full-time")
        self.assertEqual(
            job["job_function"], "Engineering and Information Technology"
        )
        self.assertEqual(job["industries"], "Software Development")
        self.assertEqual(job["benefits"], ["Medical insurance"])
        self.assertEqual(
            job["criteria"][0],
            {
                "name": "seniority_level",
                "label": "Seniority level",
                "value": "Entry level",
            },
        )

    def test_job_search_cards_dates_benefits_and_total_are_normalized(self) -> None:
        page = LinkedInClient.parse_jobs_html(JOB_SEARCH_HTML)

        self.assertEqual(page["count"], 2)
        self.assertEqual(page["total"], 321)
        first, second = page["items"]
        self.assertEqual(first["id"], JOB_ID)
        self.assertEqual(first["company"]["slug"], "fixture-labs")
        self.assertEqual(first["posted_at"], "2026-07-20T00:00:00+00:00")
        self.assertEqual(first["posted_timestamp"], 1_784_505_600)
        self.assertEqual(first["benefits"], ["Medical insurance"])
        self.assertEqual(second["id"], SECOND_JOB_ID)
        self.assertEqual(second["posted_text"], "1 day ago")
        self.assertEqual(
            second["url"],
            "https://www.linkedin.com/jobs/view/"
            f"platform-engineer-at-example-cloud-{SECOND_JOB_ID}",
        )

        missing_link = JOB_SEARCH_HTML.replace(
            'class="hidden-nested-link"', 'class="company-name"', 1
        )
        fallback = LinkedInClient.parse_jobs_html(missing_link)["items"][0]
        self.assertEqual(fallback["company"]["name"], "Fixture Labs")
        self.assertEqual(fallback["company"]["url"], "")

    def test_job_html_identity_login_and_card_shape_failures_are_explicit(self) -> None:
        wrong_id = JOB_HTML.replace(f'<!--"{JOB_ID}"-->', '<!--"4441111111"-->')
        with self.assertRaisesRegex(LinkedInResponseError, "metadata id"):
            LinkedInClient.parse_job_html(wrong_id, expected_id=JOB_ID)

        with self.assertRaisesRegex(LinkedInResponseError, "expected"):
            LinkedInClient.parse_job_html(JOB_HTML, expected_id="4441111111")
        with self.assertRaisesRegex(LinkedInResponseError, "login page"):
            LinkedInClient.parse_job_html("<title>Sign in | LinkedIn</title>")
        with self.assertRaisesRegex(LinkedInResponseError, "empty"):
            LinkedInClient.parse_jobs_html("")

        empty = LinkedInClient.parse_jobs_html("<!doctype html><ul></ul>")
        self.assertEqual(empty, {"items": [], "count": 0, "total": None})

        bad_urn = JOB_SEARCH_HTML.replace(
            f"urn:li:jobPosting:{JOB_ID}", f"urn:li:activity:{JOB_ID}", 1
        )
        with self.assertRaisesRegex(LinkedInResponseError, "invalid URN"):
            LinkedInClient.parse_jobs_html(bad_urn)

    def test_open_graph_profile_and_article_fallbacks_are_marked(self) -> None:
        person_html = """
        <link rel="canonical" href="https://www.linkedin.com/in/fixture-person">
        <meta property="og:title" content="Fixture Person - Role | LinkedIn">
        <meta property="og:description"
              content="Fixture Person has 500+ connections on LinkedIn.">
        <meta property="profile:first_name" content="Fixture">
        <meta property="profile:last_name" content="Person">
        """
        person = LinkedInClient.parse_person_html(
            person_html, expected_slug="fixture-person"
        )
        self.assertEqual(person["source"], "open_graph")
        self.assertEqual(person["name"], "Fixture Person")
        self.assertEqual(person["connections"], 500)
        self.assertEqual(person["works_for"], [])

        article_html = f"""
        <link rel="canonical" href="https://www.linkedin.com/pulse/{ARTICLE_SLUG}">
        <meta property="og:title" content="Fallback article">
        <meta property="og:description" content="Fallback summary">
        <meta property="og:image" content="https://media.licdn.com/fallback-cover.jpg">
        <meta name="twitter:data2" content="4 min read">
        """
        article = LinkedInClient.parse_article_html(
            article_html, expected_slug=ARTICLE_SLUG
        )
        self.assertEqual(article["source"], "open_graph")
        self.assertEqual(article["body"], "Fallback summary")
        self.assertIsNone(article["article_urn"])
        self.assertEqual(article["reading_time"], "4 min read")

    def test_canonical_identity_mismatches_are_rejected(self) -> None:
        with self.assertRaisesRegex(LinkedInResponseError, "expected"):
            LinkedInClient.parse_post_html(VIDEO_HTML, expected_id=SOCIAL_ID)
        with self.assertRaisesRegex(LinkedInResponseError, "expected"):
            LinkedInClient.parse_article_html(ARTICLE_HTML, expected_slug="other-article")
        with self.assertRaisesRegex(LinkedInResponseError, "expected"):
            LinkedInClient.parse_person_html(PERSON_HTML, expected_slug="other-person")
        with self.assertRaisesRegex(LinkedInResponseError, "expected"):
            LinkedInClient.parse_company_html(COMPANY_HTML, expected_slug="other-company")

        external = VIDEO_HTML.replace(
            f"https://www.linkedin.com/posts/{POST_SLUG}",
            f"https://example.com/posts/{POST_SLUG}",
        )
        with self.assertRaisesRegex(LinkedInResponseError, "left the owned hosts"):
            LinkedInClient.parse_post_html(external, expected_id=POST_ID)

        wrong_urn = VIDEO_HTML.replace(
            f"urn:li:activity:{POST_ID}", f"urn:li:activity:{SOCIAL_ID}"
        )
        with self.assertRaisesRegex(LinkedInResponseError, "URN id"):
            LinkedInClient.parse_post_html(wrong_urn, expected_id=POST_ID)

    def test_login_pages_empty_html_and_missing_metadata_fail_cleanly(self) -> None:
        login = """
        <meta property="og:title" content="LinkedIn Login, Sign in">
        <meta property="og:url" content="https://www.linkedin.com/login">
        """
        with self.assertRaisesRegex(LinkedInResponseError, "login page"):
            LinkedInClient.parse_post_html(login, expected_id=POST_ID)
        with self.assertRaisesRegex(LinkedInResponseError, "login page"):
            LinkedInClient.parse_post_html(
                "<title>Sign in | LinkedIn</title>",
                expected_id=POST_ID,
                page_url="https://www.linkedin.com/authwall?trk=fixture",
            )
        with self.assertRaisesRegex(LinkedInResponseError, "empty"):
            LinkedInClient.parse_post_html("", expected_id=POST_ID)
        with self.assertRaisesRegex(LinkedInResponseError, "no public post metadata"):
            LinkedInClient.parse_post_html("<html>challenge</html>", expected_id=POST_ID)

    def test_post_request_contract_and_default_headers(self) -> None:
        session = FakeSession([response(VIDEO_HTML)])
        client = LinkedInClient(session=session, timeout=13, retries=0)

        post = client.get_post(POST_ID)

        self.assertEqual(post["id"], POST_ID)
        self.assertEqual(post["requested_url"], f"https://www.linkedin.com/feed/update/{POST_URN}")
        self.assertEqual(session.calls[0][0], f"https://www.linkedin.com/feed/update/{POST_URN}")
        self.assertEqual(session.calls[0][1]["timeout"], 13)
        self.assertTrue(session.calls[0][1]["allow_redirects"])
        self.assertEqual(
            session.calls[0][1]["headers"], {"Referer": "https://www.linkedin.com/"}
        )
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)

    def test_job_request_uses_guest_detail_endpoint(self) -> None:
        session = FakeSession([response(JOB_HTML)])
        client = LinkedInClient(session=session, timeout=11, retries=0)

        job = client.get_job(
            f"https://www.linkedin.com/jobs/view/software-engineer-at-fixture-{JOB_ID}"
        )

        request_url = (
            f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{JOB_ID}"
        )
        self.assertEqual(job["id"], JOB_ID)
        self.assertEqual(job["requested_url"], request_url)
        self.assertEqual(session.calls[0][0], request_url)
        self.assertEqual(session.calls[0][1]["timeout"], 11)

    def test_job_search_paginates_by_raw_card_count_and_tolerates_stale_pages(
        self,
    ) -> None:
        third_id = "4441111111"
        fourth_id = "4442222222"
        next_page = JOB_SEARCH_HTML.replace(JOB_ID, third_id).replace(
            SECOND_JOB_ID, fourth_id
        )
        session = FakeSession(
            [
                response(JOB_SEARCH_HTML),
                response(JOB_SEARCH_HTML),
                response(next_page),
            ]
        )
        client = LinkedInClient(session=session, retries=0)

        result = client.search_jobs(
            "platform engineer",
            location="Paris",
            company_id="1441",
            remote="hybrid",
            sort_by="recent",
            easy_apply=True,
            under_10_applicants=True,
            count=3,
        )

        self.assertEqual(
            [item["id"] for item in result["items"]],
            [JOB_ID, SECOND_JOB_ID, third_id],
        )
        self.assertEqual(result["pages_fetched"], 3)
        self.assertEqual(result["next_start"], 6)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["total"], 321)
        starts = [
            parse_qs(urlsplit(call[0]).query)["start"][0] for call in session.calls
        ]
        self.assertEqual(starts, ["0", "2", "4"])
        query = parse_qs(urlsplit(session.calls[0][0]).query)
        self.assertEqual(query["keywords"], ["platform engineer"])
        self.assertEqual(query["location"], ["Paris"])
        self.assertEqual(query["f_C"], ["1441"])
        self.assertEqual(query["f_WT"], ["3"])
        self.assertEqual(query["sortBy"], ["DD"])
        self.assertEqual(query["f_AL"], ["true"])
        self.assertEqual(query["f_EA"], ["true"])
        self.assertEqual(result["filters"]["sort_by"], "DD")
        self.assertTrue(result["filters"]["easy_apply"])
        self.assertTrue(result["filters"]["under_10_applicants"])

    def test_job_search_stops_after_three_consecutive_pages_add_no_ids(self) -> None:
        session = FakeSession([response(JOB_SEARCH_HTML) for _ in range(4)])
        client = LinkedInClient(session=session, retries=0)

        result = client.search_jobs("engineer", count=5)

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["pages_fetched"], 4)
        self.assertEqual(result["next_start"], 8)
        self.assertFalse(result["has_more"])

    def test_job_search_treats_origin_400_as_pagination_end(self) -> None:
        session = FakeSession(
            [response(JOB_SEARCH_HTML), response("", status=400)]
        )
        client = LinkedInClient(session=session, retries=0)

        result = client.search_jobs("engineer", count=5)

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["pages_fetched"], 2)
        self.assertEqual(result["next_start"], 2)
        self.assertFalse(result["has_more"])

    def test_jobs_cli_forwards_search_filters(self) -> None:
        args = _parser().parse_args(
            [
                "jobs",
                "--company-id",
                "1441",
                "--time-range",
                "week",
                "--job-type",
                "F,C",
                "--experience-level",
                "2,4",
                "--remote",
                "hybrid",
                "--sort-by",
                "recent",
                "--easy-apply",
                "--under-10-applicants",
                "--start",
                "20",
                "--count",
                "30",
            ]
        )
        with patch("reverse.linkedin_reverse.cli.LinkedInClient") as client_type:
            client_type.return_value.search_jobs.return_value = {"items": []}
            result = _run(args)

        self.assertEqual(result, {"items": []})
        client_type.return_value.search_jobs.assert_called_once_with(
            "",
            location=None,
            geo_id=None,
            company_id="1441",
            time_range="week",
            job_type="F,C",
            experience_level="2,4",
            remote="hybrid",
            sort_by="recent",
            easy_apply=True,
            under_10_applicants=True,
            start=20,
            count=30,
        )

    def test_company_jobs_reuses_public_search_with_a_required_company_id(self) -> None:
        session = FakeSession([response(JOB_SEARCH_HTML)])
        client = LinkedInClient(session=session, retries=0)

        result = client.get_company_jobs(
            1441,
            location="Paris",
            geo_id="105015875",
            time_range="week",
            job_type="full_time",
            experience_level="mid_senior",
            remote="hybrid",
            sort_by="recent",
            easy_apply=True,
            under_10_applicants=True,
            start=5,
            count=2,
        )

        self.assertEqual(result["kind"], "company_jobs")
        self.assertEqual(result["company_id"], "1441")
        self.assertEqual(result["count"], 2)
        query = parse_qs(urlsplit(session.calls[0][0]).query)
        self.assertEqual(
            query,
            {
                "location": ["Paris"],
                "geoId": ["105015875"],
                "f_C": ["1441"],
                "f_TPR": ["r604800"],
                "f_JT": ["F"],
                "f_E": ["4"],
                "f_WT": ["3"],
                "sortBy": ["DD"],
                "f_AL": ["true"],
                "f_EA": ["true"],
                "start": ["5"],
            },
        )

    def test_company_job_count_reads_total_from_the_public_search_page(self) -> None:
        session = FakeSession([response(JOB_SEARCH_HTML)])
        client = LinkedInClient(session=session, retries=0)

        result = client.get_company_job_count("1441")

        request_url = "https://www.linkedin.com/jobs/search?f_C=1441"
        self.assertEqual(
            result,
            {
                "kind": "company_job_count",
                "company_id": "1441",
                "count": 321,
                "url": request_url,
            },
        )
        self.assertEqual(session.calls[0][0], request_url)

        missing_total = LinkedInClient(
            session=FakeSession([response("<!doctype html><html></html>")]), retries=0
        )
        with self.assertRaisesRegex(LinkedInResponseError, "totalResults"):
            missing_total.get_company_job_count("1441")

    def test_location_suggestions_normalize_guest_typeahead_json(self) -> None:
        session = FakeSession([response(LOCATION_SUGGESTIONS_JSON)])
        client = LinkedInClient(session=session, retries=0)

        result = client.suggest_job_locations("  Paris  ", count=2)

        self.assertEqual(result["kind"], "location_suggestions")
        self.assertEqual(result["query"], "Paris")
        self.assertEqual(result["count"], 2)
        self.assertEqual(
            result["items"][0],
            {
                "id": "101240143",
                "type": "GEO",
                "name": "Paris, Ile-de-France, France",
                "tracking_id": "TRACKING/PARIS+ONE==",
            },
        )
        request = urlsplit(session.calls[0][0])
        self.assertEqual(request.path, "/jobs-guest/api/typeaheadHits")
        self.assertEqual(
            parse_qs(request.query),
            {
                "origin": ["jserp"],
                "typeaheadType": ["GEO"],
                "geoTypes": [
                    "POPULATED_PLACE,ADMIN_DIVISION_2,MARKET_AREA,COUNTRY_REGION"
                ],
                "query": ["Paris"],
            },
        )

    def test_job_and_company_suggestions_share_public_typeahead_normalization(
        self,
    ) -> None:
        job_session = FakeSession([response(JOB_SUGGESTIONS_JSON)])
        jobs = LinkedInClient(session=job_session, retries=0).suggest_job_keywords(
            "  software  ", count=2
        )

        self.assertEqual(jobs["kind"], "job_suggestions")
        self.assertEqual(jobs["query"], "software")
        self.assertEqual(jobs["count"], 2)
        self.assertEqual([item["type"] for item in jobs["items"]], ["TITLE", "SKILL"])
        self.assertEqual(
            parse_qs(urlsplit(job_session.calls[0][0]).query),
            {"query": ["software"]},
        )

        company_session = FakeSession([response(COMPANY_SUGGESTIONS_JSON)])
        companies = LinkedInClient(
            session=company_session, retries=0
        ).suggest_job_companies("fixture", count=1)

        self.assertEqual(companies["kind"], "company_suggestions")
        self.assertEqual(companies["count"], 1)
        self.assertEqual(companies["items"][0]["type"], "COMPANY")
        self.assertEqual(companies["items"][0]["id"], "11130470")
        self.assertEqual(
            parse_qs(urlsplit(company_session.calls[0][0]).query),
            {"typeaheadType": ["COMPANY"], "query": ["fixture"]},
        )

    def test_company_and_location_inputs_fail_before_public_requests(self) -> None:
        for company_id in ("", "0", "-1", "1,2", True, None):
            with self.subTest(company_id=company_id), self.assertRaises(
                LinkedInInputError
            ):
                LinkedInClient(session=FakeSession([])).get_company_job_count(
                    company_id  # type: ignore[arg-type]
                )

        for count in (0, 101, True):
            with self.subTest(count=count), self.assertRaises(LinkedInInputError):
                LinkedInClient(session=FakeSession([])).suggest_job_locations(
                    "Paris", count=count  # type: ignore[arg-type]
                )
        with self.assertRaises(LinkedInInputError):
            LinkedInClient(session=FakeSession([])).suggest_job_locations("   ")

        malformed = LinkedInClient(
            session=FakeSession([response("not-json")]), retries=0
        )
        with self.assertRaisesRegex(LinkedInResponseError, "JSON is invalid"):
            malformed.suggest_job_locations("Paris")
        wrong_shape = LinkedInClient(
            session=FakeSession([response('{"id":"101240143"}')]), retries=0
        )
        with self.assertRaisesRegex(LinkedInResponseError, "JSON array"):
            wrong_shape.suggest_job_locations("Paris")
        bad_item = LinkedInClient(session=FakeSession([response('["Paris"]')]), retries=0)
        with self.assertRaisesRegex(LinkedInResponseError, "invalid item"):
            bad_item.suggest_job_locations("Paris")

    def test_company_and_location_cli_commands_forward_arguments(self) -> None:
        company_args = _parser().parse_args(
            [
                "company-jobs",
                "1441",
                "--location",
                "Paris",
                "--geo-id",
                "105015875",
                "--time-range",
                "week",
                "--job-type",
                "F,C",
                "--experience-level",
                "2,4",
                "--remote",
                "hybrid",
                "--sort-by",
                "R",
                "--easy-apply",
                "--under-10-applicants",
                "--start",
                "20",
                "--count",
                "30",
            ]
        )
        with patch("reverse.linkedin_reverse.cli.LinkedInClient") as client_type:
            client_type.return_value.get_company_jobs.return_value = {"items": []}
            result = _run(company_args)
        self.assertEqual(result, {"items": []})
        client_type.return_value.get_company_jobs.assert_called_once_with(
            "1441",
            location="Paris",
            geo_id="105015875",
            time_range="week",
            job_type="F,C",
            experience_level="2,4",
            remote="hybrid",
            sort_by="R",
            easy_apply=True,
            under_10_applicants=True,
            start=20,
            count=30,
        )

        count_args = _parser().parse_args(["company-job-count", "1441"])
        with patch("reverse.linkedin_reverse.cli.LinkedInClient") as client_type:
            client_type.return_value.get_company_job_count.return_value = {"count": 321}
            result = _run(count_args)
        self.assertEqual(result, {"count": 321})
        client_type.return_value.get_company_job_count.assert_called_once_with("1441")

        location_args = _parser().parse_args(
            ["location-suggest", "San Francisco", "--count", "7"]
        )
        with patch("reverse.linkedin_reverse.cli.LinkedInClient") as client_type:
            client_type.return_value.suggest_job_locations.return_value = {"items": []}
            result = _run(location_args)
        self.assertEqual(result, {"items": []})
        client_type.return_value.suggest_job_locations.assert_called_once_with(
            "San Francisco", count=7
        )

    def test_job_and_company_suggest_cli_commands_forward_arguments(self) -> None:
        job_args = _parser().parse_args(["job-suggest", "software", "--count", "6"])
        with patch("reverse.linkedin_reverse.cli.LinkedInClient") as client_type:
            client_type.return_value.suggest_job_keywords.return_value = {"items": []}
            result = _run(job_args)
        self.assertEqual(result, {"items": []})
        client_type.return_value.suggest_job_keywords.assert_called_once_with(
            "software", count=6
        )

        company_args = _parser().parse_args(
            ["company-suggest", "fixture", "--count", "4"]
        )
        with patch("reverse.linkedin_reverse.cli.LinkedInClient") as client_type:
            client_type.return_value.suggest_job_companies.return_value = {"items": []}
            result = _run(company_args)
        self.assertEqual(result, {"items": []})
        client_type.return_value.suggest_job_companies.assert_called_once_with(
            "fixture", count=4
        )

    def test_transport_and_transient_http_errors_retry_with_backoff(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture connection failure"),
                response("slow down", status=429),
                response(VIDEO_HTML),
            ]
        )
        client = LinkedInClient(session=session, retries=2)

        with patch("reverse.linkedin_reverse.client.time.sleep") as sleep:
            post = client.get_post(POST_ID)

        self.assertEqual(post["id"], POST_ID)
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])

    def test_deterministic_http_errors_and_external_redirects_fail_cleanly(self) -> None:
        session = FakeSession([response("missing", status=404), response(VIDEO_HTML)])
        client = LinkedInClient(session=session, retries=2)
        with self.assertRaisesRegex(LinkedInResponseError, "HTTP 404"):
            client.get_post(POST_ID)
        self.assertEqual(len(session.calls), 1)

        redirect = FakeSession(
            [response(VIDEO_HTML, url="https://example.com/posts/redirected")]
        )
        redirected = LinkedInClient(session=redirect, retries=0)
        with self.assertRaisesRegex(LinkedInResponseError, "left the owned hosts"):
            redirected.get_post(POST_ID)


if __name__ == "__main__":
    unittest.main()
