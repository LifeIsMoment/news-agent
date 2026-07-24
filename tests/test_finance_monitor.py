import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

import finance_monitor as monitor


class FakeClient:
    def __init__(self, *, bytes_map=None, json_map=None, text_map=None):
        self.bytes_map = bytes_map or {}
        self.json_map = json_map or {}
        self.text_map = text_map or {}

    @staticmethod
    def _lookup(mapping, url):
        for key in sorted(mapping, key=len, reverse=True):
            if key in url:
                return mapping[key]
        raise AssertionError(f"unexpected URL: {url}")

    def get_bytes(self, url, **kwargs):
        return self._lookup(self.bytes_map, url)

    def get_json(self, url):
        return self._lookup(self.json_map, url)

    def get_text(self, url):
        return self._lookup(self.text_map, url)


class FinanceMonitorTests(unittest.TestCase):
    def test_short_ai_token_uses_word_boundary(self):
        self.assertFalse(monitor.contains_term("Company said financial results improved", "ai"))
        self.assertTrue(monitor.contains_term("Company launched an AI tax agent", "ai"))
        self.assertTrue(monitor.contains_term("AI 기반 세무 서비스", "AI"))

    def test_relevance_gate_requires_ai_and_tax_context(self):
        rule = {
            "required_all_groups": [
                ["AI", "artificial intelligence", "agent"],
                ["tax", "세무", "VAT"],
            ],
            "exclude_any": ["AI companion", "casino"],
        }
        self.assertTrue(monitor.passes_gate("New AI tax agent launched", "https://example.com", rule))
        self.assertFalse(monitor.passes_gate("New corporate tax guidance", "https://example.com", rule))
        self.assertFalse(monitor.passes_gate("New AI companion for tax season", "https://example.com", rule))

    def test_domain_allowlist_blocks_non_official_source(self):
        rule = {
            "required_all_groups": [["AI"], ["tax"]],
            "domain_allowlist": ["irs.gov"],
        }
        self.assertTrue(monitor.passes_gate("AI tax guidance", "https://www.irs.gov/news", rule))
        self.assertFalse(monitor.passes_gate("AI tax guidance", "https://example.com/news", rule))

    def test_google_news_applies_strict_gate_and_source_type(self):
        rss = b'''<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel>
          <item>
            <title>IRS issues AI tax administration guidance - IRS</title>
            <link>https://news.google.com/rss/articles/official</link>
            <pubDate>Fri, 24 Jul 2026 00:30:00 GMT</pubDate>
            <description><![CDATA[Artificial intelligence controls for tax administration]]></description>
            <source url="https://www.irs.gov">IRS</source>
          </item>
          <item>
            <title>AI companion launches new voice mode - Other</title>
            <link>https://news.google.com/rss/articles/unrelated</link>
            <pubDate>Fri, 24 Jul 2026 00:40:00 GMT</pubDate>
            <description><![CDATA[Personal assistant and dating companion]]></description>
            <source url="https://example.com">Other</source>
          </item>
        </channel></rss>'''
        row = {
            "name": "US-IRS",
            "query": "site:irs.gov AI tax",
            "track": "법·제도·감사",
            "category": "세무 AI·조세기술",
            "jurisdiction": "미국",
            "locale": "en",
            "required_all_groups": [["AI", "artificial intelligence"], ["tax"]],
            "exclude_any": ["AI companion"],
            "domain_allowlist": ["irs.gov"],
            "source_type": "official_primary",
        }
        config = {"official_domains": ["irs.gov"], "vendor_domains": []}
        items = monitor.fetch_google_news(
            FakeClient(bytes_map={"news.google.com": rss}),
            row=row,
            since=dt.datetime(2026, 7, 23, tzinfo=dt.timezone.utc),
            config=config,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_type, "official_primary")
        self.assertEqual(items[0].track, "법·제도·감사")
        self.assertIn("TAXiA/CLOA", monitor.render_item(items[0], ZoneInfo("Asia/Seoul"), 1))

    def test_arxiv_parser_returns_primary_paper(self):
        atom = b'''<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>https://arxiv.org/abs/2607.12345</id>
            <updated>2026-07-24T01:00:00Z</updated>
            <published>2026-07-23T01:00:00Z</published>
            <title>TaxReasoner: A Benchmark for Tax LLM Reasoning</title>
            <summary>We evaluate large language models on tax reasoning and citation.</summary>
            <author><name>Jane Doe</name></author>
          </entry>
        </feed>'''
        row = {
            "name": "ARXIV-TAX",
            "query": 'all:"tax reasoning"',
            "track": "논문·벤치마크",
            "category": "논문·벤치마크",
            "required_all_groups": [["tax"], ["benchmark", "large language model"]],
        }
        items = monitor.fetch_arxiv(
            FakeClient(bytes_map={"export.arxiv.org": atom}),
            row,
            dt.datetime(2026, 7, 23, tzinfo=dt.timezone.utc),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_type, "paper_primary")
        self.assertEqual(items[0].confidence.split("(")[0], "높음")
        self.assertIn("Jane Doe", items[0].summary)

    def test_github_repo_baseline_tracks_metadata_release_commit_and_issue(self):
        metadata = {
            "html_url": "https://github.com/example/tax-agent",
            "updated_at": "2026-07-24T01:00:00Z",
            "pushed_at": "2026-07-24T00:59:00Z",
            "default_branch": "main",
            "stargazers_count": 12,
            "forks_count": 2,
            "open_issues_count": 3,
            "archived": False,
        }
        releases = [{
            "tag_name": "v1.0.0",
            "published_at": "2026-07-24T00:30:00Z",
            "html_url": "https://github.com/example/tax-agent/releases/tag/v1.0.0",
            "body": "First tax AI agent release",
        }]
        commits = [{
            "sha": "abcdef1234567890",
            "html_url": "https://github.com/example/tax-agent/commit/abcdef",
            "commit": {
                "message": "feat: add VAT validation",
                "committer": {"date": "2026-07-24T00:20:00Z"},
            },
        }]
        issues = [{
            "number": 7,
            "title": "Incorrect tax year",
            "body": "Effective-date validation needed",
            "state": "open",
            "updated_at": "2026-07-24T00:10:00Z",
            "html_url": "https://github.com/example/tax-agent/issues/7",
        }]
        client = FakeClient(json_map={
            "api.github.com/repos/example/tax-agent/releases?": releases,
            "api.github.com/repos/example/tax-agent/commits?": commits,
            "api.github.com/repos/example/tax-agent/issues?": issues,
            "api.github.com/repos/example/tax-agent": metadata,
        })
        asset = {
            "repo": "example/tax-agent",
            "track": "오픈소스 프로젝트",
            "category": "세무 AI·조세기술",
            "monitor_issues": True,
            "baseline_releases": 0,
            "baseline_commits": 3,
            "baseline_issues": 5,
        }
        items, snapshots = monitor.fetch_github_repo(
            client,
            asset,
            dt.datetime(2026, 7, 23, tzinfo=dt.timezone.utc),
            {"snapshots": {}},
        )
        self.assertEqual(len(items), 4)
        self.assertIn("finance:github:example/tax-agent", snapshots)
        self.assertTrue(all(item.source_type == "repository_primary" for item in items))

    def test_pypi_baseline_reports_latest_only(self):
        payload = {
            "info": {
                "version": "2.0.0",
                "requires_python": ">=3.10",
                "package_url": "https://pypi.org/project/tax-engine/",
            },
            "releases": {
                "1.0.0": [{"upload_time_iso_8601": "2025-01-01T00:00:00Z"}],
                "2.0.0": [{"upload_time_iso_8601": "2026-07-24T00:00:00Z"}],
            },
        }
        asset = {"package": "tax-engine", "category": "세무 AI·조세기술"}
        items, snapshots = monitor.fetch_pypi(
            FakeClient(json_map={"pypi.org": payload}),
            asset,
            dt.datetime(2026, 7, 23, tzinfo=dt.timezone.utc),
            {"snapshots": {}},
        )
        self.assertEqual(len(items), 1)
        self.assertIn("2.0.0", items[0].title)
        self.assertEqual(snapshots["finance:pypi:tax-engine"]["version"], "2.0.0")

    def test_merge_duplicate_prefers_higher_score_and_combines_queries(self):
        base = dict(
            uid="same",
            title="Same finance AI release",
            url="https://example.com/item",
            source="A",
            published_at="2026-07-24T00:00:00Z",
            jurisdiction="글로벌",
            track="상용 서비스·기업 업데이트",
            category="재무분석·FP&A·CFO",
            kind="news",
            summary="short",
            priority="P2",
            score=40,
            status="RSS",
            confidence="낮음~중간",
            source_type="secondary_index",
            evidence="RSS",
            impact="impact",
        )
        first = monitor.Item(**base, query_names=["q1"])
        better_data = dict(base)
        better_data.update(score=70, priority="P1", summary="longer summary")
        second = monitor.Item(**better_data, query_names=["q2"])
        merged = monitor.merge_duplicate_items([first, second])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].score, 70)
        self.assertEqual(merged[0].query_names, ["q1", "q2"])

    def test_report_no_results_is_explicitly_non_conclusive(self):
        config = {
            "report_title": "AI 재무·세무·회계 자동 모니터링",
            "section_order": monitor.DEFAULT_SECTION_ORDER,
        }
        report = monitor.render_report(
            report_date=dt.date(2026, 7, 24),
            run_at=dt.datetime(2026, 7, 23, 22, tzinfo=dt.timezone.utc),
            since=dt.datetime(2026, 7, 22, 22, tzinfo=dt.timezone.utc),
            items=[],
            health=[monitor.Health("test", "뉴스·공식기관", True, 0)],
            timezone=ZoneInfo("Asia/Seoul"),
            repository="LifeIsMoment/news-agent",
            config=config,
        )
        self.assertIn("새롭거나 의미 있는 변화를 확인하지 못했습니다", report)
        self.assertIn("변화가 없다는 확정 결론이 아니라", report)
        self.assertIn("수집 소스 상태", report)

    def test_priority_scoring_promotes_official_regulatory_change(self):
        score, priority = monitor.score_item(
            "Official AI tax regulation enters into force with mandatory audit trail",
            source_type="official_primary",
            category="AI 규제·거버넌스",
            kind="official_rule",
            score_boost=8,
        )
        self.assertGreaterEqual(score, 75)
        self.assertEqual(priority, "P0")

    def test_config_is_detailed_and_scheduled_at_seven(self):
        config = json.loads(Path("config/finance_sources.json").read_text(encoding="utf-8"))
        self.assertEqual(config["report_hour_kst"], 7)
        self.assertEqual(config["report_minute_kst"], 30)
        self.assertEqual(config["watchdog_minute_kst"], 50)
        self.assertNotIn("논문", config["critical_source_groups"])
        self.assertLessEqual(config.get("max_workers", 4), 4)
        self.assertGreaterEqual(len(config["news_queries"]), 30)
        self.assertGreaterEqual(len(config["arxiv_queries"]), 6)
        self.assertGreaterEqual(len(config["github_repositories"]), 12)
        self.assertIn("xaikorea/taxia", [row["repo"] for row in config["github_repositories"]])
        self.assertIn("patronus-ai/financebench", [row["repo"] for row in config["github_repositories"]])
        self.assertIn("finance-tax-ai-monitoring", config["issue_label"])

    def test_snapshot_hash_ignores_script_content(self):
        first = '<html><script>token=1</script><body><h1>API guide</h1></body></html>'
        second = '<html><script>token=2</script><body> <h1>API guide</h1> </body></html>'
        self.assertEqual(monitor.normalized_page_hash(first), monitor.normalized_page_hash(second))


if __name__ == "__main__":
    unittest.main()
