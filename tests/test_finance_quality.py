import copy
import datetime as dt
import unittest

import finance_monitor as monitor
import finance_monitor_entry as entry
import finance_monitor_quality as quality


def make_item(**updates):
    data = dict(
        uid="x", title="New AI accounting benchmark", url="https://example.com/x",
        source="Example", published_at="2026-07-24T00:00:00Z", jurisdiction="글로벌",
        track="논문·벤치마크", category="논문·벤치마크", kind="arxiv_paper",
        summary="Financial accounting benchmark for large language models",
        priority="P1", score=65, status="사전공개 논문 메타데이터",
        confidence="높음", source_type="paper_primary", evidence="arXiv API",
        impact="old TAXiA/CLOA text", query_names=["ARXIV-ACCOUNTING"],
    )
    data.update(updates)
    return monitor.Item(**data)


class CoreFirstPolicyTests(unittest.TestCase):
    def test_taxia_activity_is_demoted_to_appendix(self):
        item = make_item(
            title="xaikorea/taxia release", track="TAXiA·CLOA 직접 관련",
            kind="github_release", source_type="repository_primary", score=100, priority="P0",
            query_names=["xaikorea/taxia"],
        )
        normalized = entry.normalize_item(item, monitor, dt.datetime(2026, 7, 24, tzinfo=dt.timezone.utc))
        self.assertEqual(normalized.track, entry.APPENDIX_TRACK)
        self.assertNotIn(normalized.priority, {"P0", "P1"})

    def test_baseline_and_generic_commit_cannot_enter_top_priority(self):
        baseline = make_item(title="OpenDART 기준선 등록", status="공식 페이지 기준선", source_type="official_primary", score=90, priority="P0")
        commit = make_item(title="Project commit: update README", kind="github_commit", source_type="repository_primary", score=80, priority="P0")
        self.assertEqual(entry.normalize_item(baseline, monitor).priority, "P3")
        self.assertEqual(entry.normalize_item(commit, monitor).priority, "P3")

    def test_current_official_rule_remains_p0(self):
        item = make_item(
            title="Official AI accounting regulation enters into force",
            summary="Mandatory audit trail and internal control rule",
            source_type="official_primary", category="AI 규제·거버넌스",
            kind="official_rule", score=60, priority="P1",
        )
        normalized = entry.normalize_item(item, monitor, dt.datetime(2026, 7, 24, tzinfo=dt.timezone.utc))
        self.assertEqual(normalized.priority, "P0")

    def test_section_order_puts_specific_project_last(self):
        config = entry.apply_core_first_policy({"news_queries": [], "github_repositories": [], "pypi_packages": []})
        self.assertEqual(config["section_order"][-1], entry.APPENDIX_TRACK)
        self.assertNotEqual(config["section_order"][0], entry.APPENDIX_TRACK)

    def test_report_core_summary_excludes_taxia(self):
        core = make_item()
        appendix = make_item(
            title="TAXiA release", track="TAXiA·CLOA 직접 관련", kind="github_release",
            source_type="repository_primary", score=100, priority="P0", query_names=["taxia-core"],
        )
        items = [entry.normalize_item(core, monitor), entry.normalize_item(appendix, monitor)]
        report = entry.render_report(
            monitor, report_date=dt.date(2026, 7, 24),
            run_at=dt.datetime(2026, 7, 24, tzinfo=dt.timezone.utc),
            since=dt.datetime(2026, 7, 23, tzinfo=dt.timezone.utc),
            items=items, health=[monitor.Health("x", "논문", True, 1)],
            timezone=dt.timezone.utc, repository="LifeIsMoment/news-agent",
            config={"section_order": entry.CORE_SECTION_ORDER},
        )
        headline = report.split("## 상용 서비스·기업 업데이트", 1)[0]
        self.assertIn("New AI accounting benchmark", headline)
        self.assertNotIn("TAXiA release", headline)


class QualityOptimizerTests(unittest.TestCase):
    def test_metrics_measure_core_purity_and_taxia_share(self):
        core = make_item().to_dict()
        taxia = make_item(title="TAXiA release", track="TAXiA·CLOA 직접 관련", query_names=["taxia-core"]).to_dict()
        reports = [{"items": [core, taxia], "health": [{"ok": True}]}]
        metrics = quality.calculate_metrics(reports, {"workflow_runs": [{"conclusion": "success"}]})
        self.assertEqual(metrics.top_core_purity, 0.5)
        self.assertEqual(metrics.taxia_top_share, 0.5)

    def test_noisy_report_increases_minimum_score(self):
        config = {"min_report_score": 30, "max_workers": 8, "news_queries": [], "github_repositories": []}
        metrics = quality.QualityMetrics(
            reports=1, items=100, top_count=20, top_core_purity=0.5,
            primary_evidence_share=0.5, official_or_paper_share=0.2,
            taxia_top_share=0.0, baseline_top_share=0.0, noise_top_share=0.2,
            health_rate=1.0, category_coverage=3, actionable_core_items=5,
            official_items=1, paper_items=1, vendor_items=1, open_source_items=1,
            secondary_items=10, quality_score=50, pipeline_success_rate=1.0,
            pipeline_average_minutes=5.0, pipeline_timed_out=0,
        )
        proposed, _ = quality.propose_config(copy.deepcopy(config), {"thresholds": {}}, metrics, [])
        self.assertEqual(proposed["min_report_score"], 32)

    def test_repeated_safe_noise_adds_query_exclusion(self):
        config = {
            "news_queries": [{"name": "Q", "exclude_any": [], "score_boost": 2}],
            "github_repositories": [], "min_report_score": 30, "max_workers": 8,
        }
        item = make_item(
            title="Finance AI conference recruitment", summary="채용 모집",
            source_type="secondary_index", priority="P3", score=20, query_names=["Q"],
        ).to_dict()
        metrics = quality.QualityMetrics(
            reports=1, items=2, top_count=2, top_core_purity=0.0,
            primary_evidence_share=0.0, official_or_paper_share=0.0,
            taxia_top_share=0.0, baseline_top_share=0.0, noise_top_share=1.0,
            health_rate=1.0, category_coverage=0, actionable_core_items=0,
            official_items=0, paper_items=0, vendor_items=0, open_source_items=0,
            secondary_items=2, quality_score=10, pipeline_success_rate=1.0,
            pipeline_average_minutes=1.0, pipeline_timed_out=0,
        )
        proposed, _ = quality.propose_config(config, {"thresholds": {}, "safe_noise_terms": ["채용"]}, metrics, [item, item])
        self.assertIn("채용", proposed["news_queries"][0]["exclude_any"])

    def test_two_timeouts_raise_only_workflow_timeout(self):
        metrics = quality.QualityMetrics(
            reports=1, items=1, top_count=1, top_core_purity=1.0,
            primary_evidence_share=1.0, official_or_paper_share=1.0,
            taxia_top_share=0.0, baseline_top_share=0.0, noise_top_share=0.0,
            health_rate=1.0, category_coverage=1, actionable_core_items=1,
            official_items=1, paper_items=0, vendor_items=0, open_source_items=0,
            secondary_items=0, quality_score=90, pipeline_success_rate=0.7,
            pipeline_average_minutes=44.0, pipeline_timed_out=2,
        )
        proposed, changes = quality.propose_workflow("jobs:\n  x:\n    timeout-minutes: 45\n", metrics)
        self.assertIn("timeout-minutes: 50", proposed)
        self.assertEqual(len(changes), 1)


if __name__ == "__main__":
    unittest.main()
