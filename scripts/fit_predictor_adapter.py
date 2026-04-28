#!/usr/bin/env python3
"""
Fit Predictor Adapter — feature sizing and release capacity analysis.

All scoring logic is self-contained. Optionally loads improved constants
from lib/release_fit_predictor/ (private submodule) if present; otherwise
uses hardcoded defaults derived from 41 historical releases.
"""

import json
import os

_SUBMODULE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib", "release_fit_predictor")

_SIZE_TO_ABBREV = {"Small": "S", "Medium": "M", "Large": "L", "Extra Large": "XL"}
_ABBREV_TO_SIZE = {v: k for k, v in _SIZE_TO_ABBREV.items()}
_SIZE_POINTS = {"Small": 3, "Medium": 5, "Large": 8, "Extra Large": 13}

_DEFAULT_CAPACITY_MODEL = {
    "confidence_level": "90%",
    "releases_analyzed": 41,
    "min_points": 5.0,
    "max_points": 140.0,
    "mean_points": 38.74,
    "median_points": 27.5,
    "std_dev": 32.07,
    "recommended_range": "5 - 140 points",
}

_HIGH_VALUE_KEYWORDS = [
    "architecture", "platform", "integration", "multi-system",
    "cross-cutting", "infrastructure", "distributed", "scalability",
    "enterprise", "api",
]
_MEDIUM_VALUE_KEYWORDS = [
    "dependencies", "migration", "refactoring", "coordination",
    "phases", "rollout", "compatibility", "observability",
    "multi-phase", "multi-tenant",
]


