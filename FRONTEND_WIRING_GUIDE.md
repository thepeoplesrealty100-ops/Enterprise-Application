# Frontend API Wiring Guide - JAKAL v3.0+

## Overview
Convert 51 hardcoded render functions to use real backend APIs via JAKALClient.

## Pattern: Before & After

### BEFORE (Hardcoded Demo Data)
```javascript
function renderDeviceFleet() {
    const fleet = [
        {id: 'dev-001', name: 'Workstation-Alpha', status: 'online', ...},
        {id: 'dev-002', name: 'Server-Beta', status: 'degraded', ...},
        // More hardcoded devices
    ];
    // Render logic uses static data
}
```

### AFTER (Real API)
```javascript
async function renderDeviceFleet() {
    try {
        const response = await client.getDeviceFleet({page: 1, limit: 20});
        const fleet = response.data;
        // Same render logic now uses real data
        displayFleetTable(fleet);
    } catch (error) {
        console.error('Failed to load fleet:', error);
        displayError('Unable to load device fleet');
    }
}
```

---

## Priority 1: Core Dashboard Functions (Wire First)

### 1. renderDeviceFleet()
- **Line**: ~2250 in index.html
- **Endpoint**: `GET /api/dashboard/fleet?page=1&limit=20`
- **Change**: Replace hardcoded device array with API call
- **Impact**: Shows real device inventory

### 2. renderThreatMatrix()
- **Line**: ~1900
- **Endpoint**: `GET /api/dashboard/matrix`
- **Change**: Replace hardcoded severity counts with real data
- **Impact**: Shows actual threat landscape

### 3. renderFabricPosture()
- **Line**: ~1750
- **Endpoint**: `GET /api/dashboard/fabric/status`
- **Change**: Use posture_score from API
- **Impact**: Real security posture metric

### 4. renderLatestActivity()
- **Line**: ~2350
- **Endpoint**: `GET /api/dashboard/agents/recent`
- **Change**: Replace hardcoded logs with real agent activity
- **Impact**: Real-time operational visibility

### 5. renderQuantumDataNexus()
- **Line**: ~2016
- **Endpoint**: `GET /api/quantum/jobs`
- **Change**: Use real quantum job data
- **Impact**: Shows actual quantum operations

### 6. renderOntologyHub()
- **Line**: ~1423
- **Endpoint**: `GET /api/ontology/nodes` + `GET /api/ontology/edges`
- **Change**: Query real ontology graph
- **Impact**: Shows real attack paths

### 7. renderInvestigationCanvas()
- **Line**: ~1547
- **Endpoint**: `GET /api/investigation/cases`
- **Change**: Load real investigation cases
- **Impact**: Real case management

---

## Priority 2: Advanced Features

### 8. renderCompliance()
- **Endpoint**: `GET /api/compliance/status`

### 9. renderPhishingSim()
- **Endpoint**: `GET /api/automation/phishing/campaigns`

### 10. renderSecurityTraining()
- **Endpoint**: `GET /api/automation/awareness/stats`

### 11. renderDarkWeb()
- **Endpoint**: `GET /api/darkweb/mentions`

### 12. renderEnergyCoreManagement()
- **Endpoint**: `GET /api/energy/core/status`

### 13. renderGlobalPredictiveMatrix()
- **Endpoint**: `GET /api/predictions/matrix`

### 14. renderPredictiveCommand()
- **Endpoint**: `GET /api/predictions/commands`

### 15. renderModelChains()
- **Endpoint**: `GET /api/models/chains`

### 16. renderZeroTrust()
- **Endpoint**: `GET /api/fabric/zt/posture`

### 17. renderUnifiedSecurityFabric()
- **Endpoint**: `GET /api/fabric/summary`

---

## Implementation Steps

### Step 1: Identify Render Function (Example: renderDeviceFleet)
```javascript
// Line ~2250 in index.html
function renderDeviceFleet() {
    // Find where hardcoded data is defined
    const fleet = [{id: 'dev-001', ...}, {...}];
    // Find the display logic
    // ... build table HTML from fleet array
}
```

### Step 2: Extract Display Logic
```javascript
function displayFleetTable(fleet) {
    // Extract the HTML building part
    let html = '<table class="fleet-table">';
    for (let device of fleet) {
        html += `<tr>
            <td>${device.name}</td>
            <td>${device.status}</td>
            ...
        </tr>`;
    }
    html += '</table>';
    document.getElementById('fleet-container').innerHTML = html;
}
```

### Step 3: Make API Call
```javascript
async function renderDeviceFleet() {
    try {
        const response = await client.getDeviceFleet({page: 1, limit: 20});
        displayFleetTable(response.data);
    } catch (error) {
        console.error('Fleet load failed:', error);
        // Show error UI or fallback
    }
}
```

