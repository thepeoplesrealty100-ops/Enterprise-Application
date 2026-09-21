/**
 * frontend/js/integration-loader.js
 * 
 * Loads real data from backend API and integrates with frontend components.
 * Replaces mock data with live backend responses.
 * Handles SSE streaming for real-time updates.
 * 
 * v1.0 - Full Phase 2 integration
 */

class IntegrationLoader {
  constructor(apiClient) {
    this.client = apiClient || new JAKALClient();
    this.loadedData = {};
    this.updateIntervals = [];
    this.sseUnsubscribers = [];
    console.log('[IntegrationLoader] Initialized');
  }

  /**
   * Load all data for a specific page/module
   */
  async loadDashboard(pageKey) {
    console.log(`[IntegrationLoader] Loading dashboard: ${pageKey}`);
    
    try {
      switch (pageKey) {
        case 'admin_global_dashboard':
          await this.loadAdminGlobalDashboard();
          break;
        case 'admin_fabric':
          await this.loadFabricDashboard();
          break;
        case 'admin_automation_controls':
          await this.loadAutomationControls();
          break;
        case 'admin_compliance':
          await this.loadComplianceDashboard();
          break;
        case 'admin_dark_web':
          await this.loadDarkWebMonitoring();
          break;
        default:
          console.warn(`[IntegrationLoader] No loader for page: ${pageKey}`);
      }
    } catch (error) {
      console.error(`[IntegrationLoader] Error loading ${pageKey}:`, error);
    }
  }

  /**
   * Load Admin Global Dashboard data
   */
  async loadAdminGlobalDashboard() {
    try {
      console.log('[IntegrationLoader] Loading fleet...');
      const fleetResponse = await this.client.getDeviceFleet({ page: 1, per_page: 100 });
      this.loadedData.fleet = fleetResponse;
      this.updateFleetDisplay(fleetResponse);

      console.log('[IntegrationLoader] Loading matrix...');
      const matrixResponse = await this.client.getGlobalMatrix(60);
      this.loadedData.matrix = matrixResponse;
      this.updateMatrixDisplay(matrixResponse);

      console.log('[IntegrationLoader] Loading health...');
      const healthResponse = await this.client.getDetailedHealth();
      this.loadedData.health = healthResponse;
      this.updateHealthDisplay(healthResponse);

      // Connect to real-time telemetry
      this.connectTelemetryStream();

      console.log('[IntegrationLoader] Dashboard loaded successfully');
    } catch (error) {
      console.error('[IntegrationLoader] Error loading dashboard:', error);
    }
  }

  /**
   * Load Unified Security Fabric dashboard
   */
  async loadFabricDashboard() {
    try {
      console.log('[IntegrationLoader] Loading fabric status...');
      const fabricResponse = await this.client.getFabricStatus();
      this.loadedData.fabric = fabricResponse;
      this.updateFabricDisplay(fabricResponse);
      console.log('[IntegrationLoader] Fabric dashboard loaded');
    } catch (error) {
      console.error('[IntegrationLoader] Error loading fabric:', error);
    }
  }

  /**
   * Load Automation Controls dashboard
   */
  async loadAutomationControls() {
    try {
      console.log('[IntegrationLoader] Loading policies...');
      const policiesResponse = await this.client.getResonancePolicies();
      this.loadedData.policies = policiesResponse;
      this.updatePoliciesDisplay(policiesResponse);
      this.connectTelemetryStream();
      console.log('[IntegrationLoader] Automation controls loaded');
    } catch (error) {
      console.error('[IntegrationLoader] Error loading automation:', error);
    }
  }

  /**
   * Load Compliance dashboard
   */
  async loadComplianceDashboard() {
    try {
      console.log('[IntegrationLoader] Loading compliance...');
      const settingsResponse = await this.client.getGlobalSettings();
      this.loadedData.compliance = settingsResponse;
      this.updateComplianceDisplay(settingsResponse);
      console.log('[IntegrationLoader] Compliance dashboard loaded');
    } catch (error) {
      console.error('[IntegrationLoader] Error loading compliance:', error);
    }
  }

  /**
   * Load Dark Web Monitoring dashboard
   */
  async loadDarkWebMonitoring() {
    try {
      console.log('[IntegrationLoader] Loading audit trail...');
      const auditResponse = await this.client.getResonanceAudit({ limit: 50 });
      this.loadedData.darkWeb = auditResponse;
      this.updateDarkWebDisplay(auditResponse);
      console.log('[IntegrationLoader] Dark web monitoring loaded');
    } catch (error) {
      console.error('[IntegrationLoader] Error loading dark web:', error);
    }
  }

  // ========================================================================
  // UPDATE DISPLAY FUNCTIONS
  // ========================================================================

