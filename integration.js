/**
 * integration.js - JAKAL Frontend-Backend Real-Time Integration
 * 
 * Handles:
 * - Real-time data fetching from backend REST APIs
 * - Server-Sent Events (SSE) telemetry streaming
 * - Error handling and graceful degradation for GitHub Pages demo
 * - Dashboard auto-refresh and component updates
 */

const API_BASE = (() => {
    // On GitHub Pages or without backend: use demo mode
    if (window.location.hostname === 'thepeoplesrealty100-ops.github.io' ||
        window.location.hostname === 'localhost:3000') {
        return null; // Demo mode
    }
    return `http://${window.location.hostname}:8000`;
})();

const DEMO_MODE = API_BASE === null;
const API_TIMEOUT = 5000;

export class JAKALIntegrationClient {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
        this.cache = new Map();
        this.cacheTTL = 60000; // 60 seconds
        this.eventSource = null;
    }

    async fetchJSON(endpoint, options = {}) {
        if (DEMO_MODE) {
            return this._generateDemoData(endpoint);
        }

        const url = `${this.baseUrl}${endpoint}`;
        const cacheKey = `${endpoint}_${JSON.stringify(options)}`;
        
        // Check cache
        if (this.cache.has(cacheKey)) {
            const { data, timestamp } = this.cache.get(cacheKey);
            if (Date.now() - timestamp < this.cacheTTL) {
                return data;
            }
        }

        try {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), API_TIMEOUT);

            const response = await fetch(url, {
                method: options.method || 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                },
                body: options.body ? JSON.stringify(options.body) : undefined,
                signal: controller.signal
            });

            clearTimeout(timeout);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            
            // Cache successful response
            this.cache.set(cacheKey, {
                data,
                timestamp: Date.now()
            });

            return data;
        } catch (error) {
            console.error(`API Error [${endpoint}]:`, error.message);
            
            // Fallback to demo data on error
            if (error.name !== 'AbortError') {
                return this._generateDemoData(endpoint);
            }
            
            throw error;
        }
    }

    connectTelemetryStream(onMessage, onError) {
        if (DEMO_MODE) {
            return this._simulateTelemetryStream(onMessage);
        }

        try {
            this.eventSource = new EventSource(`${this.baseUrl}/api/telemetry/stream`);

            this.eventSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    onMessage(data);
                } catch (e) {
                    console.error('Telemetry parse error:', e);
                }
            };

            this.eventSource.onerror = (error) => {
                console.error('Telemetry stream error:', error);
                if (onError) onError(error);
                this.eventSource.close();
                
                // Attempt reconnect after 5 seconds
                setTimeout(() => this.connectTelemetryStream(onMessage, onError), 5000);
            };

            return () => this.eventSource?.close();
        } catch (error) {
            console.error('Telemetry connection error:', error);
            if (onError) onError(error);
            return () => {};
        }
    }

    _generateDemoData(endpoint) {
        // Demo data generation for offline/GitHub Pages usage
        const demoResponses = {
            '/api/dashboard/fleet': {
                data: [
                    { id: 'dev-001', name: 'Workstation-Alpha', ip: '192.168.1.10', status: 'online', threat_level: 'LOW' },
                    { id: 'dev-002', name: 'Server-Beta', ip: '192.168.1.20', status: 'online', threat_level: 'MEDIUM' },
                    { id: 'dev-003', name: 'Laptop-Gamma', ip: '192.168.1.30', status: 'offline', threat_level: 'LOW' }
                ],
                pagination: { page: 1, per_page: 20, total: 3, pages: 1 },
                timestamp: new Date().toISOString()
            },
            '/api/dashboard/matrix': {
                matrix: {
                    'CRITICAL': 2,
                    'HIGH': 5,
                    'MEDIUM': 12,
                    'LOW': 34
                },
                time_window_minutes: 60,
                timestamp: new Date().toISOString()
            },
            '/api/fabric/status': {
                overall_score: 87,
                overall_level: 'SECURE',
                by_pillar: {
                    'identity': 92,
                    'devices': 85,
                    'network': 88,
                    'applications': 82,
                    'data': 90,
                    'infrastructure': 86,
                    'automation': 79
                },
                timestamp: new Date().toISOString()
            },
            '/api/health/detailed': {
                status: 'operational',
                timestamp: new Date().toISOString(),
                version: '3.0.0',
                components: {
                    database: { status: 'healthy', tables: 25 },
                    cache: { status: 'operational', ttl_seconds: 60 },
                    security_agents: { vm_orchestrator: 'operational', compliance_axiom: 'operational' }
                }
            },
            '/api/resonance/policies': {
                policies: [
                    { id: 'pol-001', name: 'Auto-Isolate Critical Threats', enabled: true },
                    { id: 'pol-002', name: 'Daily Compliance Check', enabled: true }
                ],
                timestamp: new Date().toISOString()
            }
        };

        return demoResponses[endpoint] || { error: 'Endpoint not found in demo mode' };
    }

    _simulateTelemetryStream(onMessage) {
        let messageCount = 0;
        const interval = setInterval(() => {
            const events = [
                { message: 'Agent health check passed', type: 'success' },
                { message: 'Threat scanning completed', type: 'info' },
                { message: 'Policy update deployed', type: 'success' },
                { message: 'Compliance check: PASSED', type: 'success' }
            ];
            
            const event = events[messageCount % events.length];
            onMessage({
                message: event.message,
                timestamp: new Date().toISOString(),
                level_color: event.type === 'success' ? 'text-green-400' : 'text-blue-400'
            });

            messageCount++;
        }, 5000);

        return () => clearInterval(interval);
    }

    clearCache() {
        this.cache.clear();
    }
}

// Initialize and export global integration
export async function startIntegration() {
    window.jakalClient = new JAKALIntegrationClient(API_BASE);

    if (!DEMO_MODE) {
        console.log(`[JAKAL Integration] Connected to backend at ${API_BASE}`);
    } else {
        console.log('[JAKAL Integration] Running in DEMO mode (no backend detected)');
    }

    // Auto-load initial data
    try {
        const health = await window.jakalClient.fetchJSON('/api/health/detailed');
        console.log('[JAKAL] Backend health:', health);
    } catch (error) {
        console.warn('[JAKAL] Backend unavailable, using demo data');
    }

    // Start telemetry stream
    let unsubscribe = window.jakalClient.connectTelemetryStream(
        (event) => {
            console.log('[JAKAL Telemetry]', event.message);
            // Trigger dashboard updates here
            if (window.onTelemetryEvent) {
                window.onTelemetryEvent(event);
            }
        },
        (error) => {
            console.error('[JAKAL Telemetry] Error:', error);
        }
    );

    // Cleanup on page unload
    window.addEventListener('beforeunload', () => {
        unsubscribe?.();
    });
}

// Export client class for direct use
export { JAKALIntegrationClient };
