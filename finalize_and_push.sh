#!/usr/bin/env bash
# finalize_and_push.sh — JAKAL HUS-OS Console (Ubuntu / WSL)
# Prunes redundant docs + dead code, commits, and publishes to GitHub main.
#
#   cd /mnt/d/LocalAgentHub/Enterprise-Application
#   bash finalize_and_push.sh              # prune (remove) + push
#   bash finalize_and_push.sh --archive    # move docs to docs/archive instead
#   bash finalize_and_push.sh --dry-run    # show what would happen
#   bash finalize_and_push.sh --no-push    # prune + commit only
#
# Nothing is destroyed: removed files remain in git history
# (recover with: git checkout HEAD~1 -- <path>). Remote main is tagged
# backup/pre-consolidation before publishing.
set -euo pipefail

ARCHIVE=0; DRYRUN=0; NOPUSH=0
for a in "$@"; do
  case "$a" in
    --archive) ARCHIVE=1 ;;
    --dry-run) DRYRUN=1 ;;
    --no-push) NOPUSH=1 ;;
  esac
done
run(){ if [ "$DRYRUN" = "1" ]; then echo "  [dry-run] $*"; else eval "$@"; fi; }

[ -d .git ] || { echo "ERROR: run from the repo root (.git not found)"; exit 1; }
echo "== JAKAL finalize: prune + publish =="
git remote -v | head -1
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "Branch: $BRANCH"; echo

REDUNDANT=(
  BUILD_SUMMARY.txt CONSOLIDATION_REPORT.md DEPLOYMENT_CHECKLIST.md DEPLOYMENT_INDEX.md
  DEPLOYMENT_QUICK_REFERENCE.txt DEPLOYMENT_STEPS_DETAILED.md FINAL_DEPLOYMENT_SUMMARY.txt
  FINAL_STATUS_COMPLETE.md FINAL_STATUS_REPORT.md JAKAL_V4_ARCHITECTURAL_DESIGN.md
  JAKAL_V4_BUILD_COMPLETION_REPORT.md JAKAL_V4_EXECUTIVE_SUMMARY.txt
  JAKAL_V4_IMPLEMENTATION_ROADMAP.md JAKAL_V4_RESTRUCTURE_RESEARCH.md
  PERFORMANCE_BENCHMARK_REPORT.md PHASE_2_COMPLETION_REPORT.md PHASE_6_PRODUCTION_HARDENING.md
  QUICK_START_VISUAL.md READ_ME_FIRST.md START_HERE.md
)

if [ "$ARCHIVE" = "1" ]; then
  echo "[1/6] Archiving ${#REDUNDANT[@]} redundant docs -> docs/archive/ ..."
  run "mkdir -p docs/archive"
else
  echo "[1/6] Removing ${#REDUNDANT[@]} redundant docs (recoverable from git history) ..."
fi
for f in "${REDUNDANT[@]}"; do
  [ -f "$f" ] || continue
  if [ "$ARCHIVE" = "1" ]; then
    run "git mv -f '$f' 'docs/archive/$(basename "$f")' 2>/dev/null || mv -f '$f' docs/archive/"
  else
    run "git rm -q --ignore-unmatch -- '$f' 2>/dev/null || rm -f '$f'"
  fi
  echo "    - $f"
done

echo "[2/6] Removing dead code ..."
# main_v4.py is BROKEN (imports routers.quantum_defense, which does not exist).
if [ -f backend/main_v4.py ]; then
  run "git rm -q --ignore-unmatch -- backend/main_v4.py 2>/dev/null || rm -f backend/main_v4.py"
  echo "    - backend/main_v4.py  (broken: imports non-existent routers.quantum_defense)"
fi
if [ -d backend-v3 ]; then
  run "git rm -r -q --ignore-unmatch -- backend-v3 2>/dev/null || rm -rf backend-v3"
  echo "    - backend-v3/  (abandoned parallel backend)"
fi

echo "[3/6] Updating .gitignore for local artifacts ..."
for i in "venv/" "data/" "logs/" "backups/" "DockerDesktopWSL/" "Claude outputs/" "*.duckdb" "__pycache__/" ".pytest_cache/"; do
  grep -qF "$i" .gitignore 2>/dev/null || run "printf '%s\n' '$i' >> .gitignore"
done
for p in venv data logs backups DockerDesktopWSL "Claude outputs"; do
  [ -e "$p" ] && run "git rm -r -q --cached --ignore-unmatch -- '$p' >/dev/null 2>&1 || true"
done

echo "[4/6] Committing ..."
run "git add -A"
if [ "$DRYRUN" != "1" ]; then
git commit -F - <<'MSG' || echo "    (nothing new to commit)"
chore: prune redundant docs + dead code; publish consolidated JAKAL build

- Remove 20 superseded status/deployment docs (kept: README, RUN_LOCALLY,
  PRODUCTION_DEPLOYMENT_GUIDE, KUBERNETES_DEPLOYMENT_AND_CLAUDE_GUIDE,
  docs/JAKAL_STATUS_REPORT.html).
- Remove backend/main_v4.py (broken: imports non-existent
  routers.quantum_defense) and the abandoned backend-v3/ tree.
- Ignore local artifacts (venv, data, logs, backups, Claude outputs).

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
fi

if [ "$NOPUSH" = "1" ] || [ "$DRYRUN" = "1" ]; then
  echo; echo "== Local prune complete. Skipped push. =="; exit 0
fi

echo "[5/6] Publishing $BRANCH -> origin/main ..."
git fetch origin 2>/dev/null || true
git tag -f backup/pre-consolidation origin/main 2>/dev/null || true
git push origin backup/pre-consolidation --force 2>/dev/null || true
echo "    old main saved as tag backup/pre-consolidation"
if ! git push origin "$BRANCH:main" 2>/dev/null; then
  echo "    fast-forward rejected (histories diverged) — using --force-with-lease"
  git push --force-with-lease origin "$BRANCH:main"
fi
echo "    pushed to origin/main"
git push origin "$BRANCH:$BRANCH" --force-with-lease >/dev/null 2>&1 || true

echo "[6/6] Pruning stale remote branches ..."
for b in master claude/track-a-containment-hardening claude/enterprise-app-security-review-xialot; do
  git push origin --delete "$b" 2>/dev/null && echo "    deleted origin/$b" || true
done
for b in v3.0-ontology-maya-enterprise; do
  if git fetch origin "$b" 2>/dev/null; then
    git tag -f "archive/$b" "origin/$b" 2>/dev/null || true
    git push origin "archive/$b" --force 2>/dev/null || true
    git push origin --delete "$b" 2>/dev/null && echo "    archived + deleted origin/$b" || true
  fi
done

echo
echo "== Done =="
echo "Verify: https://github.com/thepeoplesrealty100-ops/Enterprise-Application"
echo "Recover any pruned file with: git checkout HEAD~1 -- <path>"
