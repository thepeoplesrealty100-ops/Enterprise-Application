# JAKAL Enterprise Application - Comprehensive Build Plan
## Phase 2-4 Development Roadmap | Status: In Progress

**Last Updated:** 2026-09-01  
**Current Version:** v2.5+ (Backend Ready)  
**Next Major Version:** v2.8 (Post-Frontend Build)

---

## EXECUTIVE SUMMARY

### Current State ✅
- **Backend Batch 1:** 100% Complete (Commit: 4c3c0dd)
  - ✅ Core Enforcement Engine (650+ lines)
  - ✅ Webhook Dispatcher with HMAC-SHA256
  - ✅ Immutable Audit Logger (SHA3-256 chaining)
  - ✅ Enhanced Resonance Router
  - ✅ Script Library Router
  - ✅ Database Extensions (5 new tables)
  - ✅ App Integration & Testing
  
- **Frontend:** 100% HTML/CSS/JS (index.html)
  - ✅ Dashboard Grid System
  - ✅ 20+ UI Components (Tabs, Cards, Modals)
  - ✅ Horizon AI Safety Fabric Module
  - ✅ Agentic Investigation Canvas
  - ✅ Global Predictive Matrix
  - ✅ Security Fabric (7-pillar NSA/CISA)
  - ⚠️ Static mock data (no backend integration yet)

### Gaps Identified 🔴
1. **Frontend-Backend Integration:** No API wiring yet
2. **Database Sync:** Mock data ≠ real DuckDB state
3. **Redundant Code:** backend-v3 directory (old/unused)
4. **Missing Cleanup:** Old branches, duplicate scripts
5. **Test Coverage:** No integration tests (only backend unit tests)
6. **Deployment:** Docker works, but K8s manifests untested

---

## PHASE 2: FRONTEND-BACKEND INTEGRATION (6-8 hours)

### 2.1 API Endpoint Bridging
**Files to Create/Modify:**

#### `backend/routers/ui_bridge.py` (NEW - 300+ lines)
```python
# Bridge between static frontend and live backend
# Endpoints:
# - GET /api/dashboard/fleet → device list from DuckDB
# - GET /api/dashboard/matrix → threat matrix from telemetry
# - GET /api/dashboard/settings → global settings snapshot
# - POST /api/dashboard/action → execute device action
# - GET /api/telemetry/stream (SSE) → live updates
# - GET /api/fabric/status → unified fabric posture
# - GET /api/scripts/catalog → script library from DB
# - GET /api/resonance/policies → automation policies
```

#### `backend/app.py` (MODIFY - Add UI router)
```python
from routers.ui_bridge import router as ui_router
app.include_router(ui_router, prefix="/api", tags=["UI Bridge"])
```

#### `frontend/js/api-client.js` (NEW - 250+ lines)
```javascript
// Centralized API client for all backend calls
class JAKALClient {
  async getFleetDevices(filter = null) { }
  async getGlobalMatrix() { }
  async executeDeviceAction(deviceId, action) { }
  async getScriptCatalog(filter) { }
  async getResonancePolicies() { }
  // ... plus streaming/SSE methods
}
```

#### `frontend/js/integration-loader.js` (NEW - 200+ lines)
```javascript
// Load and sync data from backend to frontend components
// - On page load, replace mock data with real data from API
// - Keep SSE listener for live updates
// - Cache responses appropriately
```

### 2.2 Database Query Optimization
**Modify `backend/database.py`:**
- Add query indexes on frequently accessed columns
- Add prepared statement caching
- Implement connection pooling (currently single-threaded)

**New Query Methods in `DuckDBManager`:**
```python
async def get_devices_by_client(self, client_id: str) → List[Dict]
async def get_device_status_summary() → Dict
async def get_threat_matrix_data(time_window: int) → List[Dict]
async def get_audit_trail(filters: Dict) → List[Dict]
async def get_fabric_posture_score() → float
```

### 2.3 Real-time Telemetry Streaming
**Modify `backend/services/telemetry_service.py`:**
- Implement event emitter for all dashboard actions
- Wire to SSE endpoint in UI Bridge
- Track device status changes, threat detections, policy changes

---

## PHASE 3: COMPONENT LIBRARY & UI ENHANCEMENTS (6-8 hours)

