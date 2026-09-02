/**
 * JAKAL v4.0 - Advanced VR Military Command Center Console
 * React/Vue component for advanced helmet with remote capabilities
 * Military-grade 3D threat visualization
 * Neural-integrated decision augmentation
 */

<template>
  <div class="vr-command-center-container">
    <!-- VR HELMET HEADER -->
    <header class="vr-header">
      <div class="helmet-status">
        <div class="status-indicator" :class="{
          'status-healthy': helmetStatus.battery > 50,
          'status-warning': helmetStatus.battery <= 50 && helmetStatus.battery > 20,
          'status-critical': helmetStatus.battery <= 20
        }">
          <span class="status-dot"></span>
          <span class="status-text">{{ helmetStatus.operational ? 'OPERATIONAL' : 'STANDBY' }}</span>
        </div>
        
        <div class="helmet-metrics">
          <div class="metric">
            <label>BATTERY</label>
            <value class="metric-value">{{ helmetStatus.battery }}%</value>
          </div>
          <div class="metric">
            <label>LATENCY</label>
            <value class="metric-value">{{ helmetStatus.latency }}ms</value>
          </div>
          <div class="metric">
            <label>SIGNAL</label>
            <value class="metric-value">{{ helmetStatus.signal }}/100</value>
          </div>
          <div class="metric">
            <label>STREAMS</label>
            <value class="metric-value">{{ helmetStatus.activeStreams }}/8</value>
          </div>
        </div>
      </div>
    </header>

    <!-- 3D THREAT VISUALIZATION (MAIN VIEWPORT) -->
    <section class="vr-3d-viewport">
      <div class="viewport-3d" ref="threeDViewport">
        <!-- Three.js/Babylon.js 3D scene rendered here -->
        <div class="viewport-info">
          <h2>3D THREAT SPACE</h2>
          <div class="threat-objects">
            <div v-for="threat in threats3D" :key="threat.id" 
                 class="threat-object"
                 :class="`threat-level-${threat.level}`"
                 @click="selectThreat(threat)">
              <div class="threat-marker" :style="{
                left: threat.x + '%',
                top: threat.y + '%'
              }"></div>
              <div class="threat-label">{{ threat.name }}</div>
              <div class="threat-level-display">{{ threat.level }}/100</div>
            </div>
          </div>
        </div>
      </div>

      <!-- MULTI-STREAM VIDEO GRID (PICTURE-IN-PICTURE) -->
      <div class="video-grid">
        <div class="video-tile primary">
          <video ref="primaryVideo" autoplay playsinline></video>
          <div class="video-overlay">
            <span class="stream-label">DRONE PRIMARY</span>
            <span class="latency">18ms</span>
          </div>
        </div>
        
        <div class="video-tile secondary">
          <video ref="thermalVideo" autoplay playsinline></video>
          <div class="video-overlay">
            <span class="stream-label">THERMAL</span>
            <span class="latency">22ms</span>
          </div>
        </div>
        
        <div class="video-tile secondary">
          <video ref="satelliteVideo" autoplay playsinline></video>
          <div class="video-overlay">
            <span class="stream-label">SATELLITE</span>
            <span class="latency">45ms</span>
          </div>
        </div>
        
        <div class="video-tile secondary">
          <video ref="overheadVideo" autoplay playsinline></video>
          <div class="video-overlay">
            <span class="stream-label">OVERHEAD</span>
            <span class="latency">25ms</span>
          </div>
        </div>
      </div>
    </section>

    <!-- THREAT ANALYSIS PANEL (SELECTED THREAT) -->
    <section v-if="selectedThreat" class="threat-analysis-panel">
      <h3>THREAT ANALYSIS: {{ selectedThreat.name }}</h3>
      
      <div class="analysis-grid">
        <!-- Threat Details -->
        <div class="analysis-card threat-details">
          <h4>THREAT DETAILS</h4>
          <div class="detail-item">
            <label>Type:</label>
            <value>{{ selectedThreat.type }}</value>
          </div>
          <div class="detail-item">
            <label>Threat Level:</label>
            <value class="threat-critical">{{ selectedThreat.level }}/100</value>
          </div>
          <div class="detail-item">
            <label>Units/Size:</label>
            <value>{{ selectedThreat.size }}</value>
          </div>
          <div class="detail-item">
            <label>Velocity:</label>
            <value>{{ selectedThreat.velocity }} m/s</value>
          </div>
          <div class="detail-item">
            <label>ETA to Critical Asset:</label>
            <value class="time-critical">{{ selectedThreat.eta }} minutes</value>
          </div>
        </div>

        <!-- AI RECOMMENDATIONS -->
        <div class="analysis-card ai-recommendations">
          <h4>AI RECOMMENDATIONS</h4>
          <div class="recommendation-priority">
            <span class="priority-badge critical">CRITICAL</span>
            <p>{{ aiRecommendations[0].text }}</p>
            <span class="confidence">Confidence: {{ aiRecommendations[0].confidence * 100 }}%</span>
          </div>
          <div v-for="(rec, idx) in aiRecommendations.slice(1)" :key="idx"
               class="recommendation-item">
            <span class="priority-badge" :class="rec.priority">{{ rec.priority }}</span>
            <p>{{ rec.text }}</p>
            <span class="confidence">{{ rec.confidence * 100 }}%</span>
          </div>
        </div>

        <!-- DECISION AUGMENTATION -->
        <div class="analysis-card decision-augmentation">
          <h4>DECISION AUGMENTATION</h4>
          <div class="decision-option selected">
            <input type="radio" name="decision" value="option1" v-model="selectedDecision" />
            <label>Deploy Defensive Swarm (Recommended)</label>
            <div class="option-metrics">
              <span class="metric">Success: 94%</span>
              <span class="metric">Resources: Heavy</span>
              <span class="metric">Risk: Low</span>
            </div>
          </div>
          <div class="decision-option">
            <input type="radio" name="decision" value="option2" v-model="selectedDecision" />
            <label>Activate Network Defense</label>
            <div class="option-metrics">
              <span class="metric">Success: 87%</span>
              <span class="metric">Resources: Moderate</span>
              <span class="metric">Risk: Medium</span>
            </div>
          </div>
          <div class="decision-option">
            <input type="radio" name="decision" value="option3" v-model="selectedDecision" />
            <label>Escalate to Government Command</label>
            <div class="option-metrics">
              <span class="metric">Success: 99%</span>
              <span class="metric">Resources: Low</span>
              <span class="metric">Risk: High</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- NEURAL INTEGRATION & BIOMETRIC FEEDBACK -->
    <section class="neural-feedback-panel">
      <div class="biometric-display">
        <h4>NEURAL INTEGRATION STATUS</h4>
        <div class="biometric-metric">
          <label>COGNITIVE LOAD</label>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: neuralStatus.cognitiveLoad + '%' }"></div>
          </div>
          <span>{{ neuralStatus.cognitiveLoad }}%</span>
        </div>
        <div class="biometric-metric">
          <label>ATTENTION LEVEL</label>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: neuralStatus.attention + '%' }"></div>
          </div>
          <span>{{ neuralStatus.attention }}%</span>
        </div>
        <div class="biometric-metric">
          <label>STRESS LEVEL</label>
          <div class="progress-bar" :class="{ stressed: neuralStatus.stress > 60 }">
            <div class="progress-fill" :style="{ width: neuralStatus.stress + '%' }"></div>
          </div>
          <span>{{ neuralStatus.stress }}%</span>
        </div>
      </div>
    </section>

    <!-- COMMAND EXECUTION (ENCRYPTED) -->
    <section class="command-execution-panel">
      <h3>COMMAND EXECUTION</h3>
      <button v-if="selectedDecision" 
              @click="executeEncryptedCommand"
              class="command-button execute-button"
              :disabled="commandExecuting">
        <span v-if="!commandExecuting">EXECUTE (ML-DSA-65 Encrypted)</span>
        <span v-else>EXECUTING...</span>
      </button>
      
      <div v-if="commandStatus" class="command-status">
        <h4>COMMAND STATUS</h4>
        <div class="status-item">
          <label>Encryption:</label>
          <value class="status-success">{{ commandStatus.encryption }}</value>
        </div>
        <div class="status-item">
          <label>Acknowledgments:</label>
          <div class="acknowledgment-list">
            <span v-for="(ack, name) in commandStatus.acks" :key="name"
                  class="ack-badge">
              {{ name }}: {{ ack }}
            </span>
          </div>
        </div>
        <div class="status-item">
          <label>Execution Progress:</label>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: commandStatus.progress + '%' }"></div>
          </div>
          <span>{{ commandStatus.progress }}%</span>
        </div>
      </div>
    </section>

    <!-- REMOTE DRONE/ROBOT CONTROL -->
    <section class="remote-control-panel">
      <h3>REMOTE PLATFORM CONTROL</h3>
      <div class="platform-controls">
        <div class="platform-selector">
          <button v-for="platform in remotePlatforms" :key="platform.id"
                  @click="selectPlatform(platform)"
                  :class="{ active: selectedPlatform?.id === platform.id }"
                  class="platform-button">
            {{ platform.name }} ({{ platform.latency }}ms)
          </button>
        </div>

        <div v-if="selectedPlatform" class="control-interface">
          <div class="control-joystick">
            <div class="joystick-base">
              <div class="joystick-stick" 
                   @mousedown="startJoystickDrag"
                   @touchstart="startJoystickDrag"></div>
            </div>
          </div>

          <div class="platform-video-feed">
            <video ref="platformVideo" autoplay playsinline></video>
            <div class="platform-overlay">
              <span>{{ selectedPlatform.name }} Feed</span>
              <span class="latency">{{ selectedPlatform.latency }}ms</span>
            </div>
          </div>

          <div class="haptic-feedback-indicator">
            <div class="haptic-dot" :class="{ active: hapticFeedback }"></div>
            <span>Haptic Feedback {{ hapticFeedback ? 'ON' : 'OFF' }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- REAL-TIME COMMAND LOG -->
    <section class="command-log-panel">
      <h3>REAL-TIME COMMAND LOG</h3>
      <div class="command-log">
        <div v-for="(log, idx) in commandLogs.slice(-10)" :key="idx"
             class="log-entry"
             :class="log.type">
          <span class="log-timestamp">{{ log.timestamp }}</span>
          <span class="log-message">{{ log.message }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<script>
export default {
  name: 'VRCommandCenter',
  data() {
    return {
      helmetStatus: {
        operational: true,
        battery: 87,
        latency: 23,
        signal: 94,
        activeStreams: 4
      },
      threats3D: [
        { id: 1, name: 'Drone Swarm', x: 60, y: 40, level: 78, type: 'autonomous_swarm', size: 4823, velocity: 5.2, eta: 8 },
        { id: 2, name: 'Network Intrusion', x: 20, y: 55, level: 62, type: 'c2_connection', size: 'Unknown', velocity: 0, eta: 'immediate' },
        { id: 3, name: 'Sensor Anomaly', x: 75, y: 65, level: 41, type: 'anomaly', size: 'Single', velocity: 0, eta: 'investigation' }
      ],
      selectedThreat: null,
      aiRecommendations: [
        { text: 'Deploy 5000-unit defensive nanoswarm. ETA 30 seconds.', confidence: 0.94, priority: 'CRITICAL' },
        { text: 'Activate emergency network isolation protocols', confidence: 0.87, priority: 'HIGH' },
        { text: 'Alert government defense coordination center', confidence: 0.91, priority: 'HIGH' }
      ],
      selectedDecision: null,
      neuralStatus: {
        cognitiveLoad: 63,
        attention: 94,
        stress: 42
      },
      commandExecuting: false,
      commandStatus: null,
      remotePlatforms: [
        { id: 1, name: 'Drone Swarm', latency: 45, type: 'drone' },
        { id: 2, name: 'Ground Robot', latency: 18, type: 'robot' },
        { id: 3, name: 'Sensor Network', latency: 12, type: 'sensor' }
      ],
      selectedPlatform: null,
      hapticFeedback: true,
      commandLogs: [
        { timestamp: '14:23:45', message: '[THREAT DETECTED] Autonomous swarm at perimeter', type: 'warning' },
        { timestamp: '14:23:46', message: '[ANALYSIS] Threat level elevated to 78/100', type: 'alert' },
        { timestamp: '14:23:47', message: '[AI] Recommended response: Deploy defensive swarm', type: 'info' }
      ]
    }
  },
  methods: {
    selectThreat(threat) {
      this.selectedThreat = threat;
    },
    selectPlatform(platform) {
      this.selectedPlatform = platform;
    },
    startJoystickDrag(event) {
      // Handle joystick drag
    },
    async executeEncryptedCommand() {
      this.commandExecuting = true;
      this.commandStatus = {
        encryption: 'ML-DSA-65_AES_256_GCM',
        acks: {
          'Swarm Network': 'received',
          'Defense Grid': 'received',
          'Satellite Relay': 'received'
        },
        progress: 0
      };

      // Simulate command execution
      for (let i = 0; i <= 100; i += 10) {
        this.commandStatus.progress = i;
        await new Promise(resolve => setTimeout(resolve, 500));
      }

      this.commandExecuting = false;
      this.commandLogs.push({
        timestamp: new Date().toLocaleTimeString(),
        message: `[COMMAND] Executed: ${this.selectedDecision}`,
        type: 'success'
      });
    }
  }
}
</script>

<style scoped>
.vr-command-center-container {
  display: grid;
  grid-template-columns: 1fr;
  grid-template-rows: 80px 1fr 120px 150px 200px 100px;
  height: 100vh;
  background: #0a0e27;
  color: #00ff88;
  font-family: 'Courier New', monospace;
  overflow: hidden;
  gap: 4px;
}

.vr-header {
  background: linear-gradient(135deg, #1a2a4a 0%, #0f1620 100%);
  border-bottom: 2px solid #00ff88;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.helmet-status, .helmet-metrics {
  display: flex;
  gap: 20px;
  align-items: center;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: bold;
  font-size: 14px;
}

.status-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #00ff88;
  box-shadow: 0 0 8px #00ff88;
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.status-healthy .status-dot {
  background: #00ff88;
  box-shadow: 0 0 8px #00ff88;
}

.status-warning .status-dot {
  background: #ffaa00;
  box-shadow: 0 0 8px #ffaa00;
}

.status-critical .status-dot {
  background: #ff2020;
  box-shadow: 0 0 8px #ff2020;
}

.metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 80px;
}

.metric label {
  font-size: 10px;
  opacity: 0.7;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.metric-value {
  font-size: 16px;
  font-weight: bold;
  color: #00ff88;
}

.vr-3d-viewport {
  grid-row: 2;
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: 4px;
  padding: 4px;
}

.viewport-3d {
  background: #0f1620;
  border: 1px solid #00ff88;
  position: relative;
  overflow: hidden;
}

.threat-object {
  position: absolute;
  cursor: pointer;
  transition: all 0.3s;
}

.threat-object:hover {
  transform: scale(1.2);
}

.threat-marker {
  width: 20px;
  height: 20px;
  border: 2px solid #00ff88;
  border-radius: 50%;
  position: absolute;
}

.threat-level-1 .threat-marker,
.threat-level-2 .threat-marker {
  border-color: #ffaa00;
  box-shadow: 0 0 10px #ffaa00;
}

.threat-level-3 .threat-marker {
  border-color: #ff2020;
  box-shadow: 0 0 10px #ff2020;
}

.video-grid {
  display: grid;
  grid-template-rows: repeat(2, 1fr);
  gap: 2px;
}

.video-tile {
  background: #000;
  border: 1px solid #00ff88;
  position: relative;
  overflow: hidden;
}

.video-tile.primary {
  grid-row: 1 / 3;
  grid-column: 1;
}

.video-tile video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.video-overlay {
  position: absolute;
  top: 4px;
  left: 4px;
  background: rgba(0, 0, 0, 0.7);
  padding: 4px 8px;
  font-size: 10px;
  border: 1px solid #00ff88;
  display: flex;
  gap: 8px;
}

.threat-analysis-panel,
.neural-feedback-panel,
.command-execution-panel,
.remote-control-panel,
.command-log-panel {
  background: #0f1620;
  border: 1px solid #00ff88;
  padding: 8px 12px;
  overflow-y: auto;
  font-size: 11px;
}

.analysis-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  margin-top: 4px;
}

.analysis-card {
  background: rgba(0, 255, 136, 0.05);
  border: 1px solid #00ff88;
  padding: 6px;
  overflow-y: auto;
}

.detail-item {
  display: flex;
  justify-content: space-between;
  padding: 2px 0;
  border-bottom: 1px solid rgba(0, 255, 136, 0.2);
}

.threat-critical {
  color: #ff2020;
  font-weight: bold;
}

.command-button {
  padding: 8px 16px;
  background: #00ff88;
  color: #0a0e27;
  border: none;
  border-radius: 2px;
  cursor: pointer;
  font-weight: bold;
  font-family: 'Courier New', monospace;
  transition: all 0.3s;
}

.command-button:hover:not(:disabled) {
  box-shadow: 0 0 12px #00ff88;
  transform: scale(1.05);
}

.command-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.progress-bar {
  width: 100%;
  height: 8px;
  background: rgba(0, 255, 136, 0.1);
  border: 1px solid #00ff88;
  position: relative;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #00ff88, #00aa44);
  transition: width 0.3s;
  box-shadow: 0 0 8px #00ff88;
}

.log-entry {
  padding: 2px 4px;
  border-bottom: 1px solid rgba(0, 255, 136, 0.1);
  display: flex;
  gap: 8px;
}

.log-timestamp {
  color: #00aa44;
  min-width: 60px;
}

.log-entry.warning {
  color: #ffaa00;
}

.log-entry.alert {
  color: #ff2020;
}

.log-entry.success {
  color: #00ff88;
}

/* Responsive adjustments */
@media (max-width: 1024px) {
  .vr-command-center-container {
    grid-template-rows: 60px 1fr 100px 120px 150px 80px;
  }
  
  .analysis-grid {
    grid-template-columns: 1fr;
  }
}
</style>
