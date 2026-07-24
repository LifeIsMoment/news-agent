#!/usr/bin/env python3
"""Run the quality optimizer with monotonic and core-domain safety guards."""
from __future__ import annotations

import sys
from typing import Any

import finance_monitor_entry as core_policy
import finance_monitor_quality as quality

MIN_POLICY_VERSION = 3
_ORIGINAL_PROPOSE_CONFIG = quality.propose_config
_ORIGINAL_IS_CORE = quality.is_core
_ORIGINAL_IS_NOISE = quality.is_noise


def is_weak_paper(item: dict[str, Any]) -> bool:
    if item.get("source_type") != "paper_primary":
        return False
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    return not any(term.lower() in text for term in core_policy.PAPER_DOMAIN_TERMS)


def guarded_is_core(item: dict[str, Any]) -> bool:
    return _ORIGINAL_IS_CORE(item) and not is_weak_paper(item)


def guarded_is_noise(item: dict[str, Any]) -> bool:
    return _ORIGINAL_IS_NOISE(item) or is_weak_paper(item)


def guarded_propose_config(config: dict[str, Any], policy: dict[str, Any], metrics: Any,
                           latest_items: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    proposed, changes = _ORIGINAL_PROPOSE_CONFIG(config, policy, metrics, latest_items)
    current = int(config.get("priority_policy_version", 0))
    target = max(current, MIN_POLICY_VERSION)

    filtered = [change for change in changes if not change.startswith("priority_policy_version:")]
    proposed["priority_policy_version"] = target
    if target != current:
        filtered.append(f"priority_policy_version: {current!r} → {target!r}")
    return proposed, filtered


def install_guards() -> None:
    quality.is_core = guarded_is_core
    quality.is_noise = guarded_is_noise
    quality.propose_config = guarded_propose_config


def main() -> int:
    install_guards()
    return quality.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
