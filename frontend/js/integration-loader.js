/**
 * frontend/js/integration-loader.js
 * 
 * Loads real data from backend API and integrates with frontend components.
 * Replaces mock data with live backend responses.
 * Handles SSE streaming for real-time updates.
 * 
 * Usage (called in index.html after page load):
 *   const loader = new IntegrationLoader(window.JAKALClient);
 *   await loader.loadDashboard('admin_global_dashboard');
 * 
 * v1.0 - Full Phase 2 integration
 */

class IntegrationLoader {
  constructor(apiClient) {
    this.client = apiClient || new JAKALClient();
    this.loadedData = {};
    this.updateIntervals = [];
    this.sseUnsubscribers = [];
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
          console.warn(`No integration loader for page: ${pageKey}`);
      }
    } catch (error) {
      console.error(`Error loading dashboard ${pageKey}:`, error);
      this.showErrorNotification(`Failed to load ${pageKey}: ${error.message}`);
    }
  }

  /**
   * Load Admin Global Dashboard data
   */
  async loadAdminGlobalDashboard() {
    console.log('[IntegrationLoader] Loading Admin Global Dashboard');

    try {
      // Load fleet data
      const fleetResponse = await this.client.getDeviceFleet({ page: 1, per_page: 100 });
      this.loadedData.fleet = fleetResponse;
      this.updateFleetDisplay(fleetResponse);

      // Load matrix data
      const matrixResponse = await this.client.getGlobalMatrix(60);
      this.loadedData.matrix = matrixResponse;
      this.updateMatrixDisplay(matrixResponse);

      // Load health
      const healthResponse = await this.client.getDetailedHealth();
      this.loadedData.health = healthResponse;
      this.updateHealthDisplay(healthResponse);

      // Connect to real-time telemetry
      this.connectTelemetryStream();

      console.log('[IntegrationLoader] Admin Global Dashboard loaded successfully');
    } catch (error) {
      console.error('Error loading admin dashboard:', error);
      throw error;
    }
  }

  /**
   * Load Unified Security Fabric dashboard
   */
  async loadFabricDashboard() {
    console.log('[IntegrationLoader] Loading Fabric Dashboard');

    try {
      const fabricResponse = await this.client.getFabricStatus();
      this.loadedData.fabric = fabricResponse;
      this.updateFabricDisplay(fabricResponse);

      console.log('[IntegrationLoader] Fabric Dashboard loaded successfully');
    } catch (error) {
      console.error('Error loading fabric dashboard:', error);
      throw error;
    }
  }

  /**
   * Load Automation Controls dashboard
   */
  async loadAutomationControls() {
    console.log('[IntegrationLoader] Loading Automation Controls');

    try {
      const policiesResponse = await this.client.getResonancePolicies();
      this.loadedData.policies = policiesResponse;
      this.updatePoliciesDisplay(policiesResponse);

      // Connect to telemetry for live updates
      this.connectTelemetryStream();

      console.log('[IntegrationLoader] Automation Controls loaded successfully');
    } catch (error) {
      console.error('Error loading automation controls:', error);
      throw error;
    }
  }

  /**
   * Load Compliance dashboard
   */
  async loadComplianceDashboard() {
    console.log('[IntegrationLoader] Loading Compliance Dashboard');

    try {
      const settingsResponse = await this.client.getSettingsTab('audit');
      this.loadedData.compliance = settingsResponse;
      this.updateComplianceDisplay(settingsResponse);

      console.log('[IntegrationLoader] Compliance Dashboard loaded successfully');
    } catch (error) {
      console.error('Error loading compliance dashboard:', error);
      throw error;
    }
  }

  /**
   * Load Dark Web Monitoring dashboard
   */
  async loadDarkWebMonitoring() {
    console.log('[IntegrationLoader] Loading Dark Web Monitoring');

    try {
      const auditResponse = await this.client.getResonanceAudit({ limit: 50 });
      this.loadedData.darkWeb = auditResponse;
      this.updateDarkWebDisplay(auditResponse);

      console.log('[IntegrationLoader] Dark Web Monitoring loaded successfully');
    } catch (error) {
      console.error('Error loading dark web monitoring:', error);
      throw error;
    }
  }

  // ========================================================================
  // UPDATE DISPLAY FUNCTIONS
  // ========================================================================

  /**
   * Update fleet display with real data
   */
  updateFleetDisplay(fleetData) {
    console.log('[IntegrationLoader] Updating fleet display with', fleetData.data?.length, 'devices');

    const fleetContainer = document.getElementById('fleet-container');
    if (!fleetContainer) return;

    // Clear existing content
    fleetContainer.innerHTML = '';

    if (!fleetData.data || fleetData.data.length === 0) {
      fleetContainer.innerHTML = '<p class="text-gray-400">No devices found</p>';
      return;
    }

    // Build device table
    const table = document.createElement('table');
    table.className = 'w-full text-sm';
    table.innerHTML = `
      <thead class="border-b border-border-color">
        <tr>
          <th class="text-left py-2 px-3 font-semibold text-gray-300">Device Name</th>
          <th class="text-left py-2 px-3 font-semibold text-gray-300">User</th>
          <th class="text-left py-2 px-3 font-semibold text-gray-300">Status</th>
          <th class="text-left py-2 px-3 font-semibold text-gray-300">Risk</th>
          <th class="text-left py-2 px-3 font-semibold text-gray-300">IP Address</th>
        </tr>
      </thead>
      <tbody>
        ${fleetData.data.map(device => `
          <tr class="border-b border-border-color/50 hover:bg-gray-900/50">
            <td class="py-2 px-3 text-white font-semibold">${device.name}</td>
            <td class="py-2 px-3 text-gray-400">${device.user}</td>
            <td class="py-2 px-3">
              <span class="px-2 py-1 rounded-full text-xs font-bold
                ${device.status === 'online' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}">
                ${device.status}
              </span>
            </td>
            <td class="py-2 px-3">
              <span class="text-${device.risk > 0.7 ? 'red-400' : device.risk > 0.4 ? 'yellow-400' : 'green-400'}">
                ${Math.round(device.risk * 100)}%
              </span>
            </td>
            <td class="py-2 px-3 text-gray-400">${device.ip}</td>
          </tr>
        `).join('')}
      </tbody>
    `;

    fleetContainer.appendChild(table);
  }

  /**
   * Update threat matrix display
   */
  updateMatrixDisplay(matrixData) {
    console.log('[IntegrationLoader] Updating matrix display');

    const matrixContainer = document.getElementById('matrix-container');
    if (!matrixContainer) return;

    matrixContainer.innerHTML = '';

    if (!matrixData.matrix || matrixData.matrix.length === 0) {
      matrixContainer.innerHTML = '<p class="text-gray-400">No threats detected</p>';
      return;
    }

    matrixData.matrix.forEach(group => {
      const groupDiv = document.createElement('div');
      groupDiv.className = 'mb-4 p-4 bg-gray-900/50 rounded-lg border border-border-color';
      groupDiv.innerHTML = `
        <h4 class="font-bold text-white mb-2">${group.origin}</h4>
        <p class="text-sm text-gray-400 mb-3">Total threats: <span class="text-red-400 font-bold">${group.total}</span></p>
        <div class="space-y-2">
          ${group.threats.map(threat => `
            <div class="flex justify-between items-center p-2 bg-gray-800/50 rounded">
              <span class="text-sm text-gray-300">${threat.type}</span>
              <span class="text-xs font-bold text-${threat.severity > 7 ? 'red-400' : threat.severity > 4 ? 'yellow-400' : 'green-400'}">
                Severity: ${threat.severity}
              </span>
            </div>
          `).join('')}
        </div>
      `;
      matrixContainer.appendChild(groupDiv);
    });
  }

  /**
   * Update health display
   */
  updateHealthDisplay(healthData) {
    console.log('[IntegrationLoader] Updating health display');

    const healthContainer = document.getElementById('health-container');
    if (!healthContainer) return;

    healthContainer.innerHTML = `
      <div class="grid grid-cols-4 gap-4">
        <div class="card p-4 rounded-xl text-center">
          <p class="text-xs text-gray-400 uppercase">Database</p>
          <p class="text-lg font-bold text-${healthData.components?.database?.status === 'healthy' ? 'green-400' : 'red-400'}">
            ${healthData.components?.database?.status || 'unknown'}
          </p>
        </div>
        <div class="card p-4 rounded-xl text-center">
          <p class="text-xs text-gray-400 uppercase">Devices</p>
          <p class="text-lg font-bold text-primary-color">${healthData.components?.resources?.devices || 0}</p>
        </div>
        <div class="card p-4 rounded-xl text-center">
          <p class="text-xs text-gray-400 uppercase">Threats</p>
          <p class="text-lg font-bold text-red-400">${healthData.components?.resources?.threat_events || 0}</p>
        </div>
        <div class="card p-4 rounded-xl text-center">
          <p class="text-xs text-gray-400 uppercase">Policies</p>
          <p class="text-lg font-bold text-primary-color">${healthData.components?.resources?.policies || 0}</p>
        </div>
      </div>
    `;
  }

  /**
   * Update fabric display
   */
  updateFabricDisplay(fabricData) {
    console.log('[IntegrationLoader] Updating fabric display');

    const fabricContainer = document.getElementById('fabric-container');
    if (!fabricContainer) return;

    const posture = fabricData.posture || {};
    fabricContainer.innerHTML = `
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="card p-5 rounded-xl border border-primary-color/40 flex flex-col items-center justify-center text-center">
          <div class="text-xs uppercase tracking-wide text-gray-400 mb-1">Zero Trust Posture</div>
          <div class="text-5xl font-black text-primary-color">${posture.overall_score || 0}</div>
          <div class="text-sm font-bold text-primary-color mt-1">${posture.overall_level || 'Unknown'}</div>
        </div>
        <div class="lg:col-span-2 card p-5 rounded-xl border border-border-color">
          <h3 class="text-sm font-bold text-primary-color mb-2">Maturity by Pillar</h3>
          <div class="space-y-2">
            ${Object.entries(posture.by_pillar || {}).map(([name, data]) => `
              <div class="flex justify-between items-center py-1 border-b border-border-color/50">
                <span class="text-xs text-gray-300">${name}</span>
                <div class="flex items-center gap-2">
                  <span class="text-xs font-bold text-primary-color">${data.score}</span>
                  <span class="text-[10px] px-2 py-0.5 rounded-full bg-gray-700 text-gray-300">${data.level}</span>
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Update policies display
   */
  updatePoliciesDisplay(policiesData) {
    console.log('[IntegrationLoader] Updating policies display');

    const policiesContainer = document.getElementById('policies-container');
    if (!policiesContainer) return;

    policiesContainer.innerHTML = '';

    if (!policiesData.policies || policiesData.policies.length === 0) {
      policiesContainer.innerHTML = '<p class="text-gray-400">No policies defined</p>';
      return;
    }

    policiesData.policies.forEach(policy => {
      const policyDiv = document.createElement('div');
      policyDiv.className = 'p-3 bg-gray-900/70 rounded-lg border border-border-color';
      policyDiv.innerHTML = `
        <div class="flex justify-between items-center mb-2">
          <span class="font-semibold text-white">${policy.name}</span>
          <span class="text-xs px-2 py-1 rounded-full ${policy.enabled ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}">
            ${policy.enabled ? 'ENABLED' : 'DISABLED'}
          </span>
        </div>
        <p class="text-xs text-gray-400 mb-2">${policy.description || 'No description'}</p>
        <div class="text-xs text-gray-500 space-y-1">
          <p><strong>Trigger:</strong> ${policy.trigger_type}</p>
          <p><strong>Mode:</strong> ${policy.isolation_mode}</p>
          <p><strong>Threshold:</strong> ${Math.round(policy.threat_threshold * 100)}%</p>
        </div>
      `;
      policiesContainer.appendChild(policyDiv);
    });
  }

  /**
   * Update compliance display
   */
  updateComplianceDisplay(complianceData) {
    console.log('[IntegrationLoader] Updating compliance display');

    const complianceContainer = document.getElementById('compliance-container');
    if (!complianceContainer) return;

    complianceContainer.innerHTML = `
      <div class="space-y-3">
        ${complianceData.settings?.map(setting => `
          <div class="p-3 bg-gray-900/70 rounded-lg border border-border-color">
            <div class="flex justify-between items-center">
              <span class="font-semibold text-white">${setting.key}</span>
              <span class="text-sm text-primary-color">${typeof setting.value === 'object' ? JSON.stringify(setting.value) : setting.value}</span>
            </div>
            <p class="text-xs text-gray-500 mt-1">Updated by ${setting.updated_by || 'system'}</p>
          </div>
        `).join('') || '<p class="text-gray-400">No compliance data available</p>'}
      </div>
    `;
  }

  /**
   * Update dark web display
   */
  updateDarkWebDisplay(darkWebData) {
    console.log('[IntegrationLoader] Updating dark web display');

    const darkWebContainer = document.getElementById('darkweb-container');
    if (!darkWebContainer) return;

    darkWebContainer.innerHTML = '';

    if (!darkWebData.audit_trail || darkWebData.audit_trail.length === 0) {
      darkWebContainer.innerHTML = '<p class="text-gray-400">No threats detected</p>';
      return;
    }

    darkWebData.audit_trail.forEach(event => {
      const eventDiv = document.createElement('div');
      eventDiv.className = 'p-3 bg-gray-900/70 rounded-lg border border-border-color';
      eventDiv.innerHTML = `
        <div class="flex justify-between items-center mb-2">
          <span class="font-semibold text-white">${event.event_type}</span>
          <span class="text-xs font-bold text-${event.status === 'success' ? 'green-400' : 'red-400'}">
            ${event.status}
          </span>
        </div>
        <p class="text-xs text-gray-400">By ${event.actor} on ${new Date(event.timestamp).toLocaleString()}</p>
      `;
      darkWebContainer.appendChild(eventDiv);
    });
  }

  // ========================================================================
  // REAL-TIME STREAMING
  // ========================================================================

  /**
   * Connect to SSE telemetry stream and update UI
   */
  connectTelemetryStream() {
    console.log('[IntegrationLoader] Connecting to telemetry stream');

    const unsubscribe = this.client.onTelemetry((event) => {
      console.log('[IntegrationLoader] Received telemetry event:', event);

      // Update log display if exists
      const logContainer = document.getElementById('telemetry-log');
      if (logContainer) {
        const eventDiv = document.createElement('div');
        eventDiv.className = `text-sm ${event.level_color || 'text-gray-400'} mb-1 flex items-start`;
        eventDiv.innerHTML = `
          <span class="mr-2">[${new Date(event.timestamp).toLocaleTimeString()}]</span>
          <span>${event.message}</span>
        `;
        logContainer.insertBefore(eventDiv, logContainer.firstChild);

        // Keep only last 50 entries
        while (logContainer.children.length > 50) {
          logContainer.removeChild(logContainer.lastChild);
        }
      }
    });

    this.sseUnsubscribers.push(unsubscribe);

    // Start telemetry connection
    this.client.connectTelemetry(
      (event) => {
        console.log('[IntegrationLoader] Telemetry event:', event);
      },
      (error) => {
        console.error('[IntegrationLoader] Telemetry error:', error);
        this.showErrorNotification('Lost connection to telemetry stream');
      }
    );
  }

  /**
   * Periodically refresh data
   */
  startAutoRefresh(pageKey, intervalMs = 30000) {
    console.log(`[IntegrationLoader] Starting auto-refresh for ${pageKey} every ${intervalMs}ms`);

    const intervalId = setInterval(() => {
      this.loadDashboard(pageKey).catch(error => {
        console.error(`[IntegrationLoader] Auto-refresh failed for ${pageKey}:`, error);
      });
    }, intervalMs);

    this.updateIntervals.push(intervalId);
  }

  /**
   * Stop all auto-refresh and SSE connections
   */
  cleanup() {
    console.log('[IntegrationLoader] Cleaning up...');

    // Clear intervals
    this.updateIntervals.forEach(id => clearInterval(id));
    this.updateIntervals = [];

    // Disconnect SSE
    this.sseUnsubscribers.forEach(unsubscribe => unsubscribe());
    this.sseUnsubscribers = [];

    this.client.disconnectTelemetry();
    this.loadedData = {};
  }

  /**
   * Show error notification to user
   */
  showErrorNotification(message) {
    console.error('[IntegrationLoader] Error:', message);
    // Could integrate with toast/notification system here
    window.showAppModal('Integration Error', message);
  }
}

// Export for global use
window.IntegrationLoader = IntegrationLoader;
