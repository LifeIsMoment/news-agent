import datetime as dt
import unittest

import finance_monitor as monitor
import finance_monitor_entry as entry


def make_item(**updates):
    data = dict(
        uid="feedback", title="AI accounting benchmark", url="https://example.com/item",
        source="Example", published_at="2026-07-24T00:00:00Z", jurisdiction="글로벌",
        track="논문·벤치마크", category="논문·벤치마크", kind="arxiv_paper",
        summary="Financial accounting benchmark for large language models",
        priority="P1", score=65, status="사전공개 논문 메타데이터",
        confidence="높음", source_type="paper_primary", evidence="arXiv API",
        impact="impact", query_names=["ARXIV-ACCOUNTING"],
    )
    data.update(updates)
    return monitor.Item(**data)


class FirstFeedbackRegressionTests(unittest.TestCase):
    def test_recruitment_notice_is_not_a_core_official_signal(self):
        item = make_item(
            title="경제통계팀 통계조사보조원 채용 안내",
            summary="한국은행 채용 모집 공고",
            track="공공 데이터·API", category="공공 데이터·API",
            kind="news", source_type="official_primary", score=82, priority="P0",
        )
        normalized = entry.normalize_item(item, monitor, dt.datetime(2026, 7, 24, tzinfo=dt.timezone.utc))
        self.assertEqual(normalized.priority, "P3")
        self.assertFalse(entry.is_core_item(normalized))

    def test_generic_algorithmic_auditing_paper_is_not_accounting_core(self):
        item = make_item(
            title="Open Veins of Algorithmic Auditing",
            summary="AI assessment and accountability in public-sector algorithms",
            score=82, priority="P0",
            query_names=["ARXIV-AUDIT-AI"],
        )
        normalized = entry.normalize_item(item, monitor, dt.datetime(2026, 7, 24, tzinfo=dt.timezone.utc))
        self.assertEqual(normalized.priority, "P3")
        self.assertFalse(entry.is_core_item(normalized))

    def test_financial_reporting_benchmark_remains_core(self):
        item = make_item(
            title="FinSAgent: Evidence-Grounded SEC Filing Question Answering",
            summary="A financial reporting benchmark over SEC filings with accounting evidence",
            score=62, priority="P1",
        )
        normalized = entry.normalize_item(item, monitor, dt.datetime(2026, 7, 24, tzinfo=dt.timezone.utc))
        self.assertEqual(normalized.priority, "P1")
        self.assertTrue(entry.is_core_item(normalized))

    def test_temporary_paper_outage_is_not_a_global_failure_condition(self):
        config = entry.apply_core_first_policy({
            "critical_source_groups": ["뉴스·공식기관", "GitHub 고정 추적", "논문"],
            "news_queries": [], "github_repositories": [], "pypi_packages": [],
        })
        self.assertEqual(config["critical_source_groups"], ["뉴스·공식기관", "GitHub 고정 추적"])
        self.assertLessEqual(config["max_workers"], 4)


if __name__ == "__main__":
    unittest.main()
