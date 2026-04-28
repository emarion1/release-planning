#!/usr/bin/env python3
"""
Fetch supplemental Jira fields not yet present in feature-traffic-data.

TEMPORARY — remove this script and its CI step once feature-traffic is
extended to include: storyPoints, products, productSingle, targetEndDate,
and description. See feature-traffic-changes.md for the required changes.

Reads feature keys from the feature-traffic-data index, then fetches the
missing fields in batches of 50 via JQL.

Environment:
  JIRA_SERVER          Jira base URL (default: https://redhat.atlassian.net)
  JIRA_EMAIL           Jira account email
  JIRA_API_TOKEN       Atlassian API token
  FEATURE_INDEX        Path to feature-traffic index.json
  SUPPLEMENTAL_OUTPUT  Output file path (default: data/supplemental.json)
"""

import json
import os
import sys

import requests
from requests.auth import HTTPBasicAuth

JIRA_SERVER = os.environ.get("JIRA_SERVER", "https://redhat.atlassian.net")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL") or os.environ.get("JIRA_USER")
JIRA_TOKEN = os.environ.get("JIRA_API_TOKEN") or os.environ.get("JIRA_TOKEN")
FEATURE_INDEX = os.environ.get("FEATURE_INDEX", "data/feature-traffic/RHAISTRAT/latest/index.json")
OUTPUT = os.environ.get("SUPPLEMENTAL_OUTPUT", "data/supplemental.json")
BATCH_SIZE = 50

FIELDS = ",".join([
    "customfield_10836",  # Story Points
    "customfield_10868",  # Products (array)
    "customfield_10608",  # Product (single select)
    "customfield_10015",  # Target End Date
    "description",
])


def adf_to_text(adf):
    """Extract plain text from Atlassian Document Format."""
    if not adf or not isinstance(adf, dict):
        return ""
    texts = []

    def extract(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                texts.append(node.get("text", ""))
            for child in node.get("content", []):
                extract(child)
        elif isinstance(node, list):
            for item in node:
                extract(item)

    extract(adf)
    return " ".join(texts)


def fetch_batch(keys, auth):
    jql = f"issueKey in ({','.join(keys)})"
    url = f"{JIRA_SERVER}/rest/api/3/search/jql"
    resp = requests.get(
        url,
        params={"jql": jql, "fields": FIELDS, "maxResults": BATCH_SIZE},
        auth=auth,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json().get("issues", [])


def main():
    if not JIRA_EMAIL or not JIRA_TOKEN:
        print("ERROR: JIRA_EMAIL and JIRA_API_TOKEN must be set", file=sys.stderr)
        sys.exit(1)

    with open(FEATURE_INDEX) as f:
        index = json.load(f)

    keys = [feat["key"] for feat in index["features"]]
    print(f"Fetching supplemental fields for {len(keys)} features...")

    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_TOKEN)
    result = {}

    for i in range(0, len(keys), BATCH_SIZE):
        batch = keys[i : i + BATCH_SIZE]
        try:
            issues = fetch_batch(batch, auth)
        except requests.HTTPError as e:
            print(f"ERROR on batch {i//BATCH_SIZE + 1}: {e}", file=sys.stderr)
            sys.exit(1)

        for issue in issues:
            key = issue["key"]
            fields = issue["fields"]

            story_points = fields.get("customfield_10836") or 0

            products_raw = fields.get("customfield_10868") or []
            products = [
                p.get("value") or p.get("name")
                for p in products_raw
                if isinstance(p, dict)
            ]

            product_single = None
            cf_10608 = fields.get("customfield_10608")
            if isinstance(cf_10608, dict):
                product_single = cf_10608.get("value")

            target_end_date = fields.get("customfield_10015")
            description = adf_to_text(fields.get("description"))

            result[key] = {
                "storyPoints": int(story_points) if story_points else 0,
                "products": products,
                "productSingle": product_single,
                "targetEndDate": target_end_date,
                "description": description,
            }

        done = min(i + BATCH_SIZE, len(keys))
        print(f"  {done}/{len(keys)}")

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Wrote {OUTPUT} ({len(result)} features)")


if __name__ == "__main__":
    main()
