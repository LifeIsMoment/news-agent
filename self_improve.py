#!/usr/bin/env python3
"""Create allowlisted collector-quality fixes from measured failure modes.

The script patches only known exact code shapes and adds regression tests. It never
changes workflow permissions, secrets, external destinations, or target-project
source. The caller must run the full test suite before opening or merging a PR.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


GLOBAL_FILTER_MARKER = "AUTO-QUALITY: strict-global-brand-filter-v1"
REGULATORY_FILTER_MARKER = "AUTO-QUALITY: regulatory-misc-filter-v1"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def patch_global_filter(source: str) -> tuple[str, bool]:
    if GLOBAL_FILTER_MARKER in source:
        return source, False
    old = '''            combined = f"{title} {summary} {url}"
            if not brand_relevant(combined, url, brand_cfg):
                continue
'''
    new = '''            combined = f"{title} {summary} {url}"
            # AUTO-QUALITY: strict-global-brand-filter-v1
            # Generic TaxIA/CLOA homonyms are common. Global GitHub discovery must
            # contain a high-precision TAXiA/XAIKOREA signal before it is reported.
            precise_global_signal = any(
                token in combined.lower()
                for token in (
                    "xaikorea", "taxia-core", "xaikorea0", "korean tax",
                    "한국 세법", "graph-rag", "xaikorea.github.io/taxia",
                )
            )
            if not precise_global_signal:
                continue
            if "lifeismoment/news-agent" in combined.lower():
                continue
            if not brand_relevant(combined, url, brand_cfg):
                continue
'''
    if old not in source:
        raise RuntimeError("fetch_github_global code shape not found; refusing unsafe patch")
    return source.replace(old, new, 1), True


def patch_regulatory_filter(source: str) -> tuple[str, bool]:
    if REGULATORY_FILTER_MARKER in source:
        return source, False
    old = '''        category = "TAXiA·CLOA" if is_brand else classify_category(combined)
        score, importance = calculate_importance(
'''
    new = '''        category = "TAXiA·CLOA" if is_brand else classify_category(combined)
        # AUTO-QUALITY: regulatory-misc-filter-v1
        # Search-engine sidebars can match the query even when the actual document
        # has no tax, legal, data, security, labour, financial or AI relevance.
        if kind == "regulatory_news" and category == "기타" and not is_brand:
            continue
        score, importance = calculate_importance(
'''
    if old not in source:
        raise RuntimeError("fetch_google_news code shape not found; refusing unsafe patch")
    return source.replace(old, new, 1), True


def regression_test_content() -> str:
    return '''import datetime as dt
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
'''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate guarded collector-quality patches")
    parser.add_argument("--quality-file", required=True)
    parser.add_argument("--monitor", default="monitor.py")
    parser.add_argument("--test-file", default="tests/test_collector_quality.py")
    parser.add_argument("--work-dir", default="out-quality")
    args = parser.parse_args(argv)

    metrics_payload = load_json(Path(args.quality_file), {})
    metrics = metrics_payload.get("metrics", {})
    source_path = Path(args.monitor)
    source = source_path.read_text(encoding="utf-8")
    changes: list[str] = []

    if int(metrics.get("generic_github_noise_items", 0)) > 0:
        source, changed = patch_global_filter(source)
        if changed:
            changes.append("strict-global-brand-filter-v1")

    if int(metrics.get("misc_items", 0)) > 3:
        source, changed = patch_regulatory_filter(source)
        if changed:
            changes.append("regulatory-misc-filter-v1")

    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    metadata = {
        "candidate": bool(changes),
        "changes": changes,
        "allowlisted_files": [args.monitor, args.test_file],
        "auto_merge_eligible": bool(changes),
    }
    (work / "candidate.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not changes:
        print(json.dumps(metadata, ensure_ascii=False))
        return 0

    source_path.write_text(source, encoding="utf-8")
    test_path = Path(args.test_file)
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(regression_test_content(), encoding="utf-8")
    body = [
        "# Guarded automatic quality improvement",
        "",
        "Measured report noise triggered the following allowlisted fixes:",
        "",
    ]
    body.extend([f"- `{change}`" for change in changes])
    body.extend([
        "",
        "Safety constraints:",
        "",
        f"- Changed files are limited to `{args.monitor}` and `{args.test_file}`.",
        "- The full unit test suite and Python compilation must pass before merge.",
        "- No workflow permissions, secrets, destinations or target-project code are changed.",
        "",
    ])
    (work / "candidate_pr_body.md").write_text("\n".join(body), encoding="utf-8")
    (work / "candidate_pr_title.txt").write_text("fix: reduce monitoring false positives\n", encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
