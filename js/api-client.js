/**
 * frontend/js/api-client.js
 * 
 * Centralized JAKAL API Client
 * Provides all methods for communicating with the backend REST API and SSE streams.
 * 
 * Usage:
 *   const client = new JAKALClient('http://localhost:8000');
 *   const fleet = await client.getDeviceFleet({ page: 1 });
 *   client.connectTelemetry((event) => { console.log(event); });
 * 
 * v1.0 - Full integration with UI Bridge endpoints
 */

class JAKALClient {
  constructor(baseURL = window.location.origin) {
    this.baseURL = baseURL.replace(/\/$/, ''); // Remove trailing slash
    this.apiBase = `${this.baseURL}/api`;
    this.cache = new Map();
    this.cacheTimeout = 60000; // 60 seconds
    this.eventSource = null;
    this.telemetryListeners = [];
    console.log(`[JAKALClient] Initialized with base URL: ${this.apiBase}`);
  }

  /**
   * Internal: Make HTTP request with error handling and retry logic
   */
  async _request(method, endpoint, data = null, options = {}) {
    const url = `${this.apiBase}${endpoint}`;
    const retries = options.retries || 3;
    let lastError;

    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        const config = {
          method,
          headers: {
            'Content-Type': 'application/json',
            ...options.headers,
          },
        };

        if (data && (method === 'POST' || method === 'PUT')) {
          config.body = JSON.stringify(data);
        }

        const response = await fetch(url, config);

        if (!response.ok) {
          const error = await response.text();
          throw new Error(`HTTP ${response.status}: ${error}`);
        }

        return await response.json();
      } catch (error) {
        lastError = error;
        console.warn(`[JAKALClient] Attempt ${attempt}/${retries} failed for ${endpoint}:`, error.message);
        if (attempt < retries) {
          const delay = Math.pow(2, attempt - 1) * 1000; // Exponential backoff
          await new Promise(resolve => setTimeout(resolve, delay));
        }
      }
    }

    console.error(`[JAKALClient] Request failed after ${retries} retries:`, lastError);
    throw lastError;
  }

  /**
   * Internal: Check and return cached response if available
   */
  _getCache(key) {
    const cached = this.cache.get(key);
    if (cached && Date.now() - cached.timestamp < this.cacheTimeout) {
      console.log(`[JAKALClient] Cache hit for ${key}`);
      return cached.data;
    }
    this.cache.delete(key);
    return null;
  }

  /**
   * Internal: Store response in cache
   */
  _setCache(key, data) {
    this.cache.set(key, { data, timestamp: Date.now() });
  }

  /**
   * Clear all cached data
   */
  clearCache() {
    console.log(`[JAKALClient] Clearing cache`);
    this.cache.clear();
  }

  // ========================================================================
  // DEVICE FLEET ENDPOINTS
  // ========================================================================

  /**
   * Get paginated device fleet with filters
   */
  async getDeviceFleet(filters = {}) {
    const cacheKey = `fleet-${JSON.stringify(filters)}`;
    const cached = this._getCache(cacheKey);
    if (cached) return cached;

    const query = new URLSearchParams({
      page: filters.page || 1,
      per_page: filters.per_page || 20,
      ...(filters.client && { client: filters.client }),
      ...(filters.status && { status: filters.status }),
    });

    const result = await this._request('GET', `/dashboard/fleet?${query}`);
    this._setCache(cacheKey, result);
    return result;
  }

  /**
   * Get single device details
   */
  async getDeviceDetails(deviceId) {
    const cacheKey = `device-${deviceId}`;
    const cached = this._getCache(cacheKey);
    if (cached) return cached;

    const result = await this._request('GET', `/dashboard/fleet/${deviceId}`);
    this._setCache(cacheKey, result);
    return result;
  }

  /**
   * Execute action on device (isolate, scan, reset_pass, quarantine, release)
   */
  async executeDeviceAction(deviceId, action, reason = null, operatorId = 'system') {
    const payload = {
      action,
      reason,
      operator_id: operatorId,
    };

    this.clearCache(); // Invalidate cache
    return this._request('POST', `/dashboard/fleet/${deviceId}/action`, payload);
  }

  // ========================================================================
  // GLOBAL MATRIX & THREATS
  // ========================================================================

  /**
   * Get global predictive threat matrix
   */
  async getGlobalMatrix(timeWindowMinutes = 60) {
    const cacheKey = `matrix-${timeWindowMinutes}`;
    const cached = this._getCache(cacheKey);
    if (cached) return cached;

    const result = await this._request('GET', `/dashboard/matrix?time_window_minutes=${timeWindowMinutes}`);
    this._setCache(cacheKey, result);
    return result;
  }

  // ========================================================================
  // DASHBOARD SETTINGS
  // ========================================================================

  /**
   * Get all global settings
   */
  async getGlobalSettings() {
    const cacheKey = 'settings-all';
    const cached = this._getCache(cacheKey);
    if (cached) return cached;

    const result = await this._request('GET', `/dashboard/settings`);
    this._setCache(cacheKey, result);
    return result;
  }

  // ========================================================================
  // UNIFIED SECURITY FABRIC
  // ========================================================================

  /**
   * Get unified security fabric posture (7-pillar Zero Trust model)
   */
  async getFabricStatus() {
    const cacheKey = 'fabric-status';
    const cached = this._getCache(cacheKey);
    if (cached) return cached;

    const result = await this._request('GET', `/dashboard/fabric/status`);
    this._setCache(cacheKey, result);
    return result;
  }

  // ========================================================================
  // SCRIPT CATALOG
  // ========================================================================

  /**
   * Get script library catalog with filters
   */
  async getScriptCatalog(filters = {}) {
    const cacheKey = `scripts-${JSON.stringify(filters)}`;
    const cached = this._getCache(cacheKey);
    if (cached) return cached;

    const query = new URLSearchParams({
      page: filters.page || 1,
      per_page: filters.per_page || 20,
      ...(filters.category && { category: filters.category }),
    });

    const result = await this._request('GET', `/dashboard/scripts/catalog?${query}`);
    this._setCache(cacheKey, result);
    return result;
  }

  // ========================================================================
  // RESONANCE POLICIES
  // ========================================================================

  /**
   * Get all automation policies
   */
  async getResonancePolicies() {
    const cacheKey = 'policies-all';
    const cached = this._getCache(cacheKey);
    if (cached) return cached;

    const result = await this._request('GET', `/dashboard/resonance/policies`);
    this._setCache(cacheKey, result);
    return result;
  }

  /**
   * Create new policy
   */
  async createResonancePolicy(policyData) {
    this.clearCache(); // Invalidate cache
    return this._request('POST', `/dashboard/resonance/policies`, policyData);
  }

  /**
   * Get recent agent activity log (dashboard view over agent_logs -- NOT
   * the tamper-evident, hash-chained audit trail; that one is
   * GET /api/resonance/audit, served by routers/resonance.py +
   * core/audit_logger.py, for the real audited enforcement workflow).
   */
  async getResonanceAudit(filters = {}) {
    const query = new URLSearchParams({
      limit: filters.limit || 50,
      offset: filters.offset || 0,
      ...(filters.eventType && { event_type: filters.eventType }),
    });

    return this._request('GET', `/dashboard/resonance/audit?${query}`);
  }

  // ========================================================================
  // HEALTH & METRICS
  // ========================================================================

  /**
   * Get detailed system health
   */
  async getDetailedHealth() {
    const cacheKey = 'health-detailed';
    const cached = this._getCache(cacheKey);
    if (cached) return cached;

    const result = await this._request('GET', `/health/detailed`);
    this._setCache(cacheKey, result);
    return result;
  }

  // ========================================================================
  // SERVER-SENT EVENTS (SSE) STREAMING
  // ========================================================================

  /**
   * Connect to real-time telemetry stream
   * Calls onEvent(event) whenever a new event arrives
   */
  connectTelemetry(onEvent, onError = null) {
    if (this.eventSource) {
      this.eventSource.close();
    }

    try {
      console.log(`[JAKALClient] Connecting to telemetry stream...`);
      this.eventSource = new EventSource(`${this.apiBase}/telemetry/stream`);

      this.eventSource.addEventListener('message', (event) => {
        try {
          const data = JSON.parse(event.data);
          onEvent(data);
          // Notify all registered listeners
          this.telemetryListeners.forEach(listener => listener(data));
        } catch (error) {
          console.error('[JAKALClient] Error parsing telemetry event:', error);
        }
      });

      this.eventSource.addEventListener('error', (error) => {
        console.error('[JAKALClient] Telemetry stream error:', error);
        if (onError) onError(error);
        // Attempt to reconnect after 5 seconds
        setTimeout(() => this.connectTelemetry(onEvent, onError), 5000);
      });
    } catch (error) {
      console.error('[JAKALClient] Error connecting to telemetry stream:', error);
      if (onError) onError(error);
    }
  }

  /**
   * Register a listener for telemetry events
   */
  onTelemetry(callback) {
    this.telemetryListeners.push(callback);
    return () => {
      this.telemetryListeners = this.telemetryListeners.filter(l => l !== callback);
    };
  }

  /**
   * Disconnect from telemetry stream
   */
  disconnectTelemetry() {
    console.log(`[JAKALClient] Disconnecting from telemetry stream`);
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }

  /**
   * Check if telemetry is connected
   */
  isTelemetryConnected() {
    return this.eventSource && this.eventSource.readyState === EventSource.OPEN;
  }
}

// Export for use in global scope
window.JAKALClient = JAKALClient;
console.log('[JAKALClient] Loaded successfully');
