#!/usr/bin/env python3
"""JAKAL Database Layer - DuckDB Manager"""
import duckdb
import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class DuckDBManager:
    """DuckDB database manager with ACID compliance."""
    
    def __init__(self, db_path: str = "data/jakal.duckdb"):
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else "data", exist_ok=True)
        self.db_path = db_path
        self.conn = duckdb.connect(db_path)
        logger.info(f"✅ Connected to DuckDB at {db_path}")
    
    def initialize_schema(self):
        """Initialize all required tables."""
        logger.info("Initializing database schema...")
        try:
            # Sequences
            self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_logs START 1")
            self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_findings START 1")
            self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_pentest START 1")
            self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_scopes START 1")
            self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_insurance START 1")
            self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_operators START 1")
            
            # Agent logs (immutable)
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_logs (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_logs'),
                timestamp TIMESTAMP DEFAULT current_timestamp,
                event VARCHAR NOT NULL,
                action VARCHAR,
                status VARCHAR,
                agent_type VARCHAR,
                operator_id VARCHAR,
                target VARCHAR,
                details VARCHAR
            )
            """)
            
            # Quantum jobs
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS quantum_jobs (
                id INTEGER PRIMARY KEY,
                job_id VARCHAR UNIQUE NOT NULL,
                circuit_name VARCHAR NOT NULL,
                backend VARCHAR DEFAULT 'qiskit-aer',
                shots INTEGER DEFAULT 1024,
                result VARCHAR,
                status VARCHAR DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT current_timestamp
            )
            """)
            
            # Penetration test runs
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pentest_runs (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_pentest'),
                test_id VARCHAR UNIQUE NOT NULL,
                target VARCHAR NOT NULL,
                scan_type VARCHAR DEFAULT 'comprehensive',
                status VARCHAR DEFAULT 'pending',
                operator_id VARCHAR NOT NULL,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
            """)
            
            # Security findings
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_findings'),
                pentest_id INTEGER NOT NULL,
                title VARCHAR NOT NULL,
                description VARCHAR,
                severity VARCHAR,
                cvss_score DECIMAL(3,1),
                created_at TIMESTAMP DEFAULT current_timestamp
            )
            """)
            
            # MITRE ATT&CK mappings
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS attack_mappings (
                id INTEGER PRIMARY KEY,
                pentest_id INTEGER,
                finding_id INTEGER,
                tactic VARCHAR NOT NULL,
                technique_id VARCHAR NOT NULL,
                technique_name VARCHAR NOT NULL,
                confidence DECIMAL(3,2) DEFAULT 0.8
            )
            """)
            
            # Scopes (RoE)
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS scopes (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_scopes'),
                scope_id VARCHAR UNIQUE NOT NULL,
                client_name VARCHAR NOT NULL,
                scope_definition VARCHAR NOT NULL,
                target_ips VARCHAR,
                target_domains VARCHAR,
                status VARCHAR DEFAULT 'active',
                created_at TIMESTAMP DEFAULT current_timestamp,
                expires_at TIMESTAMP
            )
            """)
            
            # Insurance policies
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS insurance_policies (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_insurance'),
                policy_number VARCHAR UNIQUE NOT NULL,
                provider VARCHAR NOT NULL,
                coverage_amount DECIMAL(15,2),
                expiry TIMESTAMP NOT NULL,
                status VARCHAR DEFAULT 'active',
                created_at TIMESTAMP DEFAULT current_timestamp
            )
            """)
            
            # Compliance checkpoints (immutable)
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS compliance_checkpoints (
                id INTEGER PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT current_timestamp,
                action_type VARCHAR NOT NULL,
                operator_id VARCHAR NOT NULL,
                target VARCHAR,
                authorization_result VARCHAR,
                allowed_to_proceed BOOLEAN
            )
            """)
            
            # Operators
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS operators (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_operators'),
                operator_id VARCHAR UNIQUE NOT NULL,
                email VARCHAR UNIQUE NOT NULL,
                role VARCHAR,
                active BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
            """)
            
            # Assessment reports
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS assessment_reports (
                id INTEGER PRIMARY KEY,
                pentest_id INTEGER,
                report_type VARCHAR,
                content VARCHAR,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
            """)
            
            # Indexes
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_logs_timestamp ON agent_logs(timestamp)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_findings_pentest ON findings(pentest_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_scopes_status ON scopes(status)")
            
            self.conn.commit()
            logger.info("✅ Database schema initialized successfully")
            
        except Exception as e:
            logger.error(f"Schema initialization failed: {str(e)}")
            raise
    
    def execute(self, sql: str, params: Tuple = ()) -> Any:
        """Execute SQL statement."""
        try:
            self.conn.execute(sql, params)
            self.conn.commit()
        except Exception as e:
            logger.error(f"Execute failed: {str(e)}")
            raise
    
    def query(self, sql: str, params: Tuple = ()) -> List[Tuple]:
        """Execute SELECT query."""
        try:
            return self.conn.execute(sql, params).fetchall()
        except Exception as e:
            logger.error(f"Query failed: {str(e)}")
            raise
    
    def query_one(self, sql: str, params: Tuple = ()) -> Optional[Tuple]:
        """Execute SELECT and return first result."""
        try:
            return self.conn.execute(sql, params).fetchone()
        except Exception as e:
            logger.error(f"Query failed: {str(e)}")
            raise
    
    def insert_log(self, log_data: Dict[str, Any]) -> int:
        """Insert agent log entry."""
        try:
            self.conn.execute("""
                INSERT INTO agent_logs 
                (timestamp, event, action, status, agent_type, operator_id, target, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log_data.get("timestamp", datetime.utcnow()),
                log_data.get("event"),
                log_data.get("action"),
                log_data.get("status"),
                log_data.get("agent_type"),
                log_data.get("operator_id"),
                log_data.get("target"),
                json.dumps(log_data.get("details", {}))
            ))
            self.conn.commit()
            result = self.conn.execute("SELECT last_insert_rowid()").fetchone()
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Insert log failed: {str(e)}")
            raise
    
    def insert_finding(self, finding_data: Dict[str, Any]) -> int:
        """Insert a security finding."""
        try:
            self.conn.execute("""
                INSERT INTO findings
                (pentest_id, title, description, severity, cvss_score)
                VALUES (?, ?, ?, ?, ?)
            """, (
                finding_data.get("pentest_id"),
                finding_data.get("title"),
                finding_data.get("description"),
                finding_data.get("severity", "MEDIUM"),
                finding_data.get("cvss_score")
            ))
            self.conn.commit()
            result = self.conn.execute("SELECT last_insert_rowid()").fetchone()
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Insert finding failed: {str(e)}")
            raise
    
    def get_findings_by_pentest(self, pentest_id: int, severity: Optional[str] = None) -> List[Dict]:
        """Get findings for a penetration test."""
        try:
            if severity:
                results = self.query("SELECT id, title, severity, cvss_score FROM findings WHERE pentest_id = ? AND severity = ?", (pentest_id, severity))
            else:
                results = self.query("SELECT id, title, severity, cvss_score FROM findings WHERE pentest_id = ?", (pentest_id,))
            
            return [{"id": row[0], "title": row[1], "severity": row[2], "cvss_score": row[3]} for row in results] if results else []
        except Exception as e:
            logger.error(f"Get findings failed: {str(e)}")
            raise
    
    def backup(self, backup_path: str) -> None:
        """Create a database backup."""
        try:
            os.makedirs(os.path.dirname(backup_path) if os.path.dirname(backup_path) else ".", exist_ok=True)
            self.conn.execute(f"COPY (SELECT * FROM agent_logs) TO '{backup_path}_logs.parquet' (FORMAT PARQUET)")
            logger.info(f"✅ Database backed up to {backup_path}")
        except Exception as e:
            logger.error(f"Backup failed: {str(e)}")
            raise
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
