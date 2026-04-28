#!/usr/bin/env python3
"""
Fetch per-feature rubric dimension scores from strat-pipeline-data.

Scans all pipeline run directories in the GitLab repo, building a map of
the latest score for each feature key. Later runs win on conflict.

Output: data/rubric-scores.json — dict keyed by feature key:
  {
    "RHAISTRAT-1047": {
      "run": "20260428-183832",
      "feasibility": 2,
      "testability": 2,
      "scope": 2,
      "architecture": 2,
      "total": 8,
      "recommendation": "approve"
    },
    ...
  }

Environment:
  GITLAB_TOKEN           GitLab personal access token
  RUBRIC_PROJECT_ID      GitLab project ID (default: 81219071)
  RUBRIC_PROJECT_KEY     Jira project prefix to include (default: RHAISTRAT)
  RUBRIC_REF             Git ref to read from (default: main)
  RUBRIC_OUTPUT          Output file path (default: data/rubric-scores.json)
"""

import json
import os
import sys
import urllib.request
import urllib.error

GITLAB_TOKEN     = os.environ.get("GITLAB_TOKEN", "")
PROJECT_ID       = os.environ.get("RUBRIC_PROJECT_ID", "81219071")
PROJECT_KEY      = os.environ.get("RUBRIC_PROJECT_KEY", "RHAISTRAT")
REF              = os.environ.get("RUBRIC_REF", "main")
OUTPUT           = os.environ.get("RUBRIC_OUTPUT", "data/rubric-scores.json")

GITLAB_API = "https://gitlab.com/api/v4"


def gitlab_get(path):
    url = f"{GITLAB_API}/{path}"
    req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": GITLAB_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"ERROR {e.code} fetching {url}", file=sys.stderr)
        return None


def list_run_dirs():
    """Return sorted list of run directory names under PROJECT_KEY/."""
    page = 1
    dirs = []
    while True:
        items = gitlab_get(
            f"projects/{PROJECT_ID}/repository/tree"
            f"?path={PROJECT_KEY}&ref={REF}&per_page=100&page={page}"
        )
        if not items:
            break
        trees = [i["name"] for i in items if i["type"] == "tree"]
        dirs.extend(trees)
        if len(items) < 100:
            break
        page += 1
    return sorted(dirs)


def fetch_pipeline_data(run_dir):
    """Fetch and return strategies list from a run's pipeline-data.json, or []."""
    path = f"{PROJECT_KEY}/{run_dir}/pipeline-data.json"
    encoded = path.replace("/", "%2F")
    data = gitlab_get(
        f"projects/{PROJECT_ID}/repository/files/{encoded}/raw?ref={REF}"
    )
    if data is None or not isinstance(data, dict):
        return []
    return data.get("strategies", [])


def main():
    if not GITLAB_TOKEN:
        print("ERROR: GITLAB_TOKEN must be set", file=sys.stderr)
        sys.exit(1)

    run_dirs = list_run_dirs()
    print(f"Found {len(run_dirs)} pipeline runs in {PROJECT_KEY}")

    scores = {}  # feature key -> score dict; later runs overwrite earlier ones

    for run_dir in run_dirs:
        strategies = fetch_pipeline_data(run_dir)
        for s in strategies:
            key = s.get("strat_id", "")
            if not key:
                continue
            raw_scores = s.get("scores", {})
            scores[key] = {
                "run":            run_dir,
                "feasibility":    raw_scores.get("feasibility"),
                "testability":    raw_scores.get("testability"),
                "scope":          raw_scores.get("scope"),
                "architecture":   raw_scores.get("architecture"),
                "total":          raw_scores.get("total"),
                "recommendation": s.get("recommendation"),
            }

        print(f"  {run_dir}: {len(strategies)} features (cumulative: {len(scores)})")

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(scores, f, indent=2)

    passing = sum(1 for v in scores.values() if v["recommendation"] == "approve")
    print(f"\nWrote {OUTPUT}")
    print(f"  {len(scores)} unique features scored")
    print(f"  {passing} passing (approve), {len(scores) - passing} needs-attention/reject")


if __name__ == "__main__":
    main()
