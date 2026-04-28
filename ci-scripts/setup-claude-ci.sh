#!/bin/bash
# Common CI setup: create non-root user, install Claude Code, configure GCP credentials.
set -euo pipefail

microdnf install -y --nodocs git-core shadow-utils util-linux python3 python3-pip diffutils
pip3 install requests pyyaml
useradd -m claude-ci
curl -fsSL https://claude.ai/install.sh | runuser -l claude-ci -c bash
echo "$GCP_SERVICE_ACCOUNT_KEY" | base64 -d > /tmp/gcp-key.json
chmod 644 /tmp/gcp-key.json
chown -R claude-ci:claude-ci "$CI_PROJECT_DIR"
runuser -u claude-ci -- git config --global --add safe.directory "$CI_PROJECT_DIR"
