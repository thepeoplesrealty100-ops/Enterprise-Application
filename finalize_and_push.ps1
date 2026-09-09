#Requires -Version 5
<#
  finalize_and_push.ps1 — JAKAL HUS-OS Console
  Prunes redundant docs + dead code, commits everything, and publishes to
  GitHub main. Run from the repo root:

      cd D:\LocalAgentHub\Enterprise-Application
      powershell -ExecutionPolicy Bypass -File .\finalize_and_push.ps1

  Options:
      -Archive     move the redundant docs to docs\archive\ instead of removing
      -DryRun      show what WOULD happen; change nothing
      -NoPush      prune + commit locally, but do not touch GitHub

  Nothing is destroyed: removed files stay in git history and are recoverable
  with `git checkout <commit>~1 -- <file>`. The remote main is tagged
  `backup/pre-consolidation` before publishing.
#>
param(
  [switch]$Archive,
  [switch]$DryRun,
  [switch]$NoPush
)
$ErrorActionPreference = "Stop"
function Say($m, $c = "Cyan") { Write-Host $m -ForegroundColor $c }
function Do-It($desc, $block) {
  if ($DryRun) { Say "  [dry-run] $desc" DarkGray }
  else { & $block }
}

if (-not (Test-Path ".git")) { Say "ERROR: run this from the repo root (no .git here)." Red; exit 1 }
Say "== JAKAL finalize: prune + publish ==" Cyan
git remote -v | Select-Object -First 1
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
Say "Branch: $branch" DarkGray
Say ""

# ─────────────────────────────────────────────────────────────────────────
# 1. Redundant / superseded documentation (20 files)
#    Superseded by: README.md, RUN_LOCALLY.md, PRODUCTION_DEPLOYMENT_GUIDE.md,
#    KUBERNETES_DEPLOYMENT_AND_CLAUDE_GUIDE.md and docs\JAKAL_STATUS_REPORT.html
# ─────────────────────────────────────────────────────────────────────────
$redundant = @(
  "BUILD_SUMMARY.txt",
  "CONSOLIDATION_REPORT.md",
  "DEPLOYMENT_CHECKLIST.md",
  "DEPLOYMENT_INDEX.md",
  "DEPLOYMENT_QUICK_REFERENCE.txt",
  "DEPLOYMENT_STEPS_DETAILED.md",
  "FINAL_DEPLOYMENT_SUMMARY.txt",
  "FINAL_STATUS_COMPLETE.md",
  "FINAL_STATUS_REPORT.md",
  "JAKAL_V4_ARCHITECTURAL_DESIGN.md",
  "JAKAL_V4_BUILD_COMPLETION_REPORT.md",
  "JAKAL_V4_EXECUTIVE_SUMMARY.txt",
  "JAKAL_V4_IMPLEMENTATION_ROADMAP.md",
  "JAKAL_V4_RESTRUCTURE_RESEARCH.md",
  "PERFORMANCE_BENCHMARK_REPORT.md",
  "PHASE_2_COMPLETION_REPORT.md",
  "PHASE_6_PRODUCTION_HARDENING.md",
  "QUICK_START_VISUAL.md",
  "READ_ME_FIRST.md",
  "START_HERE.md"
)