### 3.1 Extract Reusable Components
**Create `frontend/js/components/` directory:**
- `TelemetryCard.js` - KPI display component
- `ThreatMatrix.js` - Visualization component
- `TimeSeriesChart.js` - Chart wrapper
- `NodeLinkGraph.js` - Cytoscape wrapper
- `DeviceTable.js` - Sortable/filterable device list
- `PolicyPanel.js` - Policy management component
- `ApprovalModal.js` - Approval workflow component

### 3.2 Dashboard Refactoring
**Split `index.html` into:**
- `frontend/index.html` (shell - load components dynamically)
- `frontend/js/app-init.js` (initialization logic)
- `frontend/js/page-renderers.js` (page-specific renderers)
- `frontend/css/theme.css` (centralized styling)

### 3.3 Mobile Responsiveness
- Verify Tailwind breakpoints work correctly
- Test on mobile devices
- Add touch event handlers for drag-drop components

---

## PHASE 4: TESTING & DEPLOYMENT (4-6 hours)

### 4.1 Integration Test Suite
**Create `backend/tests/integration/test_ui_bridge.py`:**
```python
# Test 10 critical flows:
# 1. Load devices from fleet endpoint
# 2. Apply device filter
# 3. Execute device action (isolation)
# 4. Track action in audit log
# 5. Update device status in real-time
# 6. Get global matrix threat data
# 7. Create/update resonance policy
# 8. Query script library
# 9. SSE streaming delivers updates
# 10. Fabric posture score updates after action
```

### 4.2 End-to-End Tests (Frontend + Backend)
**Create `tests/e2e/test_scenarios.js` (Playwright):**
```javascript
// Scenario 1: Admin logs in → views fleet → isolates device
// Scenario 2: Operator sees threat alert → approves isolation → device isolated
// Scenario 3: Client portal → views protected devices → downloads report
// ... 7 more critical user workflows
```

### 4.3 Docker & Kubernetes Validation
**`tests/deployment/test_docker.sh`:**
```bash
# Build image
# Run container
# Test health endpoint
# Test API endpoints
# Verify frontend loads
# Test SSE connection
# Cleanup
```

**`tests/deployment/test_k8s.sh`:**
```bash
# Apply manifests
# Wait for rollout
# Port forward
# Test all endpoints
# Verify pod logs
# Scale replicas
# Cleanup
```

---

## CLEANUP & ORGANIZATION PLAN

### Files to DELETE (Redundant)
- [ ] `backend-v3/` - Old version, unused
- [ ] `master` branch - Move to archive
- [ ] Old setup scripts if duplicated
- [ ] Any `.bak` or `.old` files

### Files to CONSOLIDATE
- [ ] Multiple `requirements.txt` → single canonical version
- [ ] Setup scripts → single `setup.sh` with platform detection
- [ ] Multiple configs → single `.env.example`

### Directories to REORGANIZE
```
backend/
  ├── core/          (enforcement, webhook, audit)
  ├── routers/       (API endpoints)
  ├── services/      (telemetry, database)
  ├── security_agents/  (compliance, EDR)
  ├── tests/         (unit + integration)
  ├── migrations/    (database schema versions)
  └── docker/        (Docker-specific files)

frontend/
  ├── index.html     (main shell)
  ├── js/
  │   ├── api-client.js
  │   ├── components/
  │   ├── pages/
  │   └── utils/
  ├── css/
  │   ├── theme.css
  │   ├── components.css
  │   └── responsive.css
  └── assets/        (images, icons)

k8s/
  ├── deployment.yaml
  ├── service.yaml
  ├── configmap.yaml
  └── ingress.yaml

tests/
  ├── backend/
  │   ├── unit/
  │   └── integration/
  ├── frontend/
  │   └── e2e/
  └── deployment/
```

---

## DETAILED IMPLEMENTATION CHECKLIST

### Week 1: Phase 2 (API Integration)

**Day 1-2: API Bridge**
- [ ] Create `ui_bridge.py` router (200 lines)
- [ ] Add 8 new endpoints
- [ ] Test each endpoint manually
- [ ] Document in Swagger

**Day 2-3: Frontend Client**
- [ ] Create `api-client.js` class
- [ ] Implement data fetching methods
- [ ] Add error handling & retries
- [ ] Add request caching

**Day 3-4: Integration Testing**
- [ ] Write 10 integration tests
- [ ] Run locally, fix failures
- [ ] Achieve 90%+ pass rate