  /**
   * Update fleet display with real data
   */
  updateFleetDisplay(fleetData) {
    const fleetContainer = document.getElementById('fleet-container');
    if (!fleetContainer) return;

    fleetContainer.innerHTML = '';

    if (!fleetData.data || fleetData.data.length === 0) {
      fleetContainer.innerHTML = '<p class="text-gray-400 p-4">No devices found</p>';
      return;
    }

    // Build device list
    const listHTML = fleetData.data.map(device => `
      <div class="p-3 bg-gray-900/50 border border-border-color rounded-lg flex justify-between items-center mb-2">
        <div>
          <p class="text-white font-semibold">${device.name || 'Unknown'}</p>
          <p class="text-xs text-gray-400">${device.ip} • ${device.os || 'Unknown OS'}</p>
        </div>
        <div class="text-right">
          <p class="text-sm font-bold text-${device.risk > 0.7 ? 'red-400' : 'yellow-400'}">
            Risk: ${Math.round(device.risk * 100)}%
          </p>
        </div>
      </div>
    `).join('');

    fleetContainer.innerHTML = listHTML;
  }

  /**
   * Update threat matrix display
   */
  updateMatrixDisplay(matrixData) {
    const matrixContainer = document.getElementById('matrix-container');
    if (!matrixContainer) return;

    matrixContainer.innerHTML = '';

    if (!matrixData.matrix) {
      matrixContainer.innerHTML = '<p class="text-gray-400 p-4">No threats detected</p>';
      return;
    }

    const severities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
    let html = '';

    severities.forEach(severity => {
      const threats = matrixData.matrix[severity] || [];
      if (threats.length > 0) {
        html += `
          <div class="mb-4">
            <h4 class="text-sm font-bold text-${severity === 'CRITICAL' ? 'red-400' : 'yellow-400'} mb-2">
              ${severity} (${threats.length})
            </h4>
            <div class="space-y-1">
              ${threats.map(threat => `
                <p class="text-xs text-gray-300 p-2 bg-gray-800/50 rounded">
                  ${threat.title || 'Unknown'}
                </p>
              `).join('')}
            </div>
          </div>
        `;
      }
    });

    matrixContainer.innerHTML = html || '<p class="text-gray-400 p-4">No threats detected</p>';
  }

  /**
   * Update health display
   */
  updateHealthDisplay(healthData) {
    const healthContainer = document.getElementById('health-container');
    if (!healthContainer) return;

    const resources = healthData.components?.resources || {};
    
    healthContainer.innerHTML = `
      <div class="grid grid-cols-4 gap-2 text-center">
        <div class="p-3 bg-gray-900/70 rounded-lg">
          <p class="text-xs text-gray-400">Devices</p>
          <p class="text-lg font-bold text-primary-color">${resources.devices || 0}</p>
        </div>
        <div class="p-3 bg-gray-900/70 rounded-lg">
          <p class="text-xs text-gray-400">Findings</p>
          <p class="text-lg font-bold text-red-400">${resources.findings || 0}</p>
        </div>
        <div class="p-3 bg-gray-900/70 rounded-lg">
          <p class="text-xs text-gray-400">Policies</p>
          <p class="text-lg font-bold text-primary-color">${resources.policies || 0}</p>
        </div>
        <div class="p-3 bg-gray-900/70 rounded-lg">
          <p class="text-xs text-gray-400">Logs</p>
          <p class="text-lg font-bold text-blue-400">${resources.audit_logs || 0}</p>
        </div>
      </div>
    `;
  }

  /**
   * Update fabric display
   */
  updateFabricDisplay(fabricData) {
    const fabricContainer = document.getElementById('fabric-container');
    if (!fabricContainer) return;

    const posture = fabricData || {};
    const pillars = posture.by_pillar || {};

    let html = `
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <div class="p-4 bg-gray-900/70 rounded-lg border border-primary-color/40 text-center">
          <p class="text-xs text-gray-400 mb-2">Zero Trust Score</p>
          <p class="text-4xl font-bold text-primary-color">${posture.overall_score || 0}</p>
          <p class="text-sm text-gray-400">${posture.overall_level || 'Unknown'}</p>
        </div>
      </div>
      <div class="space-y-2">
    `;

    Object.entries(pillars).forEach(([name, data]) => {
      html += `
        <div class="p-2 bg-gray-900/50 rounded border border-border-color/50 flex justify-between items-center">
          <span class="text-sm text-gray-300">${name}</span>
          <span class="text-xs font-bold text-primary-color">${data.score}/100</span>
        </div>
      `;
    });

    html += '</div>';
    fabricContainer.innerHTML = html;
  }

