import datetime as dt
import unittest

import monitor


BRAND_CFG = {
    "context_terms": ["세무", "회계", "tax", "accounting", "rag", "taxia", "택시아", "xaikorea"],
    "exclude_terms": ["cosmetic", "personal ai assistant", "cloahq.com"],
}


class FakeClient:
    def __init__(self, *, bytes_payload=None, json_payload=None):
        self.bytes_payload = bytes_payload
        self.json_payload = json_payload or {}

    def get_bytes(self, url, **kwargs):
        if self.bytes_payload is None:
            raise AssertionError(url)
        return self.bytes_payload

    def get_json(self, url):
        if "search/repositories" in url:
            return self.json_payload.get("repositories", {"items": []})
        if "search/issues" in url:
            return self.json_payload.get("issues", {"items": []})
        raise AssertionError(url)


class CollectorQualityRegressionTests(unittest.TestCase):
    def test_regulatory_misc_result_is_filtered(self):
        rss = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<rss><channel><item>'
            b'<title>National school staffing regulation</title>'
            b'<link>https://news.google.com/rss/articles/noise</link>'
            b'<pubDate>Fri, 24 Jul 2026 00:30:00 GMT</pubDate>'
            b'<description>Administrative staffing notice with no relevant subject matter.</description>'
            b'<source url="https://law.go.kr">law.go.kr</source>'
            b'</item></channel></rss>'
        )
        items = monitor.fetch_google_news(
            FakeClient(bytes_payload=rss),
            query="site:law.go.kr AI tax",
            name="regression",
            jurisdiction="대한민국",
            locale="en",
            since=dt.datetime(2026, 7, 23, tzinfo=dt.timezone.utc),
            kind="regulatory_news",
            brand_cfg=BRAND_CFG,
        )
        self.assertEqual(items, [])

    def test_global_github_rejects_generic_homonym_but_keeps_xaikorea(self):
        payload = {
            "repositories": {"items": [
                {
                    "full_name": "example/TaxIA",
                    "description": "tax accounting calculator",
                    "html_url": "https://github.com/example/TaxIA",
                    "updated_at": "2026-07-24T00:00:00Z",
                },
                {
                    "full_name": "xaikorea/taxia-integration",
                    "description": "XAIKOREA Korean tax Graph-RAG integration",
                    "html_url": "https://github.com/xaikorea/taxia-integration",
                    "updated_at": "2026-07-24T00:00:00Z",
                },
            ]},
            "issues": {"items": []},
        }
        items = monitor.fetch_github_global(
            FakeClient(json_payload=payload),
            dt.datetime(2026, 7, 23, tzinfo=dt.timezone.utc),
            BRAND_CFG,
        )
        self.assertEqual(len(items), 1)
        self.assertIn("xaikorea", items[0].url.lower())


if __name__ == "__main__":
    unittest.main()