### Step 4: Add Error Handling
```javascript
async function renderDeviceFleet() {
    const container = document.getElementById('fleet-container');
    
    // Show loading state
    container.innerHTML = '<div class="loading">Loading device fleet...</div>';
    
    try {
        const response = await client.getDeviceFleet({page: 1, limit: 20});
        displayFleetTable(response.data);
    } catch (error) {
        console.error('Fleet load failed:', error);
        container.innerHTML = '<div class="error">Failed to load device fleet. Try again.</div>';
    }
}
```

### Step 5: Add Pagination (if applicable)
```javascript
async function renderDeviceFleet(page = 1) {
    const response = await client.getDeviceFleet({
        page: page,
        limit: 20,
        search: document.getElementById('fleet-search')?.value || ''
    });
    
    displayFleetTable(response.data);
    displayPagination(response.pagination);
}
```

---

## JAKALClient Methods Needed

Add these methods to `js/api-client.js`:

```javascript
class JAKALClient {
    // Dashboard endpoints
    async getDeviceFleet(options = {}) {
        return this.get('/api/dashboard/fleet', options);
    }
    
    async getThreatMatrix() {
        return this.get('/api/dashboard/matrix');
    }
    
    async getFabricPosture() {
        return this.get('/api/dashboard/fabric/status');
    }
    
    async getRecentAgentActivity(limit = 10) {
        return this.get('/api/dashboard/agents/recent', {limit});
    }
    
    // Quantum endpoints
    async getQuantumJobs(limit = 20) {
        return this.get('/api/quantum/jobs', {limit});
    }
    
    async executeQuantumCircuit(circuitType) {
        return this.post('/api/quantum/execute', {circuit_type: circuitType});
    }
    
    // Ontology endpoints
    async getOntologyNodes(nodeType = '') {
        return this.get('/api/ontology/nodes', {node_type: nodeType});
    }
    
    async getOntologyEdges() {
        return this.get('/api/ontology/edges');
    }
    
    // Investigation endpoints
    async getInvestigationCases(status = 'open') {
        return this.get('/api/investigation/cases', {status});
    }
    
    // Compliance & monitoring
    async getComplianceStatus() {
        return this.get('/api/compliance/status');
    }
    
    async getResourceStatus() {
        return this.get('/api/dashboard/resources');
    }
    
    async getPhishingCampaigns(limit = 10) {
        return this.get('/api/automation/phishing/campaigns', {limit});
    }
    
    async getPhishingStats() {
        return this.get('/api/automation/phishing/stats');
    }
    
    async getAwarenessStats() {
        return this.get('/api/automation/awareness/stats');
    }
    
    async getDarkWebMentions() {
        return this.get('/api/darkweb/mentions');
    }
    
    async getEnergyCoreStatus() {
        return this.get('/api/energy/core/status');
    }
    
    async getPredictionMatrix() {
        return this.get('/api/predictions/matrix');
    }
    
    async getPredictiveCommands() {
        return this.get('/api/predictions/commands');
    }
    
    async getModelChains() {
        return this.get('/api/models/chains');
    }
    
    async getZeroTrustPosture() {
        return this.get('/api/fabric/zt/posture');
    }
    
    async getFabricSummary() {
        return this.get('/api/fabric/summary');
    }
}
```

---

## Execution Checklist

- [ ] Create JAKALClient methods (copy above)
- [ ] Wire Priority 1 functions (7 most critical)
  - [ ] renderDeviceFleet()
  - [ ] renderThreatMatrix()
  - [ ] renderFabricPosture()
  - [ ] renderLatestActivity()
  - [ ] renderQuantumDataNexus()
  - [ ] renderOntologyHub()
  - [ ] renderInvestigationCanvas()
- [ ] Test each function against real API
- [ ] Add error handling and loading states
- [ ] Wire Priority 2 functions (10 more)
- [ ] Wire remaining functions (34 total)
- [ ] Mobile responsiveness testing
- [ ] Cross-browser testing

---

## Time Estimates

- JAKALClient methods: 30 minutes
- Priority 1 (7 functions): 2-3 hours
- Priority 2 (10 functions): 2-3 hours
- Remaining (34 functions): 4-5 hours
- Testing: 2-3 hours
- **Total: ~12-17 hours** (1.5-2 days of focused work)

---

## Next: Phase 3 Backend Implementation

Once frontend wiring is complete, move to:
1. SOAR Module (capabilities_engine.py)
2. Multi-Tenant Support (tenant_service.py)
3. Fleet Management (real device aggregation)
4. Integrations (OAuth flows)
5. Automation (script execution runtime)

See `/plans/binary-tinkering-turing.md` for full Phase 3 details.
