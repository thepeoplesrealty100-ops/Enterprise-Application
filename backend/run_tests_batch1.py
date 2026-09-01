#!/usr/bin/env python3
"""
Backend Batch 1 - Comprehensive Test Suite (20+ iterations)

Tests all newly created components:
  1. enforcement.py - AuditedHostIsolationEngine
  2. webhook_dispatcher.py - WebhookDispatcher
  3. audit_logger.py - AuditLogger
  4. resonance.py router - Policy management + enforcement APIs
  5. scripts.py router - Script library management
  6. database.py extensions - New tables
"""

import json
import uuid
import time
from datetime import datetime, timezone
from typing import Dict, List, Any

# Mock database for testing (no actual DB needed)
class MockDB:
    def __init__(self):
        self.data = {}
        self.conn = self
    
    def execute(self, query, params=None):
        """Mock query execution"""
        return self
    
    def fetchone(self):
        return None
    
    def fetchall(self):
        return []
    
    def commit(self):
        pass

def test_enforcement_engine(iteration: int) -> Dict[str, Any]:
    """Test AuditedHostIsolationEngine (multiple iterations)"""
    try:
        from core.enforcement import (
            AuditedHostIsolationEngine, AuditedHostIsolation,
            IsolationMode, IsolationTrigger, IsolationAction
        )
        
        db = MockDB()
        engine = AuditedHostIsolationEngine(db)
        
        # Test 1: Create isolation request
        isolation = engine.create_isolation_request(
            hostname=f"host-{iteration}.example.com",
            ip_address=f"192.168.1.{iteration}",
            os_type="Linux",
            isolation_mode=IsolationMode.NETWORK_ONLY,
            isolation_trigger=IsolationTrigger.THREAT_DETECTION,
            action=IsolationAction.ISOLATE_HOST,
            requested_by="test-operator",
            threat_severity=0.75,
            justification="Test isolation"
        )
        assert isolation.isolation_id
        assert isolation.status.value == "pending"
        
        # Test 2: Simulate isolation
        sim_result = engine.simulate_isolation(isolation.isolation_id, "test-operator")
        assert sim_result["status"] == "simulated"
        assert "simulation_report" in sim_result
        
        # Test 3: Get isolation status
        status = engine.get_isolation_status(isolation.isolation_id)
        assert status is not None
        assert status["isolation_id"] == isolation.isolation_id
        
        return {
            "test": "enforcement_engine",
            "iteration": iteration,
            "status": "PASS",
            "created_isolation_id": isolation.isolation_id,
        }
    
    except Exception as e:
        return {
            "test": "enforcement_engine",
            "iteration": iteration,
            "status": "FAIL",
            "error": str(e),
        }


def test_webhook_dispatcher(iteration: int) -> Dict[str, Any]:
    """Test WebhookDispatcher (multiple iterations)"""
    try:
        from core.webhook_dispatcher import WebhookDispatcher
        
        db = MockDB()
        dispatcher = WebhookDispatcher(db)
        
        # Test 1: Envelope signing
        envelope = {
            "event_id": str(uuid.uuid4()),
            "event_type": "test_event",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"test": f"iteration_{iteration}"}
        }
        
        signature = dispatcher._sign_envelope(envelope)
        assert signature
        assert len(signature) == 64  # SHA256 hex is 64 chars
        
        # Test 2: Signature verification
        envelope_json = json.dumps(envelope, sort_keys=True, default=str)
        is_valid = dispatcher.verify_signature(envelope_json, signature)
        assert is_valid
        
        # Test 3: Invalid signature detection
        bad_signature = "0" * 64
        is_invalid = dispatcher.verify_signature(envelope_json, bad_signature)
        assert not is_invalid
        
        return {
            "test": "webhook_dispatcher",
            "iteration": iteration,
            "status": "PASS",
            "signature_verified": is_valid,
        }
    
    except Exception as e:
        return {
            "test": "webhook_dispatcher",
            "iteration": iteration,
            "status": "FAIL",
            "error": str(e),
        }


def test_audit_logger(iteration: int) -> Dict[str, Any]:
    """Test AuditLogger (multiple iterations)"""
    try:
        from core.audit_logger import AuditLogger, AuditEvent
        
        db = MockDB()
        logger = AuditLogger(db)
        
        # Test 1: Log an event
        event_id = logger.log(
            event_type=f"test_event_{iteration}",
            action="test_action",
            actor=f"test_operator_{iteration}",
            resource=f"test_resource_{iteration}",
            result="success",
            details={"test": "data"}
        )
        assert event_id
        
        # Test 2: Create AuditEvent directly
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type="test",
            action="test_action",
            actor="test_actor"
        )
        assert event.event_id
        assert event.timestamp
        
        # Test 3: Get audit stats (mock)
        stats = logger.audit_stats()
        assert isinstance(stats, dict)
        
        return {
            "test": "audit_logger",
            "iteration": iteration,
            "status": "PASS",
            "event_id": event_id,
        }
    
    except Exception as e:
        return {
            "test": "audit_logger",
            "iteration": iteration,
            "status": "FAIL",
            "error": str(e),
        }


