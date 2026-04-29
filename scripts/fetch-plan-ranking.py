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
    # Endpoint requires POST with JSON body
    all_issues = []
    while True:
        body = {"planId": int(PLAN_ID), "scenarioId": int(SCENARIO_ID)}
        if all_issues:
            body["startAt"] = len(all_issues)
        resp = requests.post(url, json=body, auth=auth, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("issues", [])
        all_issues.extend(batch)
        if not data.get("more"):
            break

    # Each issue has a numeric issueKey and a lexoRank inside jiraValues.
    # Build full key as "RHAISTRAT-{number}" (all items in this plan are RHAISTRAT).
    ranked = []
    for issue in all_issues:
        num = issue.get("issueKey")
        jira_vals = issue.get("jiraValues", {})
        lexo = jira_vals.get("lexoRank", "z")
        excluded = jira_vals.get("excluded", False)
        if num and not excluded:
            ranked.append((lexo, f"RHAISTRAT-{num}"))

    ranked.sort(key=lambda x: x[0])
    return {key: i + 1 for i, (_, key) in enumerate(ranked)}


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
