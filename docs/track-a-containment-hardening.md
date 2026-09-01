# Track A — Maya-gated containment hardening

Track A closes the gap between "a human approved this isolation" and
"the isolation is actually safe to run against this org's compliance
posture." Maya still gates the *decision*. Track A gates the *blast
radius and the delivery path*.

## What shipped

| Piece | Path | Role |
|---|---|---|
| Compliance constraints | `backend/security_agents/compliance_constraints.py` | HIPAA residency, SOC2 critical-service, PCI-DSS CDE |
| Hardened orchestrator | `backend/security_agents/edr_hardened.py` | Retry, error class, compliance pre-check, ontology targeting |
| Response router | `backend/routers/response.py` | `enforce` uses the orchestrator; new pre-check + related-targets |
| Operator UI | `integration.js` Response panel | Pre-check before stage; related-target lookup |
| Tests | `backend/tests/test_track_a_hardened_containment.py` | Pass/block/retry/graph cases |

## Compliance pre-flight

`validate_containment_compliance(action_type, target, org_compliance_posture)`
returns `{ compliant, violations[], requires_audit_exception }`.

- **HIPAA** (`45 CFR §164.308(a)(7)`) — if `frameworks` includes HIPAA and
  `hipaa_allowed_regions` is set, the target string must contain an
  allowed region (e.g. `us-east-database-01`). Isolation outside the
  residency boundary is blocked.
- **SOC2 CC7** — if the target is in `soc2_critical_service_hosts`,
  isolation requires a documented audit exception.
- **PCI-DSS 1.2** — if the target is in `pci_dss_cde_hosts`, isolation
  of a cardholder-data-environment host requires an audit exception.

Org posture is read from `global_security_settings.setting_key =
'org_compliance_posture'`. If the row is missing, the check is skipped
(fail-open only on *missing posture*, never on a recorded violation).

## Hardened enforcement

`HardenedEnforcementOrchestrator.enforce_with_retry()`:

1. Compliance pre-check (permanent fail if violated).
2. Up to 3 attempts with 1s → 4s → 16s backoff.
3. `not_configured` (no EDR webhook / Docker) is permanent — no retry.
4. HTTP 5xx / 408 / 429 and connection timeouts are transient.
5. HTTP 4xx and "unauthorized" are permanent.

`POST /api/response/actions/{id}/enforce` still requires an *approved*
isolate/quarantine request. Track A does not auto-execute.

## Attack-path targeting

`GET /api/response/related-targets?target=…&max_depth=2` uses
`OntologyEngine.find_or_create_target_node()` then `query_subgraph()`.
Asset nodes within N hops are returned so an operator can stage
containment on the lateral-movement path, not just the first host.

## Operator flow

1. Enter a host on the Live Ops **Response** tab.
2. **Compliance pre-check** (or it runs automatically on **Stage isolation**).
3. **Related targets** to see the ontology neighborhood.
4. Stage → Maya challenge (HIGH/CRITICAL) → approve → **Enforce**.
5. Enforce goes through the hardened orchestrator, not a one-shot webhook.

## Verification

`cd backend && python -m pytest tests/ -q` — 204 passed, including 14
Track A tests. 0 failures.
