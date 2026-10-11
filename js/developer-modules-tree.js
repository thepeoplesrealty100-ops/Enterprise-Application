/**
 * TIER 1.4: Developer Settings Collapsible Tree Structure
 * 
 * Reorganizes 10 heavy JAKAL modules into expandable/collapsible tree
 * inside Global Dashboard > Settings & Security > Developer tab
 * 
 * Modules organized by functional area:
 * - Computational/Agentic (Energy Core, Q'AIP, Quantum, Inference)
 * - Orchestration (Resonance, Cheatsheet, Load Monitor)
 * - Command & Control (Predictive, Agentic Canvas)
 */

window.JAKAL_DEVELOPER_MODULES = {
  // Category 1: Computational & Agentic Systems
  computational_systems: {
    label: '⚙️ Computational Systems',
    icon: 'cpu',
    modules: [
      { id: 'energy_core', name: 'Energy Core Management', icon: 'battery-charging', endpoint: '/api/energy/status', status_indicator: true },
      { id: 'qaip_core', name: 'Q\'AIP Logic Core', icon: 'brain', endpoint: '/api/qaip/status', status_indicator: true },
      { id: 'quantum_orbital', name: 'Quantum Orbital Events', icon: 'atom', endpoint: '/api/quantum/status', status_indicator: true },
      { id: 'model_chains', name: 'Model Chains & Inference', icon: 'link-2', endpoint: '/api/inference/chains', status_indicator: false },
    ]
  },
  
  // Category 2: Orchestration & Automation
  orchestration: {
    label: '🎛️ Orchestration & Automation',
    icon: 'zap',
    modules: [
      { id: 'resonance_wave', name: 'Resonance Wave Automation', icon: 'radio', endpoint: '/api/resonance/status', status_indicator: true },
      { id: 'cheatsheet_lib', name: 'Cheatsheet Library', icon: 'book-open', endpoint: '/api/cheatsheet/library', status_indicator: false },
      { id: 'resonance_monitor', name: 'Resonance Load Monitor', icon: 'gauge', endpoint: '/api/resonance/load', status_indicator: true },
    ]
  },

  // Category 3: Command & Control
  command_control: {
    label: '🎮 Command & Control',
    icon: 'gamepad-2',
    modules: [
      { id: 'predictive_cmd', name: 'Predictive Command', icon: 'zap-off', endpoint: '/api/predict/commands', status_indicator: false },
      { id: 'agentic_canvas', name: 'Agentic Canvas', icon: 'palette', endpoint: '/api/canvas/agents', status_indicator: true },
    ]
  }
};

/**
 * Render collapsible tree for Developer Modules
 * Used in Global Dashboard > Settings & Security > Developer tab
 */
function renderDeveloperModulesTree() {
  let html = `
    <div class="dev-modules-tree space-y-2 mt-4">
      <p class="text-xs text-gray-500 mb-3">🔧 Advanced JAKAL Modules (Click to expand/collapse)</p>
  `;

  Object.entries(window.JAKAL_DEVELOPER_MODULES).forEach(([categoryKey, category]) => {
    const treeId = `tree-${categoryKey}`;
    const expanded = localStorage.getItem(`dev-tree-${categoryKey}`) !== 'collapsed';
    
    html += `
      <div class="dev-module-category">
        <!-- Collapsible Header -->
        <button onclick="window.toggleDevModuleTree('${categoryKey}')" 
                class="w-full flex items-center justify-between py-2 px-3 rounded-md hover:bg-gray-800/40 transition">
          <div class="flex items-center gap-2">
            <span class="text-lg">${expanded ? '▼' : '▶'}</span>
            <i data-lucide="${category.icon}" class="w-4 h-4 text-primary-color"></i>
            <span class="text-sm font-medium text-gray-300">${category.label}</span>
            <span class="text-xs text-gray-600">(${category.modules.length})</span>
          </div>
          <span class="text-xs bg-gray-800/60 px-2 py-1 rounded text-gray-400">Developer Only</span>
        </button>

        <!-- Expandable Module List -->
        <div id="${treeId}" class="tree-content overflow-hidden transition-all duration-200" 
             style="max-height: ${expanded ? '500px' : '0px'}; opacity: ${expanded ? '1' : '0'};">
          <div class="ml-6 mt-1 space-y-1 border-l border-gray-800/40 pl-3">
    `;

    category.modules.forEach((module, idx) => {
      const statusClass = module.status_indicator ? 'has-status' : '';
      html += `
        <div class="dev-module-item py-2 px-2 rounded hover:bg-gray-800/30 cursor-pointer transition"
             onclick="window.openDevModule('${module.id}', '${module.endpoint}')">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <i data-lucide="${module.icon}" class="w-3 h-3 text-gray-500"></i>
              <span class="text-xs font-medium text-gray-300">${module.name}</span>
            </div>
            ${module.status_indicator ? `<span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>` : `<span class="text-xs text-gray-700">→</span>`}
          </div>
        </div>
      `;
    });

    html += `
          </div>
        </div>
      </div>
    `;
  });

  html += `
    </div>
    <style>
      .dev-module-category { }
      .dev-module-item { border-radius: 0.375rem; }
      .dev-modules-tree .tree-content {
        max-height: 0;
        overflow: hidden;
      }
    </style>
  `;

  return html;
}

