#!/usr/bin/env python3
"""
Merge feature-traffic-data, supplemental fields, and plan ranking into a
single features-ready.json consumed by auto_scheduler.py and the
/release-plan skill.

Only features for TARGET_PRODUCT are included in the output.

Environment:
  FEATURE_INDEX     Path to feature-traffic index.json
  FEATURE_DIR       Path to feature-traffic features/ directory
  SUPPLEMENTAL      Path to supplemental.json (from fetch-supplemental.py)
  PLAN_RANKING      Path to plan-ranking.json (from fetch-plan-ranking.py)
  FEATURES_OUTPUT   Output path (default: data/features-ready.json)
  TARGET_PRODUCT    Product to include (default: RHOAI)
"""

import json
import os
import sys

# Allow importing from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fit_predictor_adapter import (
    capacity_model_to_legacy_format,
    estimate_feature_size_enhanced,
    load_capacity_model,
)

FEATURE_INDEX = os.environ.get("FEATURE_INDEX", "data/feature-traffic/RHAISTRAT/latest/index.json")
FEATURE_DIR = os.environ.get("FEATURE_DIR", "data/feature-traffic/RHAISTRAT/latest/features")
SUPPLEMENTAL = os.environ.get("SUPPLEMENTAL", "data/supplemental.json")
PLAN_RANKING = os.environ.get("PLAN_RANKING", "data/plan-ranking.json")
OUTPUT = os.environ.get("FEATURES_OUTPUT", "data/features-ready.json")
TARGET_PRODUCT = os.environ.get("TARGET_PRODUCT", "RHOAI")

KNOWN_PRODUCTS = {"RHOAI", "RHAIIS", "RHELAI"}


def infer_product(feat_summary, detail, supp):
    """Derive product using a tiered lookup hierarchy."""
    # 1. Products array field from supplemental
    for p in supp.get("products", []):
        if p and p.upper() in KNOWN_PRODUCTS:
            return p.upper()

    # 2. Product single-select field
    ps = supp.get("productSingle")
    if ps and ps.upper() in KNOWN_PRODUCTS:
        return ps.upper()

    # 3. fixVersions / targetVersions prefix
    versions = feat_summary.get("fixVersions", []) + feat_summary.get("targetVersions", [])
    versions += detail.get("fixVersions", []) + detail.get("targetVersions", [])
    for v in versions:
        for p in KNOWN_PRODUCTS:
            if v.startswith(p):
                return p

    # 4. Labels
    labels = {lb.upper() for lb in feat_summary.get("labels", detail.get("labels", []))}
    for p in KNOWN_PRODUCTS:
        if p in labels:
            return p

    return "RHOAI"


def main():
    with open(FEATURE_INDEX) as f:
        index = json.load(f)
    with open(SUPPLEMENTAL) as f:
        supplemental = json.load(f)
    with open(PLAN_RANKING) as f:
        plan_ranking = json.load(f)

    capacity_model = load_capacity_model()
    capacity = capacity_model_to_legacy_format(capacity_model)

    features_ready = []
    skipped = 0

    for feat_summary in index["features"]:
        key = feat_summary["key"]
        supp = supplemental.get(key, {})

        detail_path = os.path.join(FEATURE_DIR, f"{key}.json")
        detail = {}
        if os.path.exists(detail_path):
            with open(detail_path) as f:
                detail = json.load(f)

        product = infer_product(feat_summary, detail, supp)
        if product != TARGET_PRODUCT:
            skipped += 1
            continue

        # Story points / auto-sizing
        story_points = supp.get("storyPoints", 0)
        if story_points > 0:
            size_result = {"points": story_points, "size": None, "method": "jira_provided",
                           "complexity_score": None, "confidence": None, "confidence_score": None}
        else:
            epics = detail.get("epics", [])
            child_issue_count = sum(len(e.get("issues", [])) for e in epics) + len(epics)
            size_result = estimate_feature_size_enhanced(
                summary=feat_summary.get("summary", ""),
                priority=feat_summary.get("priority", "Major"),
                component_count=len(detail.get("components", [])),
                child_issue_count=child_issue_count,
                description=supp.get("description", ""),
                status=feat_summary.get("status", ""),
            )

        # Scheduling status
        fix_versions = feat_summary.get("fixVersions") or detail.get("fixVersions", [])
        target_versions = feat_summary.get("targetVersions") or detail.get("targetVersions", [])

        if fix_versions:
            scheduled_to = fix_versions[0]
            schedule_category = "committed"
        elif target_versions:
            scheduled_to = target_versions[0]
            schedule_category = "planned"
        else:
            scheduled_to = None
            schedule_category = "unscheduled"

        # Blocked-by: inward "Blocks" links that are not yet closed
        blocked_by = [
            link["linkedKey"]
            for link in detail.get("issueLinks", [])
            if link.get("type") == "Blocks"
            and link.get("direction") == "inward"
            and link.get("linkedStatus") not in ("Closed", "Done", "Resolved")
        ]

        rank = plan_ranking.get(key, 9999)

        features_ready.append({
            "key": key,
            "summary": feat_summary["summary"],
            "status": feat_summary["status"],
            "statusCategory": feat_summary["statusCategory"],
            "priority": feat_summary["priority"],
            "product": product,
            "points": size_result["points"],
            "size": size_result.get("size"),
            "sizeMethod": size_result["method"],
            "complexityScore": size_result.get("complexity_score"),
            "sizingConfidence": size_result.get("confidence"),
            "fixVersions": fix_versions,
            "targetVersions": target_versions,
            "scheduledTo": scheduled_to,
            "scheduleCategory": schedule_category,
            "releaseType": feat_summary.get("releaseType"),
            "rank": rank,
            "inPlan": rank < 9999,
            "targetEndDate": supp.get("targetEndDate"),
            "blockedBy": blocked_by,
            "labels": feat_summary.get("labels", []),
            "components": detail.get("components", []),
            "epicCount": len(detail.get("epics", [])),
            "health": feat_summary.get("health"),
            "assignee": feat_summary.get("assignee"),
        })

    output_data = {
        "product": TARGET_PRODUCT,
        "fetchedAt": index["fetchedAt"],
        "featureCount": len(features_ready),
        "capacity": capacity,
        "features": features_ready,
    }

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(output_data, f, indent=2)

    committed = sum(1 for f in features_ready if f["scheduleCategory"] == "committed")
    planned = sum(1 for f in features_ready if f["scheduleCategory"] == "planned")
    unscheduled = sum(1 for f in features_ready if f["scheduleCategory"] == "unscheduled")
    jira_sized = sum(1 for f in features_ready if f["sizeMethod"] == "jira_provided")
    blocked = sum(1 for f in features_ready if f["blockedBy"])

    print(f"Target product: {TARGET_PRODUCT}")
    print(f"Features: {len(features_ready)} included, {skipped} skipped (other products)")
    print(f"  Committed: {committed}  Planned: {planned}  Unscheduled: {unscheduled}")
    print(f"  Jira story points: {jira_sized}  Auto-sized: {len(features_ready) - jira_sized}")
    print(f"  Blocked: {blocked}")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
