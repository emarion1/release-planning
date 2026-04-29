#!/usr/bin/env python3
"""
Build the feature-to-big-rock mapping from the feature-traffic index.

The feature-traffic index already contains a parentKey field for each
feature, which points to its parent Outcome issue in Jira. This script
maps those parent keys to big rock definitions using big-rocks.json,
removing the need for a live Jira API call.

For big rocks with no outcomeKeys defined (TBD), no features are returned
here; prepare-features.py falls back to label matching for those rocks.

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
  FEATURE_INDEX      Path to feature-traffic index.json
                     (default: data/feature-traffic/latest/index.json)
  BIG_ROCKS          Path to big-rocks.json (default: data/big-rocks.json)
  BIG_ROCK_OUTPUT    Output file path (default: data/big-rock-features.json)
"""

import json
import os
import sys

FEATURE_INDEX = os.environ.get("FEATURE_INDEX", "data/feature-traffic/latest/index.json")
BIG_ROCKS     = os.environ.get("BIG_ROCKS",     "data/big-rocks.json")
OUTPUT        = os.environ.get("BIG_ROCK_OUTPUT", "data/big-rock-features.json")


def main():
    with open(BIG_ROCKS) as f:
        big_rocks_data = json.load(f)

    with open(FEATURE_INDEX) as f:
        index = json.load(f)

    rocks = big_rocks_data.get("bigRocks", [])

    # Build outcomeKey -> rock mapping
    outcome_to_rock = {}
    for rock in rocks:
        for key in rock.get("outcomeKeys", []):
            outcome_to_rock[key] = rock

    rocks_without = [r for r in rocks if not r.get("outcomeKeys")]
    if rocks_without:
        print("Big rocks with no outcome keys (label fallback will apply):")
        for r in rocks_without:
            print(f"  [{r['priority']}] {r['name']}")

    if not outcome_to_rock:
        print("No outcome keys defined — writing empty output")
        os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
        with open(OUTPUT, "w") as f:
            json.dump({}, f, indent=2)
        return

    # Walk the index: any feature whose parentKey matches an outcome key
    result = {}
    for feat in index.get("features", []):
        parent_key = feat.get("parentKey", "")
        if not parent_key or parent_key not in outcome_to_rock:
            continue
        rock = outcome_to_rock[parent_key]
        result[feat["key"]] = {
            "bigRock":          rock["name"],
            "bigRockPriority":  rock["priority"],
            "bigRockTier":      rock["tier"],
            "bigRockTierScore": rock["tierScore"],
            "outcomeKey":       parent_key,
        }

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(result, f, indent=2)

    by_rock = {}
    for v in result.values():
        by_rock.setdefault(v["bigRock"], 0)
        by_rock[v["bigRock"]] += 1

    print(f"\nMapped {len(result)} features to big rocks via parentKey:")
    for rock_name, count in sorted(by_rock.items(), key=lambda x: -x[1]):
        print(f"  {rock_name}: {count}")
    print(f"\nWrote {OUTPUT}")


if __name__ == "__main__":
    main()
