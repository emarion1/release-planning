#!/usr/bin/env python3
"""
Push release plan output to release-planning-data repo.

Creates a timestamped directory under RHOAI/ and updates RHOAI/latest/.

Environment:
  RESULTS_PUSH_TOKEN          GitLab token with write access to data repo
  RELEASE_PLANNING_DATA_REPO  GitLab path (default: redhat/rhel-ai/agentic-ci/release-planning-data)
  TARGET_PRODUCT              Product subdirectory (default: RHOAI)
  OUTPUT_DIR                  Source directory (default: output)
  CI_PROJECT_DIR              Set by GitLab CI
"""

import os
import subprocess
import sys
from datetime import datetime, timezone

RESULTS_PUSH_TOKEN = os.environ.get("RESULTS_PUSH_TOKEN")
DATA_REPO = os.environ.get(
    "RELEASE_PLANNING_DATA_REPO",
    "redhat/rhel-ai/agentic-ci/release-planning-data",
)
TARGET_PRODUCT = os.environ.get("TARGET_PRODUCT", "RHOAI")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")


def run(cmd, **kwargs):
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def main():
    if not RESULTS_PUSH_TOKEN:
        print("ERROR: RESULTS_PUSH_TOKEN must be set", file=sys.stderr)
        sys.exit(1)

    output_files = [
        os.path.join(OUTPUT_DIR, "release-plan.md"),
        os.path.join(OUTPUT_DIR, "release-plan.json"),
    ]
    missing = [f for f in output_files if not os.path.exists(f)]
    if missing:
        print(f"ERROR: Missing output files: {missing}", file=sys.stderr)
        sys.exit(1)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    clone_url = f"https://oauth2:{RESULTS_PUSH_TOKEN}@gitlab.com/{DATA_REPO}.git"

    run(["git", "clone", "--depth", "1", clone_url, "release-planning-data"])

    target_dir = os.path.join("release-planning-data", TARGET_PRODUCT, timestamp)
    latest_dir = os.path.join("release-planning-data", TARGET_PRODUCT, "latest")

    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(latest_dir, exist_ok=True)

    import shutil
    for src in output_files:
        shutil.copy(src, target_dir)
        shutil.copy(src, latest_dir)

    os.chdir("release-planning-data")
    run(["git", "add", "-A"])

    result = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if result.returncode == 0:
        print("No changes to commit.")
        return

    run([
        "git", "-c", "user.name=CI", "-c", "user.email=ci@redhat.com",
        "commit", "-m", f"Release plan {TARGET_PRODUCT} {timestamp}",
    ])
    run(["git", "push"])
    print(f"Published to {DATA_REPO}/{TARGET_PRODUCT}/{timestamp}")


if __name__ == "__main__":
    main()
