# Enterprise Application API — JAKAL v3.0 Phase 3

## Response & Remediation Endpoints

### Compliance Pre-Check
**GET /api/response/compliance/pre-check**

Real-time compliance validation before staging containment actions.

Query Parameters:
- `action_type` (string, required): Action type (isolate_host_staged, quarantine_host_staged)
- `target` (string, required): Target IP/hostname

Response:
```json
{
  "compliant": true,
  "violations": [
    {
      "constraint": "hipaa_data_residency",
      "reason": "Target region not in HIPAA allowed list"
    }
  ],
  "requires_audit_exception": false,
  "target": "192.168.1.1",
  "action_type": "isolate_host_staged"
}
```

Status Codes:
- 200: Success
- 422: Invalid action_type
- 500: Compliance engine error

**Use Case**: Compliance validation UI before user stages action. Blocks enforcement if violations exist unless audit exception approved.

---

### Attack-Path Analysis (Phase 1)
**GET /api/response/related-targets**

Identifies lateral-movement paths and related targets within max_depth hops.

Query Parameters:
- `target` (string, required): Primary target IP/hostname
- `max_depth` (integer, optional): Graph traversal depth (1-5, default 2)

Response:
```json
{
  "target": "10.0.0.1",
  "max_depth": 2,
  "related_targets": [
    "10.0.0.2",
    "10.0.0.3",
    "10.0.0.5"
  ],
  "count": 3,
  "note": "Use these targets as input for additional quarantine/isolate actions..."
}
```

Status Codes:
- 200: Success
- 422: Invalid max_depth
- 500: Ontology query error

**Use Case**: Simple list of related targets for batch remediation. No prioritization.

---

### Attack-Path Analysis with Criticality (Phase 3)
**GET /api/response/related-targets-v3**

Phase 3 enhancement: relates targets with criticality scoring for risk-prioritized remediation.

Query Parameters:
- `target` (string, required): Primary target IP/hostname
- `max_depth` (integer, optional): Graph traversal depth (1-4, default 4)

Response:
```json
{
  "target": "10.0.0.1",
  "max_depth": 4,
  "related_targets": [
    {
      "target": "prod-db-primary-01",
      "criticality_score": 0.74,
      "depth": 1,
      "edge_types": ["lateral_movement"],
      "node_id": "node-uuid-123"
    },
    {
      "target": "auth-service-prod",
      "criticality_score": 0.43,
      "depth": 2,
      "edge_types": ["exploit_path", "privilege_escalation"],
      "node_id": "node-uuid-456"
    },
    {
      "target": "workstation-01",
      "criticality_score": 0.05,
      "depth": 3,
      "edge_types": ["lateral_movement"],
      "node_id": "node-uuid-789"
    }
  ],
  "count": 3,
  "note": "Sorted by criticality_score (descending). Use for risk-prioritized..."
}
```

**Criticality Scoring** (0.0-1.0):
- Critical Service Flag: +0.4 (e.g., databases, auth systems)
- Production Status: +0.2 (if "prod" in target name)
- Service Type: +0.15 (if "db", "auth", or "admin" in name)
- Confidence Score: +0.1x (0.9 confidence → +0.09)

Status Codes:
- 200: Success
- 422: Invalid max_depth (must be 1-4)
- 500: Ontology query error

**Use Case**: Multi-target remediation with prioritization. High-criticality targets ranked first for targeted containment strategy.

---

## Enforcement Endpoints

### Execute Staged Enforcement
**POST /api/response/enforce**

Executes an already-approved containment action with retry logic and compliance gating.

Request Body:
```json
{
  "action_type": "isolate_host_staged",
  "target": "10.0.0.1",
  "detail": {
    "reason": "Suspicious lateral movement detected"
  },
  "operator_id": "analyst_001"
}
```

