#!/usr/bin/env python3
"""
Fetch Advanced Roadmaps plan ranking from Jira.

Uses the non-standard /rest/jpo/1.0/backlog/compact endpoint which is not
covered by the Jira MCP or acli. Outputs plan-ranking.json: a mapping of
issue key to integer rank (1 = highest priority).

Environment:
  JIRA_SERVER       Jira base URL (default: https://redhat.atlassian.net)
  JIRA_EMAIL        Jira account email
  JIRA_API_TOKEN    Atlassian API token
  JIRA_PLAN_ID      Advanced Roadmaps plan ID (default: 625)
  JIRA_SCENARIO_ID  Advanced Roadmaps scenario ID (default: 623)
  PLAN_RANKING_OUTPUT  Output file path (default: data/plan-ranking.json)
"""

import json
import os
import sys

import requests
from requests.auth import HTTPBasicAuth

JIRA_SERVER = os.environ.get("JIRA_SERVER", "https://redhat.atlassian.net")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL") or os.environ.get("JIRA_USER")
JIRA_TOKEN = os.environ.get("JIRA_API_TOKEN") or os.environ.get("JIRA_TOKEN")
PLAN_ID = os.environ.get("JIRA_PLAN_ID", "625")
SCENARIO_ID = os.environ.get("JIRA_SCENARIO_ID", "623")
OUTPUT = os.environ.get("PLAN_RANKING_OUTPUT", "data/plan-ranking.json")


def fetch_plan_ranking(auth):
    url = f"{JIRA_SERVER}/rest/jpo/1.0/backlog/compact"
    params = {"planId": PLAN_ID, "scenarioId": SCENARIO_ID}
    resp = requests.get(url, params=params, auth=auth, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    # Response shape varies; look for a list of issues with lexoRank
    issues = (
        data.get("issueRanks")
        or data.get("issues")
        or data.get("data", {}).get("issues", [])
        or []
    )

    # Sort ascending by lexoRank (lower = higher priority)
    sorted_issues = sorted(issues, key=lambda x: x.get("lexoRank", "z"))

    ranking = {}
    for rank, issue in enumerate(sorted_issues, 1):
        key = issue.get("issueKey") or issue.get("key")
        if key:
            ranking[key] = rank

    return ranking


def main():
    if not JIRA_EMAIL or not JIRA_TOKEN:
        print("ERROR: JIRA_EMAIL and JIRA_API_TOKEN must be set", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching plan ranking (plan={PLAN_ID}, scenario={SCENARIO_ID}) from {JIRA_SERVER}...")
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_TOKEN)

    try:
        ranking = fetch_plan_ranking(auth)
    except requests.HTTPError as e:
        print(f"ERROR: Jira request failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Ranked {len(ranking)} issues")

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(ranking, f, indent=2)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
