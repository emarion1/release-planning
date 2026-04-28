#!/usr/bin/env python3
"""
Auto-scheduler for Red Hat AI Products Release Planning.
Distributes features across release events based on priority and capacity.
Product-aware: features are scheduled into their own product release buckets.
"""

import json
import sys

KNOWN_PRODUCTS = ["RHOAI", "RHAIIS", "RHELAI"]


def generate_release_schedule(start_version="3.5", num_releases=8):
    major, minor = map(int, start_version.split("."))
    schedule = []
    for i in range(num_releases):
        version = f"{major}.{minor + i}"
        schedule.append({"version": version, "events": ["EA1", "EA2", "GA"]})
    return schedule


def auto_schedule_features(features, capacity_guidelines, start_version="3.5", num_releases=8):
    """
    Distribute features across release events respecting capacity.

    RHOAI features use plain keys ("3.5-EA1"), other products are prefixed
    ("RHAIIS:3.5-EA1"). Features are sorted by in-plan status, target end
    date, then Jira plan rank.

    Returns (plan dict, schedule list).
    """
    schedule = generate_release_schedule(start_version, num_releases)

    def sort_key(f):
        in_plan = f.get("inPlan", f.get("in_plan", False))
        # Higher priorityScore = higher priority; negate so larger scores sort first
        priority_score = -(f.get("priorityScore", 0))
        target_date = f.get("targetEndDate", f.get("target_end_date")) or "9999-12-31"
        rank = f.get("rank", 9999)
        return (not in_plan, priority_score, target_date, rank)

    sorted_features = sorted(features, key=sort_key)

    target_capacity = capacity_guidelines.get("typical_max", 50)
    max_capacity = capacity_guidelines.get("aggressive_max", 80)

    features_by_product = {}
    for f in sorted_features:
        product = f.get("product", "RHOAI")
        features_by_product.setdefault(product, []).append(f)

    def make_bucket_key(product, version, event):
        return f"{version}-{event}" if product == "RHOAI" else f"{product}:{version}-{event}"

    plan = {}
    product_bucket_keys = {}
    for product in features_by_product:
        keys = []
        for release in schedule:
            for event in release["events"]:
                bk = make_bucket_key(product, release["version"], event)
                keys.append(bk)
                plan[bk] = {"features": [], "points": 0, "capacity_status": "conservative"}
        product_bucket_keys[product] = keys

    for product, prod_features in features_by_product.items():
        bucket_keys = product_bucket_keys[product]
        current_bucket_idx = 0

        for feature in prod_features:
            points = feature.get("points", 0)
            if points == 0:
                continue

            placed = False
            attempts = 0
            while not placed and attempts < len(bucket_keys):
                bk = bucket_keys[current_bucket_idx % len(bucket_keys)]
                bucket = plan[bk]

                if bucket["points"] + points <= max_capacity:
                    bucket["features"].append(feature)
                    bucket["points"] += points
                    if bucket["points"] <= capacity_guidelines.get("conservative_max", 30):
                        bucket["capacity_status"] = "conservative"
                    elif bucket["points"] <= target_capacity:
                        bucket["capacity_status"] = "typical"
                    elif bucket["points"] <= max_capacity:
                        bucket["capacity_status"] = "aggressive"
                    else:
                        bucket["capacity_status"] = "over_capacity"
                    placed = True
                    if bucket["points"] >= target_capacity:
                        current_bucket_idx += 1
                else:
                    current_bucket_idx += 1
                    attempts += 1

    plan = {k: v for k, v in plan.items() if v["features"]}
    return plan, schedule


def format_plan_summary(plan, schedule):
    summary = []
    products_in_plan = set()
    for bk in plan:
        products_in_plan.add(bk.split(":")[0] if ":" in bk else "RHOAI")

    for product in sorted(products_in_plan):
        for release in schedule:
            version = release["version"]
            header_printed = False
            release_total = 0
            release_features = 0

            for event in release["events"]:
                bk = f"{version}-{event}" if product == "RHOAI" else f"{product}:{version}-{event}"
                if bk not in plan:
                    continue

                if not header_printed:
                    summary.append(f"\n{'='*60}")
                    summary.append(f"{product}-{version}")
                    summary.append(f"{'='*60}")
                    header_printed = True

                bucket = plan[bk]
                count = len(bucket["features"])
                pts = bucket["points"]
                status = bucket["capacity_status"]
                release_total += pts
                release_features += count

                icon = {"conservative": "[OK]", "typical": "[~]", "aggressive": "[!!]", "over_capacity": "[OVER]"}.get(status, "")
                summary.append(f"\n  {event}: {count} features, {pts} pts {icon} ({status})")
                for feat in bucket["features"][:3]:
                    rank_str = f"#{feat['rank']}" if feat.get("inPlan", feat.get("in_plan")) else "-"
                    summary.append(f"    {rank_str} {feat['key']} - {feat['summary'][:55]} ({feat['points']} pts)")
                if count > 3:
                    summary.append(f"    ... and {count - 3} more")

            if header_printed:
                summary.append(f"\n  TOTAL: {release_features} features, {release_total} pts")

    return "\n".join(summary)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Auto-schedule features into release events")
    parser.add_argument("--input", required=True, help="Path to features-ready.json")
    parser.add_argument("--output", required=True, help="Path to write schedule.json")
    parser.add_argument("--start-version", default="3.5")
    parser.add_argument("--num-releases", type=int, default=8)
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    features = data["features"]
    capacity = data["capacity"]

    plan, schedule = auto_schedule_features(
        features,
        capacity,
        start_version=args.start_version,
        num_releases=args.num_releases,
    )

    scheduled_keys = {feat["key"] for bucket in plan.values() for feat in bucket["features"]}
    unscheduled = [f for f in features if f["key"] not in scheduled_keys]

    output = {
        "product": data.get("product", "RHOAI"),
        "generatedAt": data.get("fetchedAt"),
        "startVersion": args.start_version,
        "numReleases": args.num_releases,
        "schedule": schedule,
        "plan": plan,
        "unscheduled": unscheduled,
        "capacity": capacity,
    }

    import os
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(format_plan_summary(plan, schedule))
    print(f"\nUnscheduled: {len(unscheduled)} features")
    print(f"Wrote {args.output}")
