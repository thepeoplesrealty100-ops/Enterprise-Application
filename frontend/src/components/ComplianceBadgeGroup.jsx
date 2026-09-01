/**
 * frontend/src/components/ComplianceBadgeGroup.jsx
 * Real-time compliance validation badges for containment actions.
 * Wires to GET /response/compliance/pre-check on target selection.
 */

import React, { useState, useEffect } from 'react';

const ComplianceBadgeGroup = ({ target, actionType, disabled = false }) => {
  const [validationState, setValidationState] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!target || !actionType) return;

    const checkCompliance = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(
          `/api/response/compliance/pre-check?action_type=${encodeURIComponent(actionType)}&target=${encodeURIComponent(target)}`,
          { method: 'GET' }
        );
        const data = await response.json();
        setValidationState(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    checkCompliance();
  }, [target, actionType]);

  if (!validationState && !loading && !error) return null;

  const statusBadgeColor = (compliant) => compliant ? 'bg-green-900 text-green-100' : 'bg-red-900 text-red-100';
  const constraintBadgeColor = (constraint) => {
    if (constraint.includes('hipaa')) return 'bg-blue-900 text-blue-100';
    if (constraint.includes('soc2')) return 'bg-purple-900 text-purple-100';
    if (constraint.includes('pci')) return 'bg-orange-900 text-orange-100';
    return 'bg-gray-700 text-gray-100';
  };

  return (
    <div className="space-y-3 p-4 bg-gray-800 rounded-lg border border-gray-700">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold text-gray-400 uppercase">Compliance Check</span>
        {loading && <span className="text-xs text-yellow-400">Checking...</span>}
      </div>

      {error && (
        <div className="p-2 bg-red-900 border border-red-700 rounded text-red-100 text-sm">
          {error}
        </div>
      )}

      {validationState && (
        <>
          <div className={`inline-block px-3 py-1 rounded text-sm font-medium ${statusBadgeColor(validationState.compliant)}`}>
            {validationState.compliant ? '✓ Compliant' : '✗ Violations Detected'}
          </div>

          {validationState.violations && validationState.violations.length > 0 && (
            <div className="space-y-2">
              {validationState.violations.map((v, i) => (
                <div
                  key={i}
                  className={`p-2 rounded text-sm ${constraintBadgeColor(v.constraint)}`}
                  title={v.reason}
                >
                  <div className="font-semibold capitalize">{v.constraint.replace(/_/g, ' ')}</div>
                  <div className="text-xs opacity-90 line-clamp-2">{v.reason}</div>
                </div>
              ))}
            </div>
          )}

          {validationState.requires_audit_exception && (
            <div className="p-2 bg-yellow-900 border border-yellow-700 rounded text-yellow-100 text-xs">
              ⚠ Audit exception required. Override requires written compliance approval.
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default ComplianceBadgeGroup;