def test_routers_imports(iteration: int) -> Dict[str, Any]:
    """Test router imports and initialization"""
    try:
        from routers.resonance import router as resonance_router
        from routers.scripts import router as scripts_router
        
        # Verify routers are properly initialized
        assert resonance_router
        assert scripts_router
        assert hasattr(resonance_router, 'routes')
        assert hasattr(scripts_router, 'routes')
        
        # Verify resonance endpoints exist
        resonance_routes = [r.path for r in resonance_router.routes]
        assert any('/fleet' in r for r in resonance_routes)
        assert any('/policies' in r for r in resonance_routes)
        assert any('/enforce' in r for r in resonance_routes)
        
        # Verify scripts endpoints exist
        scripts_routes = [r.path for r in scripts_router.routes]
        assert any('/catalog' in r for r in scripts_routes)
        assert any('/sandbox-execute' in r for r in scripts_routes)
        assert any('/executions' in r for r in scripts_routes)
        
        return {
            "test": "routers_imports",
            "iteration": iteration,
            "status": "PASS",
            "resonance_routes": len(resonance_routes),
            "scripts_routes": len(scripts_routes),
        }
    
    except Exception as e:
        return {
            "test": "routers_imports",
            "iteration": iteration,
            "status": "FAIL",
            "error": str(e),
        }


def test_database_schema(iteration: int) -> Dict[str, Any]:
    """Test database schema validation"""
    try:
        # Check that new table definitions are present in database.py
        with open('backend/database.py', 'r') as f:
            content = f.read()
        
        # Verify new tables are defined
        assert 'resonance_policy' in content
        assert 'resonance_actions' in content
        assert 'resonance_audit_trail' in content
        assert 'script_library' in content
        assert 'script_executions' in content
        
        # Verify new sequences
        assert 'seq_resonance_policy' in content
        assert 'seq_script_lib' in content
        
        return {
            "test": "database_schema",
            "iteration": iteration,
            "status": "PASS",
            "tables_verified": 5,
            "sequences_verified": 2,
        }
    
    except Exception as e:
        return {
            "test": "database_schema",
            "iteration": iteration,
            "status": "FAIL",
            "error": str(e),
        }


def run_test_suite(iterations: int = 20) -> List[Dict[str, Any]]:
    """Run full test suite with multiple iterations"""
    results = []
    test_functions = [
        test_enforcement_engine,
        test_webhook_dispatcher,
        test_audit_logger,
        test_routers_imports,
        test_database_schema,
    ]
    
    print("=" * 80)
    print("JAKAL Backend Batch 1 - Test Suite")
    print("=" * 80)
    print()
    
    for test_func in test_functions:
        print(f"Testing: {test_func.__name__}")
        print("-" * 80)
        
        test_results = []
        for iteration in range(1, iterations + 1):
            result = test_func(iteration)
            test_results.append(result)
            results.append(result)
            
            status_symbol = "✓" if result["status"] == "PASS" else "✗"
            print(f"  [{status_symbol}] Iteration {iteration}: {result['status']}")
            
            if result["status"] == "FAIL":
                print(f"       Error: {result.get('error', 'Unknown')}")
        
        # Summary for this test
        passed = sum(1 for r in test_results if r["status"] == "PASS")
        total = len(test_results)
        print(f"\n  Summary: {passed}/{total} passed\n")
    
    return results


def generate_report(results: List[Dict[str, Any]]) -> str:
    """Generate test report"""
    total_tests = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = total_tests - passed
    
    by_test = {}
    for r in results:
        test_name = r["test"]
        if test_name not in by_test:
            by_test[test_name] = {"passed": 0, "failed": 0}
        if r["status"] == "PASS":
            by_test[test_name]["passed"] += 1
        else:
            by_test[test_name]["failed"] += 1
    
    report = f"""
╔════════════════════════════════════════════════════════════════════════════╗
║               JAKAL Backend Batch 1 - Test Report                          ║
╚════════════════════════════════════════════════════════════════════════════╝

OVERALL RESULTS:
  Total Tests:    {total_tests}
  Passed:         {passed} ({'%.1f' % (100*passed/total_tests if total_tests > 0 else 0)}%)
  Failed:         {failed}

BREAKDOWN BY COMPONENT:
"""
    
    for test_name, counts in sorted(by_test.items()):
        total_for_test = counts["passed"] + counts["failed"]
        pct = 100 * counts["passed"] / total_for_test if total_for_test > 0 else 0
        report += f"  {test_name:30} {counts['passed']:2}/{total_for_test:2} ({pct:5.1f}%)\n"
    
    report += f"""
CONCLUSION:
  {'✅ ALL TESTS PASSED' if failed == 0 else f'❌ {failed} TEST(S) FAILED'}

Timestamp: {datetime.now(timezone.utc).isoformat()}
"""
    
    return report


if __name__ == "__main__":
    results = run_test_suite(iterations=20)
    report = generate_report(results)
    print(report)
    
    # Save report
    with open('backend/TEST_RESULTS_BATCH1.txt', 'w') as f:
        f.write(report)
    
    print("\n✓ Test results saved to backend/TEST_RESULTS_BATCH1.txt")
    
    # Exit with appropriate code
    exit(0 if all(r["status"] == "PASS" for r in results) else 1)
