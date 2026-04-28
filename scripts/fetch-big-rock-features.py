#!/usr/bin/env python3
"""
Fetch the feature-to-big-rock mapping via Jira parent/child hierarchy.

For each big rock that has outcomeKeys defined, queries Jira for all
Feature-type children using JQL: issueType = Feature AND parent in (...)

For big rocks with no outcomeKeys (TBD), no features are returned via
hierarchy; prepare-features.py will fall back to label-based matching
for those rocks.

Output: data/big-rock-features.json — dict keyed by feature issue key:
  {
    "RHAISTRAT-1431": {
      "bigRock": "MaaS",
      "bigRockPriority": 1,
      "bigRockTier": 1,
      "bigRockTierScore": 1.0,
      "outcomeKey": "RHAISTRAT-1513"
    },
    ...
  }

Environment:
  JIRA_SERVER          Jira base URL (default: https://redhat.atlassian.net)
  JIRA_EMAIL           Jira account email
  JIRA_API_TOKEN       Atlassian API token
  BIG_ROCKS            Path to big-rocks.json (default: data/big-rocks.json)
  BIG_ROCK_OUTPUT      Output file path (default: data/big-rock-features.json)
"""

import json
import os
import sys

import requests
from requests.auth import HTTPBasicAuth

JIRA_SERVER = os.environ.get("JIRA_SERVER", "https://redhat.atlassian.net")
JIRA_EMAIL  = os.environ.get("JIRA_EMAIL") or os.environ.get("JIRA_USER")
JIRA_TOKEN  = os.environ.get("JIRA_API_TOKEN") or os.environ.get("JIRA_TOKEN")
BIG_ROCKS   = os.environ.get("BIG_ROCKS", "data/big-rocks.json")
OUTPUT      = os.environ.get("BIG_ROCK_OUTPUT", "data/big-rock-features.json")

BATCH_SIZE  = 100


def search_jql(jql, fields, auth, max_results=1000):
    """Return all issues matching JQL, paginating automatically."""
    url = f"{JIRA_SERVER}/rest/api/3/search/jql"
    issues = []
    start = 0
    while True:
        resp = requests.get(
            url,
            params={"jql": jql, "fields": fields, "maxResults": BATCH_SIZE, "startAt": start},
            auth=auth,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("issues", [])
        issues.extend(batch)
        if len(batch) < BATCH_SIZE or len(issues) >= max_results:
            break
        start += len(batch)
    return issues


def main():
    if not JIRA_EMAIL or not JIRA_TOKEN:
        print("ERROR: JIRA_EMAIL and JIRA_API_TOKEN must be set", file=sys.stderr)
        sys.exit(1)

    with open(BIG_ROCKS) as f:
        big_rocks_data = json.load(f)

    rocks = big_rocks_data.get("bigRocks", [])
    auth  = HTTPBasicAuth(JIRA_EMAIL, JIRA_TOKEN)

    # Build outcomeKey -> rock mapping (one key may map to one rock)
    outcome_to_rock = {}
    for rock in rocks:
        for key in rock.get("outcomeKeys", []):
            outcome_to_rock[key] = rock

    rocks_with_outcomes = [r for r in rocks if r.get("outcomeKeys")]
    rocks_without = [r for r in rocks if not r.get("outcomeKeys")]

    if rocks_without:
        print(f"Big rocks with no outcome keys (label fallback will apply):")
        for r in rocks_without:
            print(f"  [{r['priority']}] {r['name']}")

    if not outcome_to_rock:
        print("No outcome keys defined — writing empty output")
        os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
        with open(OUTPUT, "w") as f:
            json.dump({}, f, indent=2)
        return

    all_outcome_keys = list(outcome_to_rock.keys())
    print(f"\nQuerying Jira for children of {len(all_outcome_keys)} outcome issues...")

    keys_clause = ", ".join(all_outcome_keys)
    jql = f"issueType = Feature AND parent in ({keys_clause})"

    try:
        issues = search_jql(jql, fields="summary,status,parent", auth=auth)
    except requests.HTTPError as e:
        print(f"ERROR fetching features: {e}", file=sys.stderr)
        sys.exit(1)

    result = {}
    for issue in issues:
        feat_key   = issue["key"]
        parent_key = issue["fields"].get("parent", {}).get("key")
        if not parent_key or parent_key not in outcome_to_rock:
            continue
        rock = outcome_to_rock[parent_key]
        result[feat_key] = {
            "bigRock":          rock["name"],
            "bigRockPriority":  rock["priority"],
            "bigRockTier":      rock["tier"],
            "bigRockTierScore": rock["tierScore"],
            "outcomeKey":       parent_key,
        }

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nFound {len(issues)} features across {len(all_outcome_keys)} outcome issues")
    by_rock = {}
    for v in result.values():
        by_rock.setdefault(v["bigRock"], 0)
        by_rock[v["bigRock"]] += 1
    for rock_name, count in sorted(by_rock.items(), key=lambda x: -x[1]):
        print(f"  {rock_name}: {count} features")
    print(f"\nWrote {OUTPUT}")


if __name__ == "__main__":
    main()
