/**
 * frontend/src/components/ResponseConsole.jsx
 * Integrated response & remediation console.
 * Combines compliance validation, attack-path analysis, and multi-target containment.
 */

import React, { useState, useEffect } from 'react';
import ComplianceBadgeGroup from './ComplianceBadgeGroup';
import AttackPathCanvas from './AttackPathCanvas';

const ResponseConsole = () => {
  const [primaryTarget, setPrimaryTarget] = useState('');
  const [actionType, setActionType] = useState('isolate_host_staged');
  const [detail, setDetail] = useState('');
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const actionTypes = [
    { value: 'isolate_host_staged', label: 'Isolate Host (Staged)' },
    { value: 'quarantine_host_staged', label: 'Quarantine Host (Staged)' },
    { value: 'disable_account_staged', label: 'Disable Account (Staged)' },
    { value: 'ioc_block', label: 'Block IOC' },
  ];

  const handleExecuteAction = async () => {
    if (!primaryTarget) {
      setError('Please enter a target');
      return;
    }

    setExecuting(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch('/api/response/enforce', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action_type: actionType,
          target: primaryTarget,
          detail: { reason: detail || 'Manual enforcement via console' },
          operator_id: 'console_user',
        }),
      });

      const data = await response.json();
      if (response.ok) {
        setResult(data);
      } else {
        setError(data.detail || 'Enforcement failed');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div className="space-y-6 p-6 bg-gray-900 min-h-screen">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-white mb-2">Response & Remediation Console</h1>
          <p className="text-gray-400">Execute containment actions with compliance validation and attack-path awareness</p>
        </div>

        {/* Primary Target Input */}
        <div className="space-y-4 p-6 bg-gray-800 rounded-lg border border-gray-700 mb-6">
          <div>
            <label className="block text-sm font-semibold text-gray-300 mb-2">Primary Target</label>
            <input
              type="text"
              value={primaryTarget}
              onChange={(e) => setPrimaryTarget(e.target.value)}
              placeholder="e.g., 192.168.1.1 or hostname"
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-semibold text-gray-300 mb-2">Action Type</label>
            <select
              value={actionType}
              onChange={(e) => setActionType(e.target.value)}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-white focus:outline-none focus:border-blue-500"
            >
              {actionTypes.map((at) => (
                <option key={at.value} value={at.value}>
                  {at.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-semibold text-gray-300 mb-2">Details (Optional)</label>
            <textarea
              value={detail}
              onChange={(e) => setDetail(e.target.value)}
              placeholder="Incident details, justification, etc."
              rows="3"
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>

        {/* Two-column layout: Compliance + AttackPath */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* Compliance validation */}
          <ComplianceBadgeGroup target={primaryTarget} actionType={actionType} />

          {/* Attack path canvas */}
          <AttackPathCanvas primaryTarget={primaryTarget} maxDepth={2} />
        </div>

        {/* Execute button */}
        <button
          onClick={handleExecuteAction}
          disabled={executing || !primaryTarget}
          className="w-full px-4 py-3 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 text-white font-semibold rounded transition"
        >
          {executing ? 'Executing...' : 'Execute Action'}
        </button>

        {/* Error display */}
        {error && (
          <div className="mt-6 p-4 bg-red-900 border border-red-700 rounded text-red-100">
            <div className="font-semibold mb-1">Error</div>
            <div className="text-sm">{error}</div>
          </div>
        )}

        {/* Result display */}
        {result && (
          <div className="mt-6 p-4 bg-green-900 border border-green-700 rounded text-green-100">
            <div className="font-semibold mb-2">Action Executed</div>
            <div className="space-y-1 text-sm">
              <div><strong>Status:</strong> {result.status}</div>
              <div><strong>Connector:</strong> {result.connector}</div>
              <div><strong>Attempts:</strong> {result.attempts}</div>
              {result.error_classification && (
                <div><strong>Classification:</strong> {result.error_classification}</div>
              )}
              {result.detail && (
                <div className="mt-2">
                  <div className="text-xs text-gray-300">Detail:</div>
                  <pre className="text-xs bg-black bg-opacity-50 p-2 rounded mt-1 overflow-auto max-h-48">
                    {JSON.stringify(result.detail, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ResponseConsole;
