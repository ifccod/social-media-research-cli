import unittest
from unittest.mock import Mock, patch

from examples import tiktok_creative_studio_cookie as studio


class CreativeStudioCookieExampleTest(unittest.TestCase):
    def test_one_request_keeps_the_observed_contract(self) -> None:
        response = Mock()
        session = Mock()
        session.request.return_value = response
        cookie = (
            "sessionid=fixture-session; csrftoken=fixture-csrf; "
            "x-creative-csrf-token=fixture-creative-csrf"
        )

        with patch.object(studio.requests, "Session", return_value=session) as factory:
            result = studio.request_once(
                cookie,
                "POST",
                studio.api_path,
                studio.params,
                {},
            )

        self.assertIs(result, response)
        factory.assert_called_once_with(
            impersonate="chrome146",
            trust_env=False,
            proxies={"all": ""},
        )
        _, url = session.request.call_args.args
        kwargs = session.request.call_args.kwargs
        self.assertEqual(url, f"{studio.BASE_URL}{studio.api_path}")
        self.assertEqual(kwargs["params"], studio.params)
        self.assertEqual(kwargs["headers"]["Cookie"], cookie)
        self.assertEqual(kwargs["headers"]["x-csrftoken"], "fixture-csrf")
        self.assertEqual(
            kwargs["headers"]["x-creative-csrf-token"],
            "fixture-creative-csrf",
        )
        self.assertEqual(kwargs["json"], {})

        with self.assertRaises(ValueError):
            studio.request_once(cookie, "GET", "https://example.test/api", {}, None)


if __name__ == "__main__":
    unittest.main()