Response:
```json
{
  "status": "enforced",
  "attempts": 1,
  "connector": "webhook",
  "detail": {
    "http_status": 200
  },
  "compliance_validated": true,
  "error_classification": null
}
```

**status** Values:
- `enforced`: Action succeeded on first or retry attempt
- `error`: Action failed (compliance violation or permanent error)
- `not_configured`: Connector not available

**error_classification** Values:
- `transient`: Retryable (network, rate limit, timeout)
- `permanent`: Non-retryable (auth, config, permission)
- `unknown`: Classification unavailable
- `null`: No error

Status Codes:
- 200: Action completed (check status field for outcome)
- 403: User lacks permission
- 500: Orchestrator error

**Retry Logic**:
- Max attempts: 3 (configurable)
- Backoff: 1s → 4s → 16s (exponential, base 4x)
- Transient errors retry, permanent errors halt immediately

---

## Data Flow: Complete Workflow

### Scenario: Multi-target Containment with Risk Prioritization

1. **Triage Finding** → Risk scored (CRITICAL)
   
2. **Pre-stage Check** (Compliance)
   ```
   GET /api/response/compliance/pre-check
   ?action_type=isolate_host_staged&target=10.0.0.1
   ```
   Response: Compliant ✓

3. **Discover Attack Paths** (Phase 3)
   ```
   GET /api/response/related-targets-v3
   ?target=10.0.0.1&max_depth=4
   ```
   Response: 3 related targets, sorted by criticality
   - prod-db (0.74) ← High priority
   - auth-service (0.43) ← Medium priority
   - workstation (0.05) ← Low priority

4. **Stage Actions** (Manual approval per target)
   ```
   POST /api/approval/request
   {
     "action_type": "isolate_host_staged",
     "target": "prod-db-primary-01",
     "reason": "High-criticality target with privilege escalation risk"
   }
   ```

5. **Operator Approves** (Maya step-up challenge if CRITICAL)
   ```
   POST /api/approval/{id}/approve
   ```

6. **Execute with Retry**
   ```
   POST /api/response/enforce
   {
     "action_type": "isolate_host_staged",
     "target": "prod-db-primary-01",
     "operator_id": "analyst_001"
   }
   ```
   Response: Enforced after 1-2 attempts (if transient failure on first)

7. **Repeat for Medium/Low Priority Targets**
   - auth-service: Quarantine (less disruptive)
   - workstation: Monitor (defer if low risk)

---

## Error Handling

### Transient Errors (Retryable)
- HTTP 500, 502, 503, 504: Server errors
- HTTP 408, 429: Request timeout, rate limit
- Network: "connection refused", "timeout"

**Action**: Automatic retry with exponential backoff.

### Permanent Errors (No Retry)
- HTTP 400, 401, 403, 404, 422: Client/config errors
- Network: "not configured", "unauthorized"

**Action**: Fail immediately, return error detail.

### Compliance Errors
- Target violates HIPAA data residency
- Target is SOC2 critical service
- Target is PCI-DSS cardholder environment

**Action**: Return 403 Forbidden + violation detail. Require audit exception to override.

---

## Authentication & Authorization

All endpoints require:
- Bearer token in Authorization header
- User must have "response:enforce" permission (role-based)
- Maya step-up challenge for CRITICAL risk level actions

---

## Rate Limiting

Per-user per-endpoint rate limits:
- /compliance/pre-check: 100 req/min (validation preview)
- /related-targets: 20 req/min (graph queries are expensive)
- /related-targets-v3: 20 req/min (deep traversal)
- /enforce: 10 req/min (safety gate on enforcement)

---

## Testing

Run complete test suite:
```bash
cd backend && python -m pytest tests/ -v --tb=short
```

Run Phase-specific tests:
- Phase 2 Resilience: `pytest tests/resilience/test_partition.py`
- Phase 3 Attack-Paths: `pytest tests/test_phase3_attack_paths.py`
- Track A Integration: `pytest tests/test_track_a_hardened_containment.py`
