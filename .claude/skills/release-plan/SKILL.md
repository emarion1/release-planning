---
name: release-plan
description: |
  Generate a 2-year RHOAI release plan from pre-fetched Jira feature data.

  Use when:
  - "Generate the release plan" or "produce the roadmap"
  - "What features are scheduled for RHOAI 3.x?"
  - "Show me capacity analysis for the next 8 releases"
  - "Which features are blocked, not ready, or unscheduled?"

  NOT for: writing back to Jira, creating Jira issues, or fetching live data
  (data is pre-fetched by the CI pipeline before this skill runs).

model: inherit
color: blue
---

# Release Plan

Generate a 2-year RHOAI release roadmap with capacity analysis and risk
commentary from pre-fetched and pre-processed feature data.

## Prerequisites

Verify these files exist before proceeding. If any are missing, report
the missing file and stop — do not attempt to fetch data directly.

- data/features-ready.json — sized, scored, and ranked RHOAI features
- data/schedule.json — auto-generated release schedule

## Key Field Reference

Each feature in features-ready.json includes:

  priorityScore (0-100)     — composite score: RICE 30%, big rock 30%,
                              priority 25%, inverse complexity 15%
  priorityScoreBreakdown    — per-factor contribution in points
  isReady (bool)            — true if label strat-creator-rubric-pass present
                              (strategy reviewed and approved by Eder's rubric)
  bigRock / bigRockTier     — associated big rock name and tier (1/2/3)
  scheduleCategory          — committed / planned / unscheduled
  sizeMethod                — jira_provided or auto_estimated
  blockedBy                 — list of blocking issue keys

## Workflow

### Step 1: Read Input Data

Read data/features-ready.json. Extract: featureCount, capacity thresholds,
and the full features list.

Read data/schedule.json. Extract: schedule, plan buckets, and unscheduled list.

Output: "Read [N] features ([R] ready to plan) and a schedule covering [start] to [end]."

### Step 2: Capacity Analysis

For each bucket in plan, note capacity_status:
  conservative  (<=conservative_max)  — Low risk
  typical       (<=typical_max)       — Normal
  aggressive    (<=aggressive_max)    — High risk
  over_capacity (>aggressive_max)     — Critical

Count buckets at each level. Identify the highest-risk events.

### Step 3: Risk Identification

**Not-ready features in plan**: features where isReady=false but scheduled.
  These should be refined before commitment. List key, summary, scheduleCategory.

**Blocked features**: features where blockedBy is non-empty.
  Check if the blocker is scheduled before the blocked feature.
  Flag scheduling conflicts explicitly.

**Oversized features**: features with points == 13 (XL).
  Candidates for splitting. Note sizingConfidence.

**Auto-sized features**: sizeMethod != "jira_provided".
  High auto-sizing rates reduce plan reliability — note the percentage.

**Unscheduled features by big rock**: from schedule.json unscheduled list,
  group by bigRock and show bigRockTier. Tier-1 big rock features that are
  unscheduled are highest priority to address.

### Step 4: Write output/release-plan.md

Write a Markdown report with these required sections:

  # RHOAI Release Plan -- [YYYY-MM-DD]
  ## Executive Summary
  ## Big Rock Coverage  (table: Priority | Big Rock | Tier | Scheduled Features | Ready)
  ## 2-Year Roadmap     (table: Release | Event | Features | Points | Status)
  ## Capacity Analysis
  ## Risk Flags
  ### Features Not Ready to Plan (isReady=false but scheduled)
  ### Blocked Features
  ### Oversized Features (XL -- Candidates for Splitting)
  ### Unscheduled Features (by Big Rock tier)
  ## Sizing Confidence
  ## Recommendations  (3-5 actionable bullets, priority-score-driven)

### Step 5: Write output/release-plan.json

Write structured JSON:

  {
    "generatedAt": "<ISO timestamp>",
    "product": "RHOAI",
    "dataFetchedAt": "<from features-ready.json>",
    "summary": { totalFeatures, scheduledFeatures, unscheduledFeatures,
                 readyFeatures, notReadyInPlan, blockedFeatures,
                 xlFeatures, autoSizedFeatures, releasesPlanned },
    "capacity": { ... },
    "releases": [
      { "version": "3.5",
        "events": {
          "EA1": { "features": [...], "points": 0, "capacityStatus": "typical" },
          "EA2": { ... },
          "GA":  { ... }
        }
      }
    ],
    "unscheduled": [...],
    "risks": {
      "notReadyInPlan": [],
      "blockedFeatures": [],
      "xlFeatures": [],
      "overCapacityEvents": []
    }
  }

Each feature entry: key, summary, points, sizeMethod, priorityScore,
  bigRock, bigRockTier, isReady, scheduleCategory, scheduledTo, blockedBy.

### Step 6: Confirm Completion

Output:
  Release plan complete.
    Releases: [N] (EA1/EA2/GA each)
    Features scheduled: [N] / unscheduled: [N]
    Ready to plan: [N] / not ready: [N]
    Capacity risks: [N] events at aggressive or over_capacity
    Blocked features: [N]
    Output: output/release-plan.md, output/release-plan.json

## Dependencies

- data/features-ready.json -- produced by scripts/prepare-features.py
- data/schedule.json       -- produced by scripts/auto_scheduler.py
- No MCP tools required; all data is local

## Example Usage

  /release-plan
