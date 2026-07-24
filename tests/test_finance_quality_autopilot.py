import copy
import unittest

import finance_monitor_quality as quality
import finance_monitor_quality_entry as autopilot


def metrics(**updates):
    data = dict(
        reports=1, items=20, top_count=20, top_core_purity=1.0,
        primary_evidence_share=1.0, official_or_paper_share=0.3,
        taxia_top_share=0.0, baseline_top_share=0.0, noise_top_share=0.0,
        health_rate=1.0, category_coverage=6, actionable_core_items=6,
        official_items=2, paper_items=2, vendor_items=2, open_source_items=5,
        secondary_items=1, quality_score=90, pipeline_success_rate=1.0,
        pipeline_average_minutes=2.0, pipeline_timed_out=0,
    )
    data.update(updates)
    return quality.QualityMetrics(**data)


class QualityAutopilotTests(unittest.TestCase):
    def test_policy_version_never_decreases(self):
        config = {
            "priority_policy_version": 3,
            "min_report_score": 30,
            "max_issue_items": 10,
            "max_report_items": 180,
            "max_workers": 4,
            "core_top_limit": 10,
            "taxia_appendix_limit": 5,
            "news_queries": [],
            "github_repositories": [],
        }
        proposed, changes = autopilot.guarded_propose_config(
            copy.deepcopy(config), {"thresholds": {}}, metrics(), []
        )
        self.assertEqual(proposed["priority_policy_version"], 3)
        self.assertFalse(any("3 → 2" in change for change in changes))

    def test_old_policy_is_upgraded_to_current_minimum(self):
        config = {
            "priority_policy_version": 2,
            "min_report_score": 30,
            "max_issue_items": 10,
            "max_report_items": 180,
            "max_workers": 4,
            "core_top_limit": 10,
            "taxia_appendix_limit": 5,
            "news_queries": [],
            "github_repositories": [],
        }
        proposed, changes = autopilot.guarded_propose_config(
            copy.deepcopy(config), {"thresholds": {}}, metrics(), []
        )
        self.assertEqual(proposed["priority_policy_version"], autopilot.MIN_POLICY_VERSION)
        self.assertTrue(any("priority_policy_version" in change for change in changes))

    def test_generic_algorithmic_auditing_paper_is_noise(self):
        item = {
            "title": "Open Veins of Algorithmic Auditing",
            "summary": "AI assessment and accountability in public-sector algorithms",
            "source_type": "paper_primary",
            "track": "논문·벤치마크",
            "priority": "P1",
            "kind": "arxiv_paper",
            "query_names": ["ARXIV-AUDIT-AI"],
        }
        self.assertTrue(autopilot.is_weak_paper(item))
        self.assertFalse(autopilot.guarded_is_core(item))
        self.assertTrue(autopilot.guarded_is_noise(item))

    def test_financial_reporting_paper_remains_core(self):
        item = {
            "title": "Evidence-Grounded SEC Filing Question Answering",
            "summary": "A financial reporting and accounting benchmark over SEC filings",
            "source_type": "paper_primary",
            "track": "논문·벤치마크",
            "priority": "P1",
            "kind": "arxiv_paper",
            "query_names": ["ARXIV-FINANCIAL-QA-BENCHMARK"],
        }
        self.assertFalse(autopilot.is_weak_paper(item))
        self.assertTrue(autopilot.guarded_is_core(item))
        self.assertFalse(autopilot.guarded_is_noise(item))


if __name__ == "__main__":
    unittest.main()
