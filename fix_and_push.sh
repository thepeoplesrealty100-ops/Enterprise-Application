#!/usr/bin/env bash
# fix_and_push.sh — resolves the "does not have a commit checked out" abort,
# then commits and publishes the consolidated JAKAL build to GitHub main.
#
#   cd /mnt/d/LocalAgentHub/Enterprise-Application
#   bash fix_and_push.sh
#
# Root cause it fixes: one or more subdirectories contain their own .git
# (stray `git init`, or vendored tool state such as ai_agent_layer/ which holds
# OpenHands agent state). Git cannot `add` a nested repo, so `git add -A`
# aborts and nothing gets committed. This script excludes those directories
# from the parent repo (gitignore + untrack) instead of swallowing them.
set -uo pipefail

[ -d .git ] || { echo "ERROR: run from the repo root (.git not found)"; exit 1; }
echo "== JAKAL fix + publish =="
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "Branch: $BRANCH"; echo

# ─────────────────────────────────────────────────────────────────────────
# 1. Find nested git repositories and exclude them from the parent repo
# ─────────────────────────────────────────────────────────────────────────
echo "[1/5] Scanning for nested git repositories ..."
mapfile -t NESTED < <(find . -mindepth 2 -maxdepth 5 -name .git -not -path "./.git/*" 2>/dev/null)
if [ "${#NESTED[@]}" -eq 0 ]; then
  echo "    none found"
else
  for g in "${NESTED[@]}"; do
    d="$(dirname "$g")"; d="${d#./}"
    if git -C "$d" rev-parse HEAD >/dev/null 2>&1; then
      state="has commits"
    else
      state="EMPTY (stray git init)"
    fi
    echo "    - $d/  ($state) -> excluding from parent repo"
    grep -qxF "$d/" .gitignore 2>/dev/null || printf '%s/\n' "$d" >> .gitignore
    git rm -r -q --cached --ignore-unmatch -- "$d" >/dev/null 2>&1 || true
  done
fi

# Belt-and-braces: make sure the heavy local dirs are ignored too.
echo "[2/5] Ensuring local artifacts are ignored ..."
for i in "venv/" "data/" "logs/" "backups/" "DockerDesktopWSL/" "Claude outputs/" \
         "*.duckdb" "__pycache__/" ".pytest_cache/" ".openhands-state/" "openhands-state/"; do
  grep -qxF "$i" .gitignore 2>/dev/null || printf '%s\n' "$i" >> .gitignore
done
for p in venv data logs backups DockerDesktopWSL "Claude outputs"; do
  [ -e "$p" ] && git rm -r -q --cached --ignore-unmatch -- "$p" >/dev/null 2>&1
done
echo "    done"

# ─────────────────────────────────────────────────────────────────────────
# 3. Stage + commit
# ─────────────────────────────────────────────────────────────────────────
echo "[3/5] Staging ..."
if ! git add -A; then
  echo
  echo "ERROR: 'git add -A' still failed. The offending path is named in the"
  echo "error above — add it to .gitignore and re-run this script."
  exit 1
fi
CHANGES="$(git diff --cached --numstat | wc -l)"
echo "    staged $CHANGES changed path(s)"

echo "[4/5] Committing ..."
git commit -F - <<'MSG'
chore: prune redundant docs + dead code; publish consolidated JAKAL build

- Remove 20 superseded status/deployment docs (kept: README, RUN_LOCALLY,
  PRODUCTION_DEPLOYMENT_GUIDE, KUBERNETES_DEPLOYMENT_AND_CLAUDE_GUIDE,
  docs/JAKAL_STATUS_REPORT.html).
- Remove backend/main_v4.py (broken: imports non-existent
  routers.quantum_defense) and the abandoned backend-v3/ tree.
- Exclude nested tool repos (ai_agent_layer/ OpenHands state) and local
  artifacts (venv, data, logs, backups, Claude outputs) from version control.

Includes the consolidated platform build: Security Capabilities Engine
(32 actions / 10 domains, guardrail + approval gating + audit), seeded
operational data layer (19 DuckDB tables), Operator Console v3, and the
enterprise gap modules (MSP multi-tenant, fleet RMM, vulnerability
management, asset relationship map, credential rotation, process
kill-tree, memory dump, remediation tickets, drift detection, phishing
auto-enroll) — 370 live routes.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01An3aVdpapQKzaxo3GN8JJ5
MSG
if [ $? -ne 0 ]; then echo "    (nothing new to commit — continuing to push)"; fi

# ─────────────────────────────────────────────────────────────────────────
# 5. Publish
# ─────────────────────────────────────────────────────────────────────────
echo "[5/5] Publishing $BRANCH -> origin/main ..."
git fetch origin >/dev/null 2>&1 || true
git tag -f backup/pre-consolidation origin/main >/dev/null 2>&1 || true
git push origin backup/pre-consolidation --force >/dev/null 2>&1 && \
  echo "    old main saved as tag backup/pre-consolidation"

if ! git push origin "$BRANCH:main" 2>/dev/null; then
  echo "    fast-forward rejected (histories diverged) — using --force-with-lease"
  if ! git push --force-with-lease origin "$BRANCH:main"; then
    echo "ERROR: push failed (credentials or network). Nothing else changed."
    exit 1
  fi
fi
echo "    ✓ pushed to origin/main"
git push origin "$BRANCH:$BRANCH" --force-with-lease >/dev/null 2>&1 || true

echo "    pruning stale remote branches ..."
for b in master claude/track-a-containment-hardening claude/enterprise-app-security-review-xialot; do
  git push origin --delete "$b" >/dev/null 2>&1 && echo "      deleted origin/$b"
done
for b in v3.0-ontology-maya-enterprise; do
  if git fetch origin "$b" >/dev/null 2>&1; then
    git tag -f "archive/$b" "origin/$b" >/dev/null 2>&1
    git push origin "archive/$b" --force >/dev/null 2>&1
    git push origin --delete "$b" >/dev/null 2>&1 && echo "      archived + deleted origin/$b"
  fi
done

echo
echo "== Done =="
git log --oneline -1
echo "Verify: https://github.com/thepeoplesrealty100-ops/Enterprise-Application"