**Day 4-5: Live Data**
- [ ] Replace mock data with real API calls
- [ ] Add SSE listeners
- [ ] Test dashboard with live backend
- [ ] Verify in Docker container

### Week 2: Phase 3 (UI Enhancement)

**Day 1-2: Component Extraction**
- [ ] Extract 7 reusable components
- [ ] Create component library
- [ ] Document component API

**Day 2-3: Dashboard Refactor**
- [ ] Split `index.html` into modules
- [ ] Update module imports
- [ ] Test all dashboard pages

**Day 3-4: Mobile & Polish**
- [ ] Add mobile breakpoints
- [ ] Test on 3 devices
- [ ] Add touch handlers
- [ ] Performance optimization

**Day 4-5: Deployment Prep**
- [ ] Update Docker image
- [ ] Test K8s manifests
- [ ] Document deployment

### Week 3: Phase 4 (Testing & Cleanup)

**Day 1-2: Test Suite**
- [ ] Write integration tests
- [ ] Write E2E tests
- [ ] Document test running

**Day 2-3: Cleanup**
- [ ] Delete redundant files
- [ ] Merge duplicate code
- [ ] Archive old branches

**Day 3-4: Final Validation**
- [ ] 10-pass testing protocol
- [ ] Performance testing
- [ ] Security audit

**Day 4-5: Documentation**
- [ ] Update README
- [ ] API docs
- [ ] Deployment guide

---

## TESTING PROTOCOL (10-Pass Validation)

Each major phase will be tested 10 times before merge:

**Pass 1-3: Local Development**
- Test locally with `python -m pytest tests/`
- Manual browser testing
- Docker compose test

**Pass 4-6: Integration**
- Test API endpoints with curl
- Test frontend-backend sync
- Test database persistence

**Pass 7-8: Deployment**
- Test Docker build
- Test Kubernetes deployment
- Test horizontal scaling

**Pass 9-10: Production Readiness**
- Security scan
- Performance benchmarks
- Load testing

---

## SUCCESS CRITERIA

### Phase 2 Complete When:
- ✅ All API endpoints tested and working
- ✅ Frontend displays real data from backend
- ✅ SSE streaming functional
- ✅ 90%+ test pass rate
- ✅ Docker container runs without errors

### Phase 3 Complete When:
- ✅ 7 components extracted and reusable
- ✅ Dashboard responsive on mobile
- ✅ No console errors
- ✅ Performance <500ms load time

### Phase 4 Complete When:
- ✅ 100% integration test pass rate
- ✅ 10 E2E scenarios passing
- ✅ Kubernetes manifests validated
- ✅ Zero security vulnerabilities
- ✅ All documentation updated

---

## GITHUB WORKFLOW

### Branch Strategy
```
main (stable, production-ready)
├── feature/phase-2-api-integration
├── feature/phase-3-ui-components
├── feature/phase-4-testing
└── cleanup/remove-redundant-files

master (deprecated, archive)
claude/enterprise-app-security-review (feature review)
```

### PR Process
1. Create feature branch from `main`
2. Implement feature
3. Run 10-pass test protocol
4. Open PR with test results
5. Code review + approval
6. Merge to `main`
7. Tag release (v2.6, v2.7, v2.8)

---

## ESTIMATED TIMELINE

| Phase | Duration | Target Completion |
|-------|----------|-------------------|
| Phase 2: API Integration | 4-5 days | Sept 5 |
| Phase 3: UI Enhancement | 3-4 days | Sept 8 |
| Phase 4: Testing & Cleanup | 2-3 days | Sept 10 |
| **TOTAL** | **9-12 days** | **Sept 10, 2026** |

---

## ROLLBACK PLAN

If critical issues found:
1. Revert to last stable commit
2. Document issue in GitHub issue
3. Create hotfix branch
4. Implement fix with tests
5. Re-merge after validation

---

## NEXT IMMEDIATE ACTIONS

1. ✅ Read this plan
2. 🔜 Audit local vs GitHub state (THIS SESSION)
3. 🔜 Delete `backend-v3` and old branches
4. 🔜 Create `feature/phase-2-api-integration` branch
5. 🔜 Implement 5 core API endpoints
6. 🔜 Run first 10-pass test cycle
7. 🔜 Commit & push to GitHub

**Status:** READY FOR EXECUTION  
**Owner:** @thepeoplesrealty100-ops  
**Reviewer:** Code review team
