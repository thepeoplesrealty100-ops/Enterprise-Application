/**
 * frontend/src/components/AttackPathCanvas.jsx
 * Graph visualization for lateral movement paths and attack surface.
 * Wires to GET /response/related-targets for multi-node remediation.
 */

import React, { useState, useEffect } from 'react';

const AttackPathCanvas = ({ primaryTarget, maxDepth = 2 }) => {
  const [nodes, setNodes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedForRemediation, setSelectedForRemediation] = useState(new Set());

  useEffect(() => {
    if (!primaryTarget) return;

    const fetchRelatedTargets = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(
          `/api/response/related-targets?target=${encodeURIComponent(primaryTarget)}&max_depth=${maxDepth}`,
          { method: 'GET' }
        );
        const data = await response.json();

        // Construct graph: primary target + related targets
        const graphNodes = [
          { id: primaryTarget, label: primaryTarget, type: 'primary', depth: 0 }
        ];
        (data.related_targets || []).forEach((target, idx) => {
          graphNodes.push({
            id: target,
            label: target,
            type: 'related',
            depth: idx < (data.related_targets.length / 2) ? 1 : 2
          });
        });

        setNodes(graphNodes);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchRelatedTargets();
  }, [primaryTarget, maxDepth]);

  const toggleSelection = (targetId) => {
    const newSelection = new Set(selectedForRemediation);
    if (newSelection.has(targetId)) {
      newSelection.delete(targetId);
    } else {
      newSelection.add(targetId);
    }
    setSelectedForRemediation(newSelection);
  };

  const handleBatchRemediation = async () => {
    if (selectedForRemediation.size === 0) return;

    // Trigger multi-node containment via parent callback or direct API
    console.log('Batch remediation targets:', Array.from(selectedForRemediation));
    // In production: POST /api/response/batch-remediate with targets + action_type
  };

  return (
    <div className="space-y-4 p-4 bg-gray-800 rounded-lg border border-gray-700">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-100">Attack Surface</h3>
        {loading && <span className="text-xs text-yellow-400">Analyzing...</span>}
      </div>

      {error && (
        <div className="p-2 bg-red-900 border border-red-700 rounded text-red-100 text-sm">
          {error}
        </div>
      )}

      {nodes.length > 0 && (
        <>
          {/* Simplified node list (full graph rendering would use D3/Three.js) */}
          <div className="space-y-2">
            {nodes.map((node) => (
              <div
                key={node.id}
                className={`p-3 rounded border cursor-pointer transition ${
                  selectedForRemediation.has(node.id)
                    ? 'bg-orange-900 border-orange-600'
                    : 'bg-gray-700 border-gray-600 hover:border-gray-500'
                }`}
                onClick={() => toggleSelection(node.id)}
              >
                <div className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    checked={selectedForRemediation.has(node.id)}
                    onChange={() => {}}
                    className="mt-1"
                  />
                  <div className="flex-1">
                    <div className="font-mono text-sm text-gray-100">{node.label}</div>
                    <div className="text-xs text-gray-400">
                      {node.type === 'primary' ? 'Primary Target' : `Related (Depth ${node.depth})`}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {selectedForRemediation.size > 0 && (
            <button
              onClick={handleBatchRemediation}
              className="w-full px-4 py-2 bg-orange-600 hover:bg-orange-700 text-white font-medium rounded transition"
            >
              Containment ({selectedForRemediation.size} targets)
            </button>
          )}
        </>
      )}

      {nodes.length === 0 && !loading && !error && (
        <div className="text-xs text-gray-400">No related targets found.</div>
      )}
    </div>
  );
};

export default AttackPathCanvas;
