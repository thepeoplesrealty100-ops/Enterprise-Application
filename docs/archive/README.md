# Archive — superseded status/planning documents

The files in this folder are mid-build status reports, roadmaps, and
handoff notes written by earlier parallel sessions (referring to
themselves as "Gordon"/"Copilot"/etc.) during the pre-v2.9 build and the
subsequent 3-way `main` reconciliation. They are kept for historical
reference only — **their content is superseded and, in places, factually
wrong**:

- `BACKEND_BATCH1_BUILD_SUMMARY.md` already carries its own
  "Reconciliation note" stating its original "✅ COMPLETE — Production
  Ready" claim did not hold up under real testing (its own test suite
  ran against a `MockDB` that no-opped every query).
- `PHASE_2_COMPLETION_SUMMARY.md` and `PHASES_3_5_FINAL_COMPLETION_SUMMARY.md`
  both self-report "100% production ready" / "COMPLETE" status for work
  that the actual reconciliation pass (`../v2.9-batch1-reconciliation.md`,
  `../v2.10-phase2-ui-bridge-reconciliation.md`) found to contain 14 real,
  reproduced bugs — including a syntax error that broke the entire
  backend's import.
- `COMPREHENSIVE_BUILD_PLAN.md` and `ENTERPRISE_ENHANCEMENT_ROADMAP.md`
  are mid-conversation planning docs for work that either already shipped
  (under different names/shapes than planned) or was never picked up;
  `HANDOFF_COMPLETE.md` is a stale progress snapshot ("75% Complete") from
  partway through that same build.

**For the actual, verified state of this codebase, use:**

- `../module-architecture-map.md` — every dashboard module mapped to its
  real backing code, kept current through v3.0 Phase 5.
- `../v2.9-batch1-reconciliation.md`, `../v2.10-phase2-ui-bridge-reconciliation.md`
  — what the reconciliation actually found and fixed, with reproduction
  steps.
- `../v3.0-ontology-maya-enterprise.md` — the Ontology Engine +
  Maya-Vigesimal build and its Phase 0–5 addenda (the interlock fix,
  crypto-agility, core loop visibility, progressive enhancements, and
  controlled expansion).
- The root `README.md`'s "What's new" sections, which are kept accurate
  release-by-release.

`docs/archive/` files still exist because deleting tracked content
destroys nothing git history doesn't already preserve, but keeping them
out of the repo root avoids anyone mistaking their claims for current
status.
