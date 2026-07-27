# JAKAL DuckDB Database Manager
import duckdb
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

class DuckDBManager:
    """High-performance database layer using DuckDB for OLAP queries."""
    
    def __init__(self, db_path: str = "jakal.duckdb"):
        self.db_path = db_path
        self.conn = None
        self.connect()
    
    def connect(self):
        """Establish database connection."""
        try:
            self.conn = duckdb.connect(self.db_path)
            logger.info(f"Connected to DuckDB at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to connect to DuckDB: {str(e)}")
            raise
    
    def initialize_schema(self):
        """Create all required tables and indexes."""
        try:
            # Create sequences
            self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_logs START 1")
            self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_jobs START 1")
            self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_pentest START 1")
            self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_findings START 1")
            
            # Agent logs table
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_logs (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_logs'),
                timestamp TIMESTAMP DEFAULT now(),
                event VARCHAR,
                action VARCHAR,
                status VARCHAR,
                operator_id VARCHAR,
                details VARCHAR,
                severity VARCHAR,
                created_at TIMESTAMP DEFAULT now()
            )
            """)
            
            # Quantum jobs table
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS quantum_jobs (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_jobs'),
                job_id VARCHAR UNIQUE,
                circuit_name VARCHAR,
                backend VARCHAR,
                shots INTEGER,
                result VARCHAR,
                status VARCHAR,
                error_message VARCHAR,
                created_at TIMESTAMP DEFAULT now(),
                completed_at TIMESTAMP,
                execution_time_ms FLOAT
            )
            """)
            
            # Penetration test runs
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pentest_runs (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_pentest'),
                test_id VARCHAR UNIQUE,
                target VARCHAR,
                scan_type VARCHAR,
                recon_results VARCHAR,
                attack_mappings VARCHAR,
                staged_exploits VARCHAR,
                status VARCHAR,
                operator_id VARCHAR,
                created_at TIMESTAMP DEFAULT now(),
                completed_at TIMESTAMP,
                execution_time_ms FLOAT
            )
            """)
            
            # Security findings
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_findings'),
                pentest_id INTEGER,
                severity VARCHAR,
                title VARCHAR,
                description VARCHAR,
                attack_technique VARCHAR,
                remediation VARCHAR,
                evidence VARCHAR,
                verified BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT now()
            )
            """)
            
            # MITRE ATT&CK mappings
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS attack_mappings (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_findings'),
                pentest_id INTEGER,
                tactic VARCHAR,
                technique_id VARCHAR,
                technique_name VARCHAR,
                sub_technique_id VARCHAR,
                sub_technique_name VARCHAR,
                confidence_score FLOAT,
                evidence VARCHAR,
                created_at TIMESTAMP DEFAULT now()
            )
            """)
            
            # Compliance checkpoints
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS compliance_checkpoints (
                id INTEGER PRIMARY KEY,
                pentest_id INTEGER,
                framework VARCHAR,
                control_id VARCHAR,
                control_name VARCHAR,
                status VARCHAR,
                findings_count INTEGER,
                created_at TIMESTAMP DEFAULT now()
            )
            """)
            
            # Create indexes for performance
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_logs_timestamp ON agent_logs(timestamp)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_quantum_jobs_status ON quantum_jobs(status)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_pentest_runs_target ON pentest_runs(target)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity)")
            
            self.conn.commit()
            logger.info("Database schema initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize schema: {str(e)}")
            raise
    
    def insert_log(self, log_data: Dict[str, Any]) -> int:
        """Insert agent telemetry log entry."""
        try:
            result = self.conn.execute(
                """
                INSERT INTO agent_logs (event, action, status, operator_id, details, severity)
                VALUES (?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    log_data.get("event"),
                    log_data.get("action"),
                    log_data.get("status"),
                    log_data.get("operator_id", "system"),
                    json.dumps(log_data.get("details", {})),
                    log_data.get("severity", "info")
                )
            )
            self.conn.commit()
            return result.fetchone()[0]
        except Exception as e:
            logger.error(f"Failed to insert log: {str(e)}")
            raise
    
    def insert_quantum_job(self, job_data: Dict[str, Any]) -> str:
        """Insert quantum job record."""
        try:
            job_id = job_data.get('job_id')
            self.conn.execute(
                """
                INSERT INTO quantum_jobs (job_id, circuit_name, backend, shots, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    job_data.get('circuit_name'),
                    job_data.get('backend'),
                    job_data.get('shots', 1024),
                    job_data.get('status', 'submitted')
                )
            )
            self.conn.commit()
            return job_id
        except Exception as e:
            logger.error(f"Failed to insert quantum job: {str(e)}")
            raise
    
    def update_quantum_job(self, job_id: str, update_data: Dict[str, Any]):
        """Update quantum job status and results."""
        try:
            set_clause = ', '.join([f"{k}=?" for k in update_data.keys() if k != 'job_id'])
            values = [v for k, v in update_data.items() if k != 'job_id']
            values.append(job_id)
            
            self.conn.execute(
                f"UPDATE quantum_jobs SET {set_clause} WHERE job_id=?",
                values
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to update quantum job {job_id}: {str(e)}")
            raise
    
    def insert_pentest(self, test_data: Dict[str, Any]) -> str:
        """Insert penetration test run."""
        try:
            import uuid
            test_id = str(uuid.uuid4())
            
            self.conn.execute(
                """
                INSERT INTO pentest_runs 
                (test_id, target, scan_type, recon_results, attack_mappings, staged_exploits, status, operator_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    test_id,
                    test_data.get('target'),
                    test_data.get('scan_type'),
                    json.dumps(test_data.get('recon_results', {})),
                    json.dumps(test_data.get('attack_mappings', {})),
                    json.dumps(test_data.get('staged_exploits', [])),
                    test_data.get('status', 'initiated'),
                    test_data.get('operator_id', 'system')
                )
            )
            self.conn.commit()
            return test_id
        except Exception as e:
            logger.error(f"Failed to insert pentest: {str(e)}")
            raise
    
    def insert_finding(self, finding_data: Dict[str, Any]) -> int:
        """Insert security finding."""
        try:
            result = self.conn.execute(
                """
                INSERT INTO findings 
                (pentest_id, severity, title, description, attack_technique, remediation, evidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    finding_data.get('pentest_id'),
                    finding_data.get('severity'),
                    finding_data.get('title'),
                    finding_data.get('description'),
                    finding_data.get('attack_technique'),
                    finding_data.get('remediation'),
                    json.dumps(finding_data.get('evidence', {}))
                )
            )
            self.conn.commit()
            return result.fetchone()[0]
        except Exception as e:
            logger.error(f"Failed to insert finding: {str(e)}")
            raise
    
    def query(self, sql: str, params: Tuple = ()) -> List[Any]:
        """Execute SELECT query."""
        try:
            result = self.conn.execute(sql, params).fetchall()
            return result
        except Exception as e:
            logger.error(f"Query failed: {str(e)}")
            raise
    
    def query_dict(self, sql: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        """Execute SELECT query, return results as dictionaries."""
        try:
            result = self.conn.execute(sql, params)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Query failed: {str(e)}")
            raise
    
    def get_recent_logs(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Fetch recent agent logs."""
        return self.query_dict(
            "SELECT * FROM agent_logs ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset)
        )
    
    def get_quantum_jobs(self, limit: int = 20, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch quantum jobs, optionally filtered by status."""
        if status:
            return self.query_dict(
                "SELECT * FROM quantum_jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit)
            )
        return self.query_dict(
            "SELECT * FROM quantum_jobs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
    
    def get_pentest_results(self, test_id: str) -> Optional[Dict[str, Any]]:
        """Fetch pentest results by ID."""
        result = self.query_dict(
            "SELECT * FROM pentest_runs WHERE test_id=?",
            (test_id,)
        )
        return result[0] if result else None
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
