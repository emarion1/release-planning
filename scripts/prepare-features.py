#!/usr/bin/env python3
"""
Merge feature-traffic-data, supplemental fields, plan ranking, and big rocks
into a single features-ready.json consumed by auto_scheduler.py and the
/release-plan skill.

Priority scoring (0-100) uses the 4-factor model from org-pulse:
  RICE score         30%  (median fallback 0.5 until field data available)
  Big rock tier      30%  (1.0 / 0.6 / 0.2 / 0.0 matched via Jira labels)
  Feature priority   25%  (Blocker→Critical→Major→Normal→Minor)
  Inverse complexity 15%  (XS→S→M→L→XL)

Readiness gate: features with label 'strat-creator-rubric-pass' are ready
to be planned. Others are flagged but still included so Claude can report
on the refinement backlog.

Only features for TARGET_PRODUCT are included in the output.

Environment:
  FEATURE_INDEX     Path to feature-traffic index.json
  FEATURE_DIR       Path to feature-traffic features/ directory
  SUPPLEMENTAL      Path to supplemental.json (from fetch-supplemental.py)
  PLAN_RANKING      Path to plan-ranking.json (from fetch-plan-ranking.py)
  BIG_ROCKS         Path to big-rocks.json (default: data/big-rocks.json)
  FEATURES_OUTPUT   Output path (default: data/features-ready.json)
  TARGET_PRODUCT    Product to include (default: RHOAI)
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fit_predictor_adapter import (
    capacity_model_to_legacy_format,
    estimate_feature_size_enhanced,
    load_capacity_model,
)

FEATURE_INDEX = os.environ.get("FEATURE_INDEX", "data/feature-traffic/RHAISTRAT/latest/index.json")
FEATURE_DIR   = os.environ.get("FEATURE_DIR",   "data/feature-traffic/RHAISTRAT/latest/features")
SUPPLEMENTAL  = os.environ.get("SUPPLEMENTAL",  "data/supplemental.json")
PLAN_RANKING  = os.environ.get("PLAN_RANKING",  "data/plan-ranking.json")
BIG_ROCKS          = os.environ.get("BIG_ROCKS",          "data/big-rocks.json")
BIG_ROCK_FEATURES  = os.environ.get("BIG_ROCK_FEATURES",  "data/big-rock-features.json")
RUBRIC_SCORES      = os.environ.get("RUBRIC_SCORES",      "data/rubric-scores.json")
OUTPUT             = os.environ.get("FEATURES_OUTPUT",    "data/features-ready.json")
TARGET_PRODUCT     = os.environ.get("TARGET_PRODUCT",     "RHOAI")

KNOWN_PRODUCTS = {"RHOAI", "RHAIIS", "RHELAI"}

READINESS_LABEL = "strat-creator-rubric-pass"

PRIORITY_SCORES = {
    "Blocker":  1.0,
    "Critical": 0.8,
    "Major":    0.6,
    "Normal":   0.4,
    "Minor":    0.2,
}

SIZE_SCORES = {
    "Extra Large": 0.2,
    "Large":       0.4,
    "Medium":      0.6,
    "Small":       0.8,
}

WEIGHTS = {"rice": 0.30, "bigRock": 0.30, "priority": 0.25, "complexity": 0.15}


def load_big_rocks(path):
    """Return (label_to_big_rock dict, ordered list of big rock dicts)."""
    if not os.path.exists(path):
        print(f"WARNING: big-rocks file not found at {path}, big rock scoring disabled")
        return {}, []
    with open(path) as f:
        data = json.load(f)
    rocks = data.get("bigRocks", [])
    label_map = {}
    for rock in rocks:
        for label in rock.get("labels", []):
            label_lower = label.lower()
            if label_lower not in label_map:
                label_map[label_lower] = rock
    return label_map, rocks


def match_big_rock(labels, label_map):
    """Return the highest-priority big rock matching any feature label, or None."""
    best = None
    for label in labels:
        rock = label_map.get(label.lower())
        if rock and (best is None or rock["priority"] < best["priority"]):
            best = rock
    return best


def compute_priority_score(priority, size, big_rock):
    """Return composite 0-100 priority score and its breakdown."""
    rice_score    = 0.5  # median fallback until RICE fields are available
    big_rock_score = big_rock["tierScore"] if big_rock else 0.0
    priority_score = PRIORITY_SCORES.get(priority, 0.4)
    complexity_score = SIZE_SCORES.get(size, 0.5)

    raw = (
        rice_score      * WEIGHTS["rice"] +
        big_rock_score  * WEIGHTS["bigRock"] +
        priority_score  * WEIGHTS["priority"] +
        complexity_score * WEIGHTS["complexity"]
    )
    score = round(raw * 100, 1)
    breakdown = {
        "rice":       round(rice_score * WEIGHTS["rice"] * 100, 1),
        "bigRock":    round(big_rock_score * WEIGHTS["bigRock"] * 100, 1),
        "priority":   round(priority_score * WEIGHTS["priority"] * 100, 1),
        "complexity": round(complexity_score * WEIGHTS["complexity"] * 100, 1),
    }
    return score, breakdown


def infer_product(feat_summary, detail, supp):
    """Derive product using a tiered lookup hierarchy."""
    for p in supp.get("products", []):
        if p and p.upper() in KNOWN_PRODUCTS:
            return p.upper()

    ps = supp.get("productSingle")
    if ps and ps.upper() in KNOWN_PRODUCTS:
        return ps.upper()

    versions = (feat_summary.get("fixVersions", []) + feat_summary.get("targetVersions", [])
                + detail.get("fixVersions", []) + detail.get("targetVersions", []))
    for v in versions:
        for p in KNOWN_PRODUCTS:
            if v.startswith(p):
                return p

    labels = {lb.upper() for lb in feat_summary.get("labels", detail.get("labels", []))}
    for p in KNOWN_PRODUCTS:
        if p in labels:
            return p

    return "RHOAI"


def load_big_rock_features(path):
    """Return dict of feature key -> big rock info from Jira hierarchy, or {} if missing."""
    if not os.path.exists(path):
        print(f"WARNING: big-rock-features file not found at {path}, using label fallback only")
        return {}
    with open(path) as f:
        return json.load(f)


def load_rubric_scores(path):
    """Return dict of feature key -> rubric score dict, or {} if file missing."""
    if not os.path.exists(path):
        print(f"WARNING: rubric-scores file not found at {path}, rubric scoring disabled")
        return {}
    with open(path) as f:
        return json.load(f)


def main():
    with open(FEATURE_INDEX) as f:
        index = json.load(f)
    with open(SUPPLEMENTAL) as f:
        supplemental = json.load(f)
    with open(PLAN_RANKING) as f:
        plan_ranking = json.load(f)

    label_map, _ = load_big_rocks(BIG_ROCKS)
    big_rock_features = load_big_rock_features(BIG_ROCK_FEATURES)
    rubric_scores = load_rubric_scores(RUBRIC_SCORES)

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
            size_result = {
                "points": story_points, "size": None, "method": "jira_provided",
                "complexity_score": None, "confidence": None, "confidence_score": None,
            }
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
        fix_versions    = feat_summary.get("fixVersions") or detail.get("fixVersions", [])
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

        # Blocked-by: inward "Blocks" links not yet closed
        blocked_by = [
            link["linkedKey"]
            for link in detail.get("issueLinks", [])
            if link.get("type") == "Blocks"
            and link.get("direction") == "inward"
            and link.get("linkedStatus") not in ("Closed", "Done", "Resolved")
        ]

        # Readiness gate
        labels = feat_summary.get("labels", detail.get("labels", []))
        is_ready = READINESS_LABEL in labels

        # Big rock association — hierarchy (Jira parent) takes priority over labels
        hierarchy_rock = big_rock_features.get(key)
        if hierarchy_rock:
            big_rock_name     = hierarchy_rock["bigRock"]
            big_rock_priority = hierarchy_rock["bigRockPriority"]
            big_rock_tier     = hierarchy_rock["bigRockTier"]
            big_rock_tier_score = hierarchy_rock["bigRockTierScore"]
            big_rock_source   = "hierarchy"
            big_rock = {"name": big_rock_name, "priority": big_rock_priority,
                        "tier": big_rock_tier, "tierScore": big_rock_tier_score}
        else:
            big_rock = match_big_rock(labels, label_map)
            big_rock_name     = big_rock["name"] if big_rock else None
            big_rock_priority = big_rock["priority"] if big_rock else None
            big_rock_tier     = big_rock["tier"] if big_rock else None
            big_rock_source   = "label" if big_rock else None

        # Priority score
        rank = plan_ranking.get(key, 9999)
        priority_score, score_breakdown = compute_priority_score(
            priority=feat_summary.get("priority", "Major"),
            size=size_result.get("size"),
            big_rock=big_rock,
        )

        # Rubric dimension scores
        rubric = rubric_scores.get(key, {})
        rubric_feasibility    = rubric.get("feasibility")
        rubric_testability    = rubric.get("testability")
        rubric_scope          = rubric.get("scope")
        rubric_architecture   = rubric.get("architecture")
        rubric_total          = rubric.get("total")
        rubric_recommendation = rubric.get("recommendation")

        # DoR soft warnings derived from rubric dimensions (only when rubric data exists)
        dor_warnings = []
        if rubric:
            if rubric_testability is not None and rubric_testability < 2:
                dor_warnings.append("AC may need refinement (Testability < 2)")
            if rubric_architecture is not None and rubric_architecture < 2:
                dor_warnings.append("Arch review may be incomplete (Architecture < 2)")
            if rubric_feasibility is not None and rubric_feasibility < 2:
                dor_warnings.append("Feasibility/risks need attention (Feasibility < 2)")

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
            "labels": labels,
            "components": detail.get("components", []),
            "epicCount": len(detail.get("epics", [])),
            "health": feat_summary.get("health"),
            "assignee": feat_summary.get("assignee"),
            # Readiness
            "isReady": is_ready,
            # Big rock
            "bigRock": big_rock_name,
            "bigRockPriority": big_rock_priority,
            "bigRockTier": big_rock_tier,
            "bigRockSource": big_rock_source,
            # Priority score
            "priorityScore": priority_score,
            "priorityScoreBreakdown": score_breakdown,
            # Rubric dimension scores
            "rubricScored": bool(rubric),
            "rubricFeasibility":    rubric_feasibility,
            "rubricTestability":    rubric_testability,
            "rubricScope":          rubric_scope,
            "rubricArchitecture":   rubric_architecture,
            "rubricTotal":          rubric_total,
            "rubricRecommendation": rubric_recommendation,
            "dorWarnings":          dor_warnings,
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

    committed   = sum(1 for f in features_ready if f["scheduleCategory"] == "committed")
    planned     = sum(1 for f in features_ready if f["scheduleCategory"] == "planned")
    unscheduled = sum(1 for f in features_ready if f["scheduleCategory"] == "unscheduled")
    jira_sized  = sum(1 for f in features_ready if f["sizeMethod"] == "jira_provided")
    blocked     = sum(1 for f in features_ready if f["blockedBy"])
    ready       = sum(1 for f in features_ready if f["isReady"])
    with_rock        = sum(1 for f in features_ready if f["bigRock"])
    rock_hierarchy   = sum(1 for f in features_ready if f["bigRockSource"] == "hierarchy")
    rock_label       = sum(1 for f in features_ready if f["bigRockSource"] == "label")
    rubric_scored = sum(1 for f in features_ready if f["rubricScored"])
    rubric_pass   = sum(1 for f in features_ready if f["rubricRecommendation"] == "approve")
    with_warnings = sum(1 for f in features_ready if f["dorWarnings"])

    print(f"Target product:   {TARGET_PRODUCT}")
    print(f"Features:         {len(features_ready)} included, {skipped} skipped (other products)")
    print(f"  Committed: {committed}  Planned: {planned}  Unscheduled: {unscheduled}")
    print(f"  Jira story points: {jira_sized}  Auto-sized: {len(features_ready) - jira_sized}")
    print(f"  Blocked: {blocked}")
    print(f"  Ready to plan (strat-creator-rubric-pass): {ready} / {len(features_ready)}")
    print(f"  Linked to a big rock: {with_rock} / {len(features_ready)} (hierarchy: {rock_hierarchy}, label fallback: {rock_label})")
    print(f"  Rubric scored: {rubric_scored} / {len(features_ready)}")
    print(f"    Passing (approve): {rubric_pass}  With DoR warnings: {with_warnings}")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
