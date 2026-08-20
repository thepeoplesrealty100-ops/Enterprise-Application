#!/usr/bin/env python3
"""Monitoring & Logging Setup for JAKAL"""

import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path

def setup_logging():
    """Configure comprehensive logging system"""
    
    # Create logs directory
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Main logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # Log format
    formatter = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler (INFO level)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler - Main log (DEBUG level)
    main_log = log_dir / "jakal.log"
    file_handler = logging.handlers.RotatingFileHandler(
        main_log,
        maxBytes=10*1024*1024,  # 10 MB
        backupCount=10
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # File handler - Agent logs
    agent_log = log_dir / "agents.log"
    agent_handler = logging.handlers.RotatingFileHandler(
        agent_log,
        maxBytes=10*1024*1024,
        backupCount=5
    )
    agent_handler.setLevel(logging.DEBUG)
    agent_handler.setFormatter(formatter)
    logging.getLogger("agents").addHandler(agent_handler)
    
    # File handler - API logs
    api_log = log_dir / "api.log"
    api_handler = logging.handlers.RotatingFileHandler(
        api_log,
        maxBytes=10*1024*1024,
        backupCount=5
    )
    api_handler.setLevel(logging.DEBUG)
    api_handler.setFormatter(formatter)
    logging.getLogger("api").addHandler(api_handler)
    
    # File handler - Error logs
    error_log = log_dir / "errors.log"
    error_handler = logging.handlers.RotatingFileHandler(
        error_log,
        maxBytes=5*1024*1024,
        backupCount=3
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)
    
    return logger

class PerformanceMonitor:
    """Monitor system performance and metrics"""
    
    def __init__(self):
        self.metrics = {
            "requests_total": 0,
            "requests_success": 0,
            "requests_error": 0,
            "requests_slowest": 0,
            "llm_requests": 0,
            "quantum_jobs": 0,
            "scan_count": 0,
            "findings_count": 0,
            "agents_active": 0,
            "db_queries": 0,
            "db_errors": 0
        }
        self.logger = logging.getLogger("monitor")
    
    def record_request(self, path: str, method: str, status_code: int, duration_ms: float):
        """Record API request metrics"""
        self.metrics["requests_total"] += 1
        
        if 200 <= status_code < 300:
            self.metrics["requests_success"] += 1
        elif status_code >= 400:
            self.metrics["requests_error"] += 1
        
        if duration_ms > self.metrics["requests_slowest"]:
            self.metrics["requests_slowest"] = duration_ms
            
            if duration_ms > 1000:  # Log slow requests
                self.logger.warning(f"Slow request: {method} {path} - {duration_ms:.2f}ms")
    
    def record_llm_usage(self):
        """Record LLM request"""
        self.metrics["llm_requests"] += 1
    
    def record_quantum_job(self):
        """Record quantum job"""
        self.metrics["quantum_jobs"] += 1
    
    def record_scan(self):
        """Record security scan"""
        self.metrics["scan_count"] += 1
    
    def record_finding(self):
        """Record vulnerability finding"""
        self.metrics["findings_count"] += 1
    
    def record_agent_start(self):
        """Record agent startup"""
        self.metrics["agents_active"] += 1
    
    def record_agent_stop(self):
        """Record agent shutdown"""
        self.metrics["agents_active"] = max(0, self.metrics["agents_active"] - 1)
    
    def record_db_query(self, success: bool = True):
        """Record database query"""
        self.metrics["db_queries"] += 1
        if not success:
            self.metrics["db_errors"] += 1
    
    def get_metrics(self) -> dict:
        """Get current metrics"""
        return self.metrics.copy()
    
    def get_health_status(self) -> dict:
        """Get health status based on metrics"""
        error_rate = (self.metrics["requests_error"] / 
                     max(1, self.metrics["requests_total"]) * 100)
        
        db_error_rate = (self.metrics["db_errors"] / 
                        max(1, self.metrics["db_queries"]) * 100)
        
        health = "healthy"
        if error_rate > 5 or db_error_rate > 5:
            health = "degraded"
        if error_rate > 20 or db_error_rate > 20:
            health = "unhealthy"
        
        return {
            "status": health,
            "error_rate": f"{error_rate:.2f}%",
            "db_error_rate": f"{db_error_rate:.2f}%",
            "slowest_request_ms": self.metrics["requests_slowest"],
            "timestamp": datetime.utcnow().isoformat()
        }

class AuditLogger:
    """Audit sensitive operations"""
    
    def __init__(self):
        self.logger = logging.getLogger("audit")
        self.audit_log = Path("logs") / "audit.log"
        
        handler = logging.handlers.RotatingFileHandler(
            self.audit_log,
            maxBytes=10*1024*1024,
            backupCount=12
        )
        formatter = logging.Formatter(
            '%(asctime)s | AUDIT | %(levelname)s | %(message)s'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def log_authorization_check(self, operator_id: str, target: str, action: str, result: bool):
        """Log authorization check"""
        status = "APPROVED" if result else "DENIED"
        self.logger.warning(f"{status} - {operator_id} attempted {action} on {target}")
    
    def log_agent_execution(self, agent_type: str, target: str, status: str):
        """Log agent execution"""
        self.logger.info(f"Agent {agent_type} executed on {target} - {status}")
    
    def log_finding_discovery(self, severity: str, vulnerability: str):
        """Log vulnerability discovery"""
        self.logger.warning(f"Finding discovered - {severity}: {vulnerability}")
    
    def log_admin_action(self, admin_id: str, action: str, details: str):
        """Log administrative action"""
        self.logger.warning(f"Admin action - {admin_id}: {action} - {details}")
    
    def log_data_access(self, user_id: str, resource: str, action: str):
        """Log data access"""
        self.logger.info(f"Data access - {user_id} {action} {resource}")

# Global instances
performance_monitor = PerformanceMonitor()
audit_logger = AuditLogger()

# Setup logging on import
setup_logging()