def load_capacity_model():
    model_path = os.path.join(_SUBMODULE_DIR, "release_capacity_model.json")
    try:
        with open(model_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return _DEFAULT_CAPACITY_MODEL.copy()


def load_sizing_guide():
    guide_path = os.path.join(_SUBMODULE_DIR, "feature_sizing_guide.json")
    try:
        with open(guide_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"Feature_Size_Scale": {"Small": 3, "Medium": 5, "Large": 8, "Extra Large": 13}}


def capacity_model_to_legacy_format(model):
    median = model.get("median_points", 27.5)
    mean = model.get("mean_points", 38.74)
    max_pts = model.get("max_points", 140.0)
    std_dev = model.get("std_dev", 32.07)
    return {
        "median": median,
        "mean": round(mean, 1),
        "conservative_max": round(median + 0.1 * std_dev, 0),
        "typical_max": round(mean + 0.35 * std_dev, 0),
        "aggressive_max": round(mean + 1.3 * std_dev, 0),
        "historical_max_release": max_pts,
    }


def calculate_complexity_score(component_count=0, child_issue_count=0,
                               description_length=0, description_text=""):
    """Score feature complexity on a 0-12 scale."""
    # Component count (0-4)
    comp_score = 0.0 if component_count == 0 else (1.0 if component_count == 1 else 4.0)

    # Child issue count (0-4.5, logarithmic)
    child_map = {0: 0.0, 1: 1.0, 2: 2.0, 3: 2.5, 4: 3.0}
    if child_issue_count in child_map:
        child_score = child_map[child_issue_count]
    elif child_issue_count <= 6:
        child_score = 3.5
    elif child_issue_count <= 9:
        child_score = 4.0
    else:
        child_score = 4.5

    # Description length (0-1.5)
    if description_length < 500:
        desc_score = 0.5
    elif description_length < 1000:
        desc_score = 0.8
    elif description_length < 2000:
        desc_score = 1.0
    else:
        desc_score = 1.5

    # Complexity keywords (0-3)
    text_lower = (description_text or "").lower()
    keyword_score = min(
        sum(0.5 for kw in _HIGH_VALUE_KEYWORDS if kw in text_lower)
        + sum(0.3 for kw in _MEDIUM_VALUE_KEYWORDS if kw in text_lower),
        3.0,
    )

    return min(comp_score + child_score + desc_score + keyword_score, 12.0)


def score_to_size(score, component_count=0):
    if score < 2.0:
        size = "Small"
    elif score < 4.5:
        size = "Medium"
    elif score < 7.0:
        size = "Large"
    else:
        size = "Extra Large"
    if component_count >= 2 and size in ("Small", "Medium"):
        size = "Large"
    return size


def calculate_confidence(score, component_count=0, child_issue_count=0,
                         description_length=0, status=""):
    confidence = 5.0
    confidence += 1.0 if component_count > 0 else -1.0
    confidence += 1.0 if child_issue_count > 0 else -1.0
    if description_length > 1000:
        confidence += 0.5
    elif description_length < 500:
        confidence -= 0.5

    status_lower = (status or "").lower()
    if status_lower in ("new", "to do"):
        confidence -= 0.5
    elif status_lower == "refined":
        confidence += 0.5

    thresholds = [2.0, 4.5, 7.0]
    near_boundary = any(abs(score - t) < 0.5 for t in thresholds)
    far_from_boundary = all(abs(score - t) >= 1.0 for t in thresholds)
    if near_boundary:
        confidence -= 1.0
    elif far_from_boundary:
        confidence += 0.5

    confidence = max(0.0, min(confidence, 10.0))
    label = (
        "Low" if confidence < 2.0
        else "Low-Medium" if confidence < 3.5
        else "Medium" if confidence < 5.0
        else "Medium-High" if confidence < 6.5
        else "High"
    )
    return confidence, label


def estimate_feature_size_enhanced(summary, priority, component_count=0,
                                   child_issue_count=0, description="", status=""):
    """
    Size a feature using complexity scoring when metadata is available,
    falling back to keyword heuristics otherwise.

    Returns dict with: points, size, method, complexity_score, confidence,
    confidence_score.
    """
    description_text = description or ""
    description_length = len(description_text)
    has_jira_data = component_count > 0 or child_issue_count > 0 or description_length > 100

    if has_jira_data:
        full_text = summary + " " + description_text
        score = calculate_complexity_score(
            component_count=component_count,
            child_issue_count=child_issue_count,
            description_length=description_length,
            description_text=full_text,
        )
        size_full = score_to_size(score, component_count)
        conf_score, conf_label = calculate_confidence(
            score, component_count, child_issue_count, description_length, status
        )
        return {
            "points": _SIZE_POINTS[size_full],
            "size": _SIZE_TO_ABBREV[size_full],
            "method": "complexity_scoring",
            "complexity_score": round(score, 1),
            "confidence": conf_label,
            "confidence_score": round(conf_score, 1),
        }

    # Keyword heuristic fallback
    sl = summary.lower()
    xl_kw = ["infrastructure", "migration", "integration", "architecture", "redesign", "framework"]
    l_kw = ["implement", "develop", "create", "build", "support", "enable"]
    s_kw = ["fix", "adjust", "minor", "small", "ui", "ux", "docs"]

    if any(kw in sl for kw in xl_kw) or priority == "Blocker":
        points, size = 13, "XL"
    elif any(kw in sl for kw in l_kw) or priority == "Critical":
        points, size = 8, "L"
    elif any(kw in sl for kw in s_kw):
        points, size = 3, "S"
    else:
        points, size = 5, "M"

    return {
        "points": points,
        "size": size,
        "method": "keyword_heuristic",
        "complexity_score": None,
        "confidence": None,
        "confidence_score": None,
    }


def check_release_fit(total_points, capacity_model=None):
    if capacity_model is None:
        capacity_model = load_capacity_model()

    median = capacity_model.get("median_points", 27.5)
    mean = capacity_model.get("mean_points", 38.74)
    max_pts = capacity_model.get("max_points", 140.0)
    std_dev = capacity_model.get("std_dev", 32.07)
    pct = (total_points / median * 100) if median > 0 else 0
    typical_max = mean + 0.35 * std_dev

    if total_points <= median * 0.4:
        level, color = "EASILY_FITS", "#28a745"
        message = f"Well within capacity ({pct:.0f}% of median)"
    elif total_points <= median * 0.8:
        level, color = "FITS_WELL", "#28a745"
        message = f"Comfortable fit ({pct:.0f}% of median)"
    elif total_points <= median * 1.5:
        level, color = "FITS", "#ffc107"
        message = f"Fits within normal range ({pct:.0f}% of median)"
    elif total_points <= max_pts:
        level, color = "TIGHT_FIT", "#fd7e14"
        message = f"Tight fit - near upper limit ({pct:.0f}% of median)"
    else:
        level, color = "EXCEEDS_CAPACITY", "#dc3545"
        message = f"Exceeds historical maximum ({pct:.0f}% of median)"

    return {
        "level": level,
        "color": color,
        "pct_of_median": round(pct, 1),
        "remaining_to_typical": round(typical_max - total_points, 1),
        "message": message,
    }