if ($Archive) {
  Say "[1/6] Archiving $($redundant.Count) redundant docs -> docs\archive\ ..." Yellow
  Do-It "mkdir docs\archive" { New-Item -ItemType Directory -Force -Path "docs\archive" | Out-Null }
} else {
  Say "[1/6] Removing $($redundant.Count) redundant docs (recoverable from git history) ..." Yellow
}
$done = 0
foreach ($f in $redundant) {
  if (Test-Path $f) {
    if ($Archive) {
      Do-It "archive $f" { git mv -f -- $f (Join-Path "docs\archive" (Split-Path $f -Leaf)) 2>$null; if ($LASTEXITCODE -ne 0) { Move-Item -Force $f "docs\archive\" } }
    } else {
      Do-It "remove $f" { git rm -q --ignore-unmatch -- $f 2>$null; if (Test-Path $f) { Remove-Item -Force $f } }
    }
    $done++
    Say "    - $f" DarkGray
  }
}
Say "    ($done handled)" DarkGray

# ─────────────────────────────────────────────────────────────────────────
# 2. Dead / broken code
# ─────────────────────────────────────────────────────────────────────────
Say "[2/6] Removing dead code ..." Yellow
# main_v4.py is BROKEN: it imports routers.quantum_defense, which does not
# exist -> ModuleNotFoundError. app.py is the real entrypoint (370 routes).
if (Test-Path "backend\main_v4.py") {
  Do-It "remove backend\main_v4.py (broken duplicate entrypoint)" {
    git rm -q --ignore-unmatch -- "backend/main_v4.py" 2>$null
    if (Test-Path "backend\main_v4.py") { Remove-Item -Force "backend\main_v4.py" }
  }
  Say "    - backend\main_v4.py  (broken: imports non-existent routers.quantum_defense)" DarkGray
}
# backend-v3: abandoned parallel Postgres rewrite; the repo's own archived
# plan flagged it 'old/unused - delete'.
if (Test-Path "backend-v3") {
  Do-It "remove backend-v3\ (abandoned parallel backend)" {
    git rm -r -q --ignore-unmatch -- "backend-v3" 2>$null
    if (Test-Path "backend-v3") { Remove-Item -Recurse -Force "backend-v3" }
  }
  Say "    - backend-v3\  (abandoned parallel backend)" DarkGray
}

# ─────────────────────────────────────────────────────────────────────────
# 3. Keep local-only artifacts out of git
# ─────────────────────────────────────────────────────────────────────────
Say "[3/6] Updating .gitignore for local artifacts ..." Yellow
$ignores = @("venv/", "data/", "logs/", "backups/", "DockerDesktopWSL/", "Claude outputs/", "*.duckdb", "__pycache__/", ".pytest_cache/")
Do-It "append .gitignore entries" {
  $gi = if (Test-Path ".gitignore") { Get-Content ".gitignore" -Raw } else { "" }
  $add = @()
  foreach ($i in $ignores) { if ($gi -notmatch [regex]::Escape($i)) { $add += $i } }
  if ($add.Count) { Add-Content -Path ".gitignore" -Value ("`n# local build/run artifacts`n" + ($add -join "`n")) }
  # stop tracking anything already committed under those paths
  foreach ($p in @("venv", "data", "logs", "backups", "DockerDesktopWSL", "Claude outputs")) {
    if (Test-Path $p) { git rm -r -q --cached --ignore-unmatch -- $p 2>$null | Out-Null }
  }
}

# ─────────────────────────────────────────────────────────────────────────
# 4. Commit
# ─────────────────────────────────────────────────────────────────────────
Say "[4/6] Committing ..." Yellow
Do-It "git add -A && git commit" {
  git add -A
  $msg = @"
chore: prune redundant docs + dead code; publish consolidated JAKAL build

- Remove 20 superseded status/deployment docs (kept: README, RUN_LOCALLY,
  PRODUCTION_DEPLOYMENT_GUIDE, KUBERNETES_DEPLOYMENT_AND_CLAUDE_GUIDE,
  docs/JAKAL_STATUS_REPORT.html).
- Remove backend/main_v4.py (broken: imports non-existent
  routers.quantum_defense) and the abandoned backend-v3/ tree.
- Ignore local artifacts (venv, data, logs, backups, Claude outputs).

Includes the consolidated platform build: Security Capabilities Engine
(32 actions / 10 domains, guardrail + approval gating + audit), seeded
operational data layer (19 DuckDB tables), Operator Console v3, the
enterprise gap modules (MSP multi-tenant, fleet RMM, vulnerability
management, asset relationship map, credential rotation, process
kill-tree, memory dump, remediation tickets, drift detection, phishing
auto-enroll) — 370 live routes.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01An3aVdpapQKzaxo3GN8JJ5
"@
  git commit -m $msg 2>$null
  if ($LASTEXITCODE -ne 0) { Say "    (nothing new to commit)" DarkGray }
}

if ($NoPush -or $DryRun) {
  Say ""
  Say "== Local prune complete. Skipped push (-NoPush/-DryRun). ==" Green
  exit 0
}

# ─────────────────────────────────────────────────────────────────────────
# 5. Publish to GitHub main (old main saved as a tag first)
# ─────────────────────────────────────────────────────────────────────────
Say "[5/6] Publishing '$branch' -> origin/main ..." Yellow
git fetch origin 2>$null
git tag -f "backup/pre-consolidation" origin/main 2>$null
git push origin "backup/pre-consolidation" --force 2>$null
Say "    old main saved as tag backup/pre-consolidation" DarkGray

git push origin "${branch}:main" 2>$null
if ($LASTEXITCODE -ne 0) {
  Say "    fast-forward rejected (histories diverged) - publishing with --force-with-lease" Yellow
  git push --force-with-lease origin "${branch}:main"
}
if ($LASTEXITCODE -ne 0) { Say "ERROR: push failed. Check 'git remote -v' and your GitHub credentials." Red; exit 1 }
Say "    pushed to origin/main" Green

# keep the working branch in sync too
git push origin "${branch}:${branch}" --force-with-lease 2>$null | Out-Null

# ─────────────────────────────────────────────────────────────────────────
# 6. Prune stale remote branches
# ─────────────────────────────────────────────────────────────────────────
Say "[6/6] Pruning stale remote branches ..." Yellow
foreach ($b in @("master", "claude/track-a-containment-hardening", "claude/enterprise-app-security-review-xialot")) {
  git push origin --delete $b 2>$null
  if ($LASTEXITCODE -eq 0) { Say "    deleted origin/$b" DarkGray }
}
# archive-tag the superseded v3.0 lineage before deleting it
foreach ($b in @("v3.0-ontology-maya-enterprise")) {
  git fetch origin $b 2>$null
  if ($LASTEXITCODE -eq 0) {
    git tag -f "archive/$b" "origin/$b" 2>$null
    git push origin "archive/$b" --force 2>$null
    git push origin --delete $b 2>$null
    if ($LASTEXITCODE -eq 0) { Say "    archived + deleted origin/$b" DarkGray }
  }
}

Say ""
Say "== Done ==" Green
Say "Verify: https://github.com/thepeoplesrealty100-ops/Enterprise-Application" Green
Say "Recover any pruned file with: git checkout HEAD~1 -- <path>" DarkGray
