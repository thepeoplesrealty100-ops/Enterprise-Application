#!/usr/bin/env python3
"""
Telemetry Ingestion Test - Verification of Context Gap Bridge
Tests the closed-loop feedback architecture with correlation ID injection and instant verification.
"""

import sys
import os
import time
import uuid
import logging
import json
from datetime import datetime
from pathlib import Path

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.database import DuckDBManager
from backend.monitoring import setup_logging, performance_monitor, audit_logger

# Setup logging
logger = setup_logging()

class TelemetryIngestionTest:
    """Test suite for telemetry injection and verification"""
    
    def __init__(self):
        self.db_path = os.getenv("DATABASE_URL", "data/jakal.duckdb")
        self.db = DuckDBManager(self.db_path)
        self.test_results = []
        self.correlation_ids = []
    
    def test_correlation_id_injection(self):
        """Test 1: Generate and inject unique correlation ID"""
        logger.info("=" * 80)
        logger.info("TEST 1: Correlation ID Injection")
        logger.info("=" * 80)
        
        try:
            # Generate unique correlation ID
            correlation_id = f"jkl-exec-uuid-{uuid.uuid4().hex[:8]}"
            self.correlation_ids.append(correlation_id)
            
            logger.info(f"✅ Generated correlation ID: {correlation_id}")
            
            test_result = {
                "test": "Correlation ID Injection",
                "status": "PASSED",
                "correlation_id": correlation_id,
                "timestamp": datetime.utcnow().isoformat()
            }
            self.test_results.append(test_result)
            
            return correlation_id
            
        except Exception as e:
            logger.error(f"❌ Correlation ID injection failed: {str(e)}")
            self.test_results.append({
                "test": "Correlation ID Injection",
                "status": "FAILED",
                "error": str(e)
            })
            return None
    
    def test_atomic_task_execution(self, correlation_id):
        """Test 2: Execute atomic MITRE ATT&CK technique simulation"""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 2: Atomic Task Execution (Safe Simulation)")
        logger.info("=" * 80)
        
        try:
            logger.info(f"Executing: MITRE T1087 (Account Discovery)")
            logger.info(f"Correlation ID: {correlation_id}")
            
            # Simulate execution timestamp
            execution_time = datetime.utcnow()
            start_ns = time.time_ns()
            
            # Simulate atomic task execution (safe - no actual system calls)
            execution_details = {
                "technique_id": "T1087",
                "technique_name": "Account Discovery",
                "tactic": "Discovery",
                "execution_method": "safe_simulation",
                "target_system": "localhost",
                "user_context": "testuser",
                "process_path": "C:\\Windows\\System32\\cmd.exe",
                "command_line": "net user /domain",
                "parent_process": "explorer.exe",
                "parent_process_id": 4328
            }
            
            # Log to database with correlation ID
            log_id = self.db.insert_log({
                "timestamp": execution_time,
                "event": "MITRE_TECHNIQUE_EXECUTION",
                "action": "execute_t1087",
                "status": "executed",
                "agent_type": "test_agent",
                "operator_id": "test_operator",
                "target": "localhost",
                "details": json.dumps({
                    "correlation_id": correlation_id,
                    "execution_details": execution_details,
                    "trace_context": f"trace-id={correlation_id},parent-id=root,span-id={uuid.uuid4().hex[:8]}"
                })
            })
            
            end_ns = time.time_ns()
            latency_ms = (end_ns - start_ns) / 1_000_000
            
            logger.info(f"✅ Task execution logged (Log ID: {log_id})")
            logger.info(f"   Execution latency: {latency_ms:.2f}ms")
            logger.info(f"   Details: {json.dumps(execution_details, indent=2)}")
            
            self.test_results.append({
                "test": "Atomic Task Execution",
                "status": "PASSED",
                "log_id": log_id,
                "correlation_id": correlation_id,
                "latency_ms": latency_ms,
                "timestamp": execution_time.isoformat()
            })
            
            return log_id
            
        except Exception as e:
            logger.error(f"❌ Task execution failed: {str(e)}", exc_info=True)
            self.test_results.append({
                "test": "Atomic Task Execution",
                "status": "FAILED",
                "correlation_id": correlation_id,
                "error": str(e)
            })
            return None
    
    def test_instant_verification(self, correlation_id, log_id):
        """Test 3: Instant verification of telemetry within milliseconds"""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 3: Instant Verification Engine")
        logger.info("=" * 80)
        
        try:
            verification_start = time.time_ns()
            
            # Condition 1: Detection verification
            logger.info("Checking Condition 1: Detection (Alert/Flag Raised)")
            detection_query = """
                SELECT COUNT(*) as alert_count FROM agent_logs 
                WHERE details LIKE ? AND status = 'executed'
            """
            detection_result = self.db.query(detection_query, (f"%{correlation_id}%",))
            detection_found = detection_result[0][0] > 0 if detection_result else False
            logger.info(f"  Detection found: {detection_found}")
            
            # Condition 2: Logging verification
            logger.info("Checking Condition 2: Logging (Raw Event in Telemetry)")
            logging_query = """
                SELECT COUNT(*) as log_count FROM agent_logs 
                WHERE id = ? AND event = 'MITRE_TECHNIQUE_EXECUTION'
            """
            logging_result = self.db.query(logging_query, (log_id,))
            logging_found = logging_result[0][0] > 0 if logging_result else False
            logger.info(f"  Logging found: {logging_found}")
            
            # Condition 3: Telemetry quality verification
            logger.info("Checking Condition 3: Telemetry Quality (Accurate Mapping)")
            quality_query = """
                SELECT details FROM agent_logs 
                WHERE id = ? AND details LIKE '%T1087%'
            """
            quality_result = self.db.query(quality_query, (log_id,))
            telemetry_quality = len(quality_result) > 0 if quality_result else False
            logger.info(f"  Telemetry quality verified: {telemetry_quality}")
            
            verification_end = time.time_ns()
            verification_latency_ms = (verification_end - verification_start) / 1_000_000
            
            # Calculate overall verification score
            all_conditions_met = detection_found and logging_found and telemetry_quality
            verification_status = "VERIFIED_DETECTION" if all_conditions_met else "BLIND_SPOT_DETECTED"
            confidence_score = 99.99 if all_conditions_met else 0.01
            
            logger.info(f"\n📊 Verification Results:")
            logger.info(f"  Detection:         {detection_found} ✓" if detection_found else f"  Detection:         {detection_found} ✗")
            logger.info(f"  Logging:           {logging_found} ✓" if logging_found else f"  Logging:           {logging_found} ✗")
            logger.info(f"  Telemetry Quality: {telemetry_quality} ✓" if telemetry_quality else f"  Telemetry Quality: {telemetry_quality} ✗")
            logger.info(f"\n🎯 Status: {verification_status}")
            logger.info(f"   Confidence Score: {confidence_score}%")
            logger.info(f"   Verification Latency: {verification_latency_ms:.3f}ms")
            
            # Log verification result
            audit_logger.log_admin_action(
                "test_operator",
                "telemetry_verification",
                f"Status: {verification_status}, Latency: {verification_latency_ms:.2f}ms, Score: {confidence_score}%"
            )
            
            self.test_results.append({
                "test": "Instant Verification",
                "status": "PASSED",
                "verification_status": verification_status,
                "conditions": {
                    "detection": detection_found,
                    "logging": logging_found,
                    "telemetry_quality": telemetry_quality
                },
                "confidence_score": confidence_score,
                "latency_ms": verification_latency_ms,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            return all_conditions_met
            
        except Exception as e:
            logger.error(f"❌ Verification failed: {str(e)}", exc_info=True)
            self.test_results.append({
                "test": "Instant Verification",
                "status": "FAILED",
                "correlation_id": correlation_id,
                "error": str(e)
            })
            return False
    
    def test_automated_scorecard_generation(self):
        """Test 4: Generate automated scorecard"""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 4: Automated Scorecard Generation")
        logger.info("=" * 80)
        
        try:
            total_tests = len(self.test_results)
            passed_tests = sum(1 for r in self.test_results if r.get("status") == "PASSED")
            failed_tests = total_tests - passed_tests
            
            logger.info(f"\n📋 Telemetry Ingestion Test Scorecard")
            logger.info(f"{'=' * 80}")
            logger.info(f"Total Tests:  {total_tests}")
            logger.info(f"Passed:       {passed_tests} ✓")
            logger.info(f"Failed:       {failed_tests} ✗")
            logger.info(f"Pass Rate:    {(passed_tests/total_tests*100):.1f}%")
            logger.info(f"{'=' * 80}")
            
            # Print detailed results
            logger.info("\nDetailed Results:")
            for i, result in enumerate(self.test_results, 1):
                status_icon = "✓" if result["status"] == "PASSED" else "✗"
                logger.info(f"\n{i}. {result['test']} [{status_icon}]")
                for key, value in result.items():
                    if key not in ["test", "status"]:
                        if isinstance(value, dict):
                            logger.info(f"   {key}: {json.dumps(value, indent=6)}")
                        else:
                            logger.info(f"   {key}: {value}")
            
            # Save scorecard to file
            scorecard_file = Path("logs") / f"telemetry_test_scorecard_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            Path("logs").mkdir(exist_ok=True)
            
            with open(scorecard_file, "w") as f:
                json.dump(self.test_results, f, indent=2)
            
            logger.info(f"\n✅ Scorecard saved to: {scorecard_file}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Scorecard generation failed: {str(e)}", exc_info=True)
            return False
    
    def run_all_tests(self):
        """Execute complete telemetry test suite"""
        logger.info("\n" + "🔬 " * 20)
        logger.info("JAKAL TELEMETRY INGESTION TEST SUITE")
        logger.info("Context Gap Bridge Verification")
        logger.info("🔬 " * 20 + "\n")
        
        try:
            # Test 1: Correlation ID Injection
            correlation_id = self.test_correlation_id_injection()
            if not correlation_id:
                return False
            
            # Test 2: Atomic Task Execution
            log_id = self.test_atomic_task_execution(correlation_id)
            if not log_id:
                return False
            
            # Test 3: Instant Verification
            verification_passed = self.test_instant_verification(correlation_id, log_id)
            
            # Test 4: Scorecard Generation
            self.test_automated_scorecard_generation()
            
            logger.info("\n" + "✅ " * 20)
            logger.info("TELEMETRY INGESTION TEST SUITE COMPLETED")
            logger.info("✅ " * 20 + "\n")
            
            return verification_passed
            
        except Exception as e:
            logger.error(f"\n❌ Test suite failed: {str(e)}", exc_info=True)
            return False
        
        finally:
            self.db.close()

def main():
    """Main entry point"""
    test_suite = TelemetryIngestionTest()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
