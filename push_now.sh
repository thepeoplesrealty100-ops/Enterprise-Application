#!/usr/bin/env bash
# push_now.sh — publish the consolidated JAKAL build to GitHub main.
#
#   bash push_now.sh <your-github-token>
#
# Takes the token as an argument so you never paste a long URL (which your
# terminal was wrapping and corrupting). The script builds the URL itself.
# It also repairs the malformed remote left by the earlier attempts.
set -uo pipefail

T="${1:-}"
if [ -z "$T" ]; then
  echo "usage:  bash push_now.sh <github-token>"
  echo "example: bash push_now.sh ghp_xxxxxxxxxxxx"
  exit 1
fi

OWNER="thepeoplesrealty100-ops"
REPO="Enterprise-Application"
CLEAN="https://github.com/${OWNER}/${REPO}.git"
AUTH="https://${OWNER}:${T}@github.com/${OWNER}/${REPO}.git"

[ -d .git ] || { echo "ERROR: run from the repo root (.git not found)"; exit 1; }

echo "== JAKAL publish =="
# 1. Repair the remote (earlier pastes left it malformed / token-embedded)
git remote set-url origin "$CLEAN"
echo "remote  : $(git remote get-url origin)"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "branch  : $BRANCH"
echo "commits : $(git rev-list --count HEAD) total"
echo

# 2. Sanity-check the token before doing anything destructive
echo "[1/4] Verifying credentials ..."
if ! git ls-remote "$AUTH" >/dev/null 2>&1; then
  echo "  ✗ GitHub rejected this token."
  echo "    - is it still valid (not revoked)?"
  echo "    - does it have the 'repo' scope?"
  echo "    - classic tokens start ghp_ ; fine-grained start github_pat_"
  echo "  Nothing was changed."
  exit 1
fi
echo "  ✓ token accepted"

# 3. Back up whatever main currently is, so nothing is ever lost
echo "[2/4] Backing up current origin/main ..."
git fetch "$AUTH" main >/dev/null 2>&1 || true
if git rev-parse FETCH_HEAD >/dev/null 2>&1; then
  git tag -f backup/pre-consolidation FETCH_HEAD >/dev/null 2>&1
  git push "$AUTH" backup/pre-consolidation --force >/dev/null 2>&1 \
    && echo "  ✓ old main saved as tag backup/pre-consolidation"
else
  echo "  (no existing main to back up)"
fi

# 4. Publish
echo "[3/4] Publishing $BRANCH -> main ..."
if git push "$AUTH" "$BRANCH:main" --force; then
  echo "  ✓ pushed to main"
else
  echo "  ✗ push failed — nothing else changed."; exit 1
fi
git push "$AUTH" "$BRANCH:$BRANCH" --force >/dev/null 2>&1 \
  && echo "  ✓ $BRANCH synced"

# 5. Prune stale branches
echo "[4/4] Pruning stale remote branches ..."
for b in master claude/track-a-containment-hardening claude/enterprise-app-security-review-xialot; do
  git push "$AUTH" --delete "$b" >/dev/null 2>&1 && echo "  deleted origin/$b"
done
if git fetch "$AUTH" v3.0-ontology-maya-enterprise >/dev/null 2>&1; then
  git tag -f archive/v3.0-ontology-maya-enterprise FETCH_HEAD >/dev/null 2>&1
  git push "$AUTH" archive/v3.0-ontology-maya-enterprise --force >/dev/null 2>&1
  git push "$AUTH" --delete v3.0-ontology-maya-enterprise >/dev/null 2>&1 \
    && echo "  archived + deleted origin/v3.0-ontology-maya-enterprise"
fi

# 6. Remember the token for next time (stored in your home dir, NOT the repo,
#    so it is never committed or pushed).
git config --global credential.helper store
printf 'https://%s:%s@github.com\n' "$OWNER" "$T" > "$HOME/.git-credentials"
chmod 600 "$HOME/.git-credentials"

echo
echo "== Done =="
git log --oneline -1
echo "Verify: https://github.com/${OWNER}/${REPO}"
echo "(future pushes: just 'git push' — credentials saved to ~/.git-credentials)"
