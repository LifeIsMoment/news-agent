import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import quality


RUN_AT = dt.datetime(2026, 7, 24, 0, 0, tzinfo=dt.timezone.utc)


def context():
    return json.loads(Path("config/project-context.json").read_text(encoding="utf-8"))


def tuning():
    return json.loads(Path("config/quality-autotune.json").read_text(encoding="utf-8"))


def item(**overrides):
    base = {
        "uid": "item-1",
        "title": "개인정보위 AI 국외이전 지침 시행",
        "url": "https://pipc.go.kr/example",
        "source": "개인정보보호위원회",
        "published_at": "2026-07-23T00:00:00Z",
        "jurisdiction": "대한민국",
        "category": "개인정보·데이터",
        "kind": "regulatory_news",
        "summary": "AI 프롬프트 로그의 국외이전, 보유기간, 삭제와 고지 의무가 시행된다.",
        "importance": "긴급",
        "score": 82,
        "status": "공식 공표",
        "evidence": "공식 기관 원문",
        "relevance": "프롬프트·로그 처리에 직접 영향",
        "query_names": ["KR-PIPC"],
    }
    base.update(overrides)
    return base


class QualityTests(unittest.TestCase):
    def test_binding_official_change_maps_to_files_and_acceptance(self):
        action = quality.make_action(item(), run_at=RUN_AT, context=context(), tuning=tuning())
        self.assertIsNotNone(action)
        self.assertGreaterEqual(action.actionability, 58)
        self.assertIn("privacy_and_audit", action.component_ids)
        self.assertIn("src/taxia/logging/tracer.py", action.target_files)
        self.assertTrue(action.implementation_steps)
        self.assertTrue(action.acceptance_criteria)

    def test_baseline_and_self_reference_are_excluded(self):
        cfg = context()
        tune = tuning()
        baseline = item(title="공식 페이지 기준선 등록", status="공식 페이지 기준선")
        self.assertTrue(quality.item_is_excluded(baseline, cfg, tune))
        self_ref = item(
            title="LifeIsMoment/news-agent 자동 모니터링 실패",
            url="https://github.com/LifeIsMoment/news-agent/issues/1",
        )
        self.assertTrue(quality.item_is_excluded(self_ref, cfg, tune))

    def test_generic_github_taxia_homonym_is_noise(self):
        candidate = item(
            title="GitHub 저장소 example/TaxIA",
            url="https://github.com/example/TaxIA",
            source="GitHub Search API",
            category="TAXiA·CLOA",
            summary="generic tax accounting calculator",
        )
        self.assertTrue(quality.item_is_generic_github_noise(candidate, context()))
        self.assertIsNone(
            quality.make_action(candidate, run_at=RUN_AT, context=context(), tuning=tuning())
        )

    def test_xaikorea_release_maps_to_sdk_delivery(self):
        release = item(
            uid="release-1",
            title="xaikorea/taxia 릴리스 1.2.0",
            url="https://github.com/xaikorea/taxia/releases/tag/1.2.0",
            source="GitHub Releases",
            category="TAXiA·CLOA",
            kind="github_release",
            summary="SDK API package compatibility release",
            status="공식 릴리스",
            evidence="GitHub 공식 Releases API",
        )
        action = quality.make_action(release, run_at=RUN_AT, context=context(), tuning=tuning())
        self.assertIsNotNone(action)
        self.assertIn("sdk_and_delivery", action.component_ids)
        self.assertIn("pyproject.toml", action.target_files)

    def test_bounded_autotune_never_crosses_limits(self):
        tune = tuning()
        tune["min_actionability_score"] = 78
        tune["min_confidence_score"] = 82
        metrics = {
            "noise_ratio": 0.9,
            "actionable_items": 0,
            "total_items": 100,
            "official_ratio": 0.5,
            "source_failure_ratio": 0,
            "quality_score": 20,
            "generated_at": "2026-07-24T00:00:00Z",
        }
        changed, _ = quality.bounded_autotune(tune, metrics, "2026-07-24")
        self.assertEqual(changed["min_actionability_score"], 78)
        self.assertEqual(changed["min_confidence_score"], 82)

    def test_quality_metrics_measure_noise_and_coverage(self):
        cfg = context()
        tune = tuning()
        valid = item()
        noise = item(
            uid="noise",
            title="공식 페이지 기준선 등록",
            status="공식 페이지 기준선",
        )
        actions = quality.build_actions([valid, noise], run_at=RUN_AT, context=cfg, tuning=tune)
        metrics = quality.quality_metrics(
            [valid, noise],
            [{"ok": True}],
            actions,
            run_at=RUN_AT,
            context=cfg,
            tuning=tune,
        )
        self.assertEqual(metrics["baseline_items"], 1)
        self.assertGreater(metrics["component_coverage"], 0)
        self.assertGreater(metrics["noise_ratio"], 0)

    def test_report_path_selects_latest_across_tracks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "reports" / "2026" / "07"
            second = root / "reports-finance-tax-ai" / "2026" / "07"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "2026-07-23.json").write_text("{}", encoding="utf-8")
            (second / "2026-07-24.json").write_text("{}", encoding="utf-8")
            date, paths = quality.report_paths_for_date(
                [root / "reports", root / "reports-finance-tax-ai"], None
            )
            self.assertEqual(date, "2026-07-24")
            self.assertEqual(len(paths), 1)


if __name__ == "__main__":
    unittest.main()
