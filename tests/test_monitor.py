import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

import monitor


BRAND_CFG = {
    "context_terms": ["세무", "회계", "tax", "accounting", "rag", "김재환", "taxia", "택시아", "xaikorea"],
    "exclude_terms": ["화장품", "cosmetic", "skincare", "personal ai assistant", "voice latency", "cloahq.com"],
}


class FakeClient:
    def __init__(self, *, bytes_map=None, json_map=None, text_map=None):
        self.bytes_map = bytes_map or {}
        self.json_map = json_map or {}
        self.text_map = text_map or {}

    def get_bytes(self, url, **kwargs):
        for key, value in self.bytes_map.items():
            if key in url:
                return value
        raise AssertionError(f"unexpected byte URL: {url}")

    def get_json(self, url):
        for key, value in self.json_map.items():
            if key in url:
                return value
        raise AssertionError(f"unexpected JSON URL: {url}")

    def get_text(self, url):
        for key, value in self.text_map.items():
            if key in url:
                return value
        raise AssertionError(f"unexpected text URL: {url}")


class MonitorTests(unittest.TestCase):
    def test_brand_filter_accepts_product_context(self):
        self.assertTrue(monitor.brand_relevant(
            "XAIKOREA의 세무·회계 SaaS TAXiA와 CLOA 엔진 업데이트",
            "https://example.com/article",
            BRAND_CFG,
        ))
        self.assertTrue(monitor.brand_relevant(
            "taxia-core Korean Tax AI Graph-RAG release",
            "https://pypi.org/project/taxia-core/",
            BRAND_CFG,
        ))

    def test_brand_filter_rejects_unrelated_cloa_and_cosmetics(self):
        self.assertFalse(monitor.brand_relevant(
            "Cloa personal AI assistant with voice latency and companions",
            "https://cloahq.com/",
            BRAND_CFG,
        ))
        self.assertFalse(monitor.brand_relevant(
            "XAIKOREA cosmetic skincare PDRN mascara",
            "https://example.com/cosmetics",
            BRAND_CFG,
        ))

    def test_event_uid_changes_with_snapshot(self):
        first = monitor.make_uid("공식 페이지 변경", "https://example.com/page#aaa", "2026-07-24T00:00:00Z", "official_snapshot")
        second = monitor.make_uid("공식 페이지 변경", "https://example.com/page#bbb", "2026-07-25T00:00:00Z", "official_snapshot")
        self.assertNotEqual(first, second)

    def test_google_news_filters_and_classifies(self):
        rss = b'''<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel>
          <item>
            <title>XAIKOREA, TAXiA CLOA engine release - Example News</title>
            <link>https://news.google.com/rss/articles/abc</link>
            <pubDate>Fri, 24 Jul 2026 00:30:00 GMT</pubDate>
            <description><![CDATA[XAIKOREA tax accounting Graph-RAG product update]]></description>
            <source url="https://example.com">Example News</source>
          </item>
          <item>
            <title>Cloa personal AI companion - Other</title>
            <link>https://news.google.com/rss/articles/unrelated</link>
            <pubDate>Fri, 24 Jul 2026 00:40:00 GMT</pubDate>
            <description><![CDATA[voice latency and AI companion]]></description>
            <source url="https://cloahq.com">Other</source>
          </item>
        </channel></rss>'''
        client = FakeClient(bytes_map={"news.google.com": rss})
        items = monitor.fetch_google_news(
            client,
            query='"TAXiA"',
            name="Brand-Test",
            jurisdiction="글로벌",
            locale="en",
            since=dt.datetime(2026, 7, 23, tzinfo=dt.timezone.utc),
            kind="brand_news",
            brand_cfg=BRAND_CFG,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].category, "TAXiA·CLOA")
        self.assertIn("TAXiA", items[0].title)

    def test_merge_duplicate_items_preserves_best_score_and_queries(self):
        base = dict(
            uid="same",
            title="동일 제목",
            url="https://example.com/a",
            source="A",
            published_at="2026-07-24T00:00:00Z",
            jurisdiction="대한민국",
            category="세무·조세",
            kind="regulatory_news",
            summary="짧음",
            importance="보통",
            score=40,
            status="RSS",
            evidence="RSS",
            relevance="관련",
        )
        a = monitor.Item(**base, query_names=["q1"])
        b_data = dict(base)
        b_data.update(score=70, importance="높음", summary="더 긴 설명")
        b = monitor.Item(**b_data, query_names=["q2"])
        merged = monitor.merge_duplicate_items([a, b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].score, 70)
        self.assertEqual(merged[0].query_names, ["q1", "q2"])

    def test_pypi_baseline_reports_latest_only(self):
        payload = {
            "info": {
                "version": "1.0.1",
                "requires_python": ">=3.9",
                "package_url": "https://pypi.org/project/taxia-core/",
            },
            "releases": {
                "1.0.0": [{"upload_time_iso_8601": "2026-01-22T00:00:00Z"}],
                "1.0.1": [{"upload_time_iso_8601": "2026-01-23T00:00:00Z"}],
            },
        }
        client = FakeClient(json_map={"pypi.org": payload})
        items, snapshots = monitor.fetch_pypi(
            client,
            "taxia-core",
            dt.datetime(2026, 7, 23, tzinfo=dt.timezone.utc),
            {"snapshots": {}},
        )
        self.assertEqual(len(items), 1)
        self.assertIn("1.0.1", items[0].title)
        self.assertEqual(snapshots["pypi:taxia-core"]["version"], "1.0.1")

    def test_report_labels_no_results_as_non_conclusive(self):
        text = monitor.render_report(
            report_date=dt.date(2026, 7, 24),
            run_at=dt.datetime(2026, 7, 23, 22, tzinfo=dt.timezone.utc),
            since=dt.datetime(2026, 7, 22, 22, tzinfo=dt.timezone.utc),
            items=[],
            health=[monitor.Health("test", True, 0)],
            timezone=ZoneInfo("Asia/Seoul"),
            repository="LifeIsMoment/news-agent",
            max_items=100,
        )
        self.assertIn("변화가 없다는 확정 결론이 아니라", text)
        self.assertIn("수집 소스 상태", text)

    def test_config_is_valid_and_schedule_hour_is_seven(self):
        config = json.loads(Path("config/sources.json").read_text(encoding="utf-8"))
        self.assertEqual(config["report_hour_kst"], 7)
        self.assertGreaterEqual(len(config["regulatory_news_queries"]), 20)
        self.assertIn("xaikorea/taxia", config["brand"]["github_repositories"])


if __name__ == "__main__":
    unittest.main()