/**
 * Toggle a category's expanded/collapsed state
 */
window.toggleDevModuleTree = function(categoryKey) {
  const treeId = `tree-${categoryKey}`;
  const el = document.getElementById(treeId);
  const isExpanded = el.style.maxHeight !== '0px';
  
  if (isExpanded) {
    el.style.maxHeight = '0px';
    el.style.opacity = '0';
    localStorage.setItem(`dev-tree-${categoryKey}`, 'collapsed');
  } else {
    el.style.maxHeight = '500px';
    el.style.opacity = '1';
    localStorage.removeItem(`dev-tree-${categoryKey}`);
  }
};

/**
 * Open a developer module (navigate to its page or show details)
 */
window.openDevModule = function(moduleId, endpoint) {
  console.log(`Opening developer module: ${moduleId} (endpoint: ${endpoint})`);
  
  // Check if we have a page for this module
  const modulePageMap = {
    'energy_core': 'admin_energy_core',
    'qaip_core': 'admin_logic_core',
    'quantum_orbital': 'admin_quantum_nexus',
    'model_chains': 'admin_quantum_computer',
    'resonance_wave': 'admin_automation_controls',
    'cheatsheet_lib': 'admin_cheatsheet',
    'resonance_monitor': 'admin_cognitive_load_monitor',
    'predictive_cmd': 'admin_predictive_command',
    'agentic_canvas': 'admin_agentic_canvas'
  };

  const pageKey = modulePageMap[moduleId];
  if (pageKey && window.loadPage) {
    window.loadPage(pageKey);
  } else {
    // Fallback: show module details in a modal
    window.showAppModal(`${moduleId.toUpperCase()}`, 
      `<div class="text-sm text-gray-300">
        <p>Module: ${moduleId}</p>
        <p class="text-xs text-gray-500 mt-2">Endpoint: <code class="bg-gray-900/60 px-1 py-0.5 rounded">${endpoint}</code></p>
        <p class="text-xs text-gray-500 mt-2">Status: Loading...</p>
      </div>`,
      { width: 500 }
    );
    
    // Try to fetch real status from endpoint
    if (endpoint) {
      fetch(endpoint, { credentials: 'include' })
        .then(r => r.json())
        .then(data => {
          console.log(`${moduleId} status:`, data);
        })
        .catch(e => console.error(`Failed to fetch ${moduleId}:`, e));
    }
  }
};

/**
 * Initialize developer modules tree on page load
 * Call this from renderDeveloperSettingsTab()
 */
window.initDeveloperModulesTree = function() {
  // Attach lucide icons to the tree
  setTimeout(() => {
    const icons = document.querySelectorAll('[data-lucide]');
    if (window.lucide) {
      icons.forEach(el => window.lucide.createIcons());
    }
  }, 100);
};