  /**
   * Update policies display
   */
  updatePoliciesDisplay(policiesData) {
    const policiesContainer = document.getElementById('policies-container');
    if (!policiesContainer) return;

    policiesContainer.innerHTML = '';

    if (!policiesData.policies || policiesData.policies.length === 0) {
      policiesContainer.innerHTML = '<p class="text-gray-400">No policies defined</p>';
      return;
    }

    const html = policiesData.policies.map(policy => `
      <div class="p-3 bg-gray-900/70 rounded-lg border border-border-color mb-2">
        <div class="flex justify-between items-center mb-1">
          <span class="font-semibold text-white">${policy.name}</span>
          <span class="text-xs px-2 py-1 rounded-full ${policy.enabled ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}">
            ${policy.enabled ? 'ON' : 'OFF'}
          </span>
        </div>
        <p class="text-xs text-gray-500">Threshold: ${Math.round(policy.threat_threshold * 100)}%</p>
      </div>
    `).join('');

    policiesContainer.innerHTML = html;
  }

  /**
   * Update compliance display
   */
  updateComplianceDisplay(complianceData) {
    const complianceContainer = document.getElementById('compliance-container');
    if (!complianceContainer) return;

    const settings = complianceData.settings || {};
    let html = '<div class="space-y-2">';

    Object.entries(settings).forEach(([key, value]) => {
      html += `
        <div class="p-2 bg-gray-900/50 rounded border border-border-color/50">
          <p class="text-xs text-gray-400">${key}</p>
          <p class="text-sm text-primary-color font-semibold">${value}</p>
        </div>
      `;
    });

    html += '</div>';
    complianceContainer.innerHTML = html;
  }

  /**
   * Update dark web display
   */
  updateDarkWebDisplay(darkWebData) {
    const darkWebContainer = document.getElementById('darkweb-container');
    if (!darkWebContainer) return;

    darkWebContainer.innerHTML = '';

    if (!darkWebData.audit_trail || darkWebData.audit_trail.length === 0) {
      darkWebContainer.innerHTML = '<p class="text-gray-400">No events detected</p>';
      return;
    }

    const html = darkWebData.audit_trail.slice(0, 20).map(event => `
      <div class="p-2 bg-gray-900/50 rounded border border-border-color/50 mb-1 text-xs">
        <p class="text-gray-300">${event.event_type} - <span class="text-gray-500">${event.action}</span></p>
        <p class="text-gray-600 text-[10px]">${event.timestamp}</p>
      </div>
    `).join('');

    darkWebContainer.innerHTML = html;
  }

  // ========================================================================
  // REAL-TIME STREAMING
  // ========================================================================

  /**
   * Connect to SSE telemetry stream and update UI
   */
  connectTelemetryStream() {
    console.log('[IntegrationLoader] Connecting to telemetry');

    const unsubscribe = this.client.onTelemetry((event) => {
      console.log('[IntegrationLoader] Telemetry event:', event);

      const logContainer = document.getElementById('telemetry-log');
      if (logContainer) {
        const eventDiv = document.createElement('div');
        eventDiv.className = `text-xs ${event.level_color || 'text-gray-400'} mb-1`;
        eventDiv.textContent = `[${new Date().toLocaleTimeString()}] ${event.message || 'Event'}`;
        logContainer.insertBefore(eventDiv, logContainer.firstChild);

        // Keep only last 50
        while (logContainer.children.length > 50) {
          logContainer.removeChild(logContainer.lastChild);
        }
      }
    });

    this.sseUnsubscribers.push(unsubscribe);

    this.client.connectTelemetry(
      (event) => console.log('[IntegrationLoader] Telemetry:', event),
      (error) => console.error('[IntegrationLoader] Telemetry error:', error)
    );
  }

  /**
   * Periodically refresh data
   */
  startAutoRefresh(pageKey, intervalMs = 30000) {
    console.log(`[IntegrationLoader] Auto-refresh: ${pageKey} every ${intervalMs}ms`);

    const intervalId = setInterval(() => {
      this.loadDashboard(pageKey).catch(e => console.error('Auto-refresh error:', e));
    }, intervalMs);

    this.updateIntervals.push(intervalId);
  }

  /**
   * Stop all connections
   */
  cleanup() {
    console.log('[IntegrationLoader] Cleaning up');
    this.updateIntervals.forEach(id => clearInterval(id));
    this.updateIntervals = [];
    this.sseUnsubscribers.forEach(unsub => unsub());
    this.sseUnsubscribers = [];
    this.client.disconnectTelemetry();
  }
}

// Export for global use
window.IntegrationLoader = IntegrationLoader;
console.log('[IntegrationLoader] Loaded successfully');
