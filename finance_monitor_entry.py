#!/usr/bin/env python3
"""Apply deterministic relevance guards, then run the finance monitor.

The guard is intentionally explicit and idempotent. It prevents two false-positive
patterns observed during the first baseline run and compensates for the collector's
legacy baseline-release boundary without rewriting historical reports.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("config/finance_sources.json")


def apply_operational_guards(config: dict[str, Any]) -> dict[str, Any]:
    news = {row["name"]: row for row in config.get("news_queries", [])}
    if "KR-BOK-ECOS-API" not in news:
        raise KeyError("KR-BOK-ECOS-API query is missing")
    bok = news["KR-BOK-ECOS-API"]
    bok["required_all_groups"] = [
        ["ECOS", "API"],
        ["변경", "개편", "점검", "추가", "버전", "서비스", "개발"],
    ]
    bok["title_required_any"] = ["ECOS", "API"]
    bok["exclude_any"] = sorted(set(bok.get("exclude_any", [])) | {"채용", "모집", "입찰"})

    arxiv = {row["name"]: row for row in config.get("arxiv_queries", [])}
    if "ARXIV-AUDIT-AI" not in arxiv:
        raise KeyError("ARXIV-AUDIT-AI query is missing")
    arxiv["ARXIV-AUDIT-AI"]["required_all_groups"] = [
        ["감사", "audit", "assurance", "internal control", "fraud", "SOX"],
        ["large language model", "LLM", "agent", "artificial intelligence"],
        [
            "accounting", "financial statement", "financial reporting",
            "assurance", "internal control", "external audit", "회계", "재무제표",
        ],
    ]

    for asset in config.get("github_repositories", []):
        # Current collector includes indices 0..baseline_releases. -1 means none;
        # 0 means exactly the latest release for the directly tracked TAXiA repo.
        asset["baseline_releases"] = 0 if asset.get("repo", "").lower() == "xaikorea/taxia" else -1
    return config


def tune_config(path: Path = CONFIG_PATH) -> None:
    original = path.read_text(encoding="utf-8")
    config = json.loads(original)
    tuned = apply_operational_guards(config)
    rendered = json.dumps(tuned, ensure_ascii=False, indent=2) + "\n"
    if original != rendered:
        path.write_text(rendered, encoding="utf-8")
        print("Applied finance monitor relevance guards.")
    else:
        print("Finance monitor relevance guards already applied.")


def main() -> int:
    tune_config()
    import finance_monitor
    return finance_monitor.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
