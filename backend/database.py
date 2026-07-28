# backend/database.py
import duckdb
import json
from datetime import datetime

class DuckDBManager:
    def __init__(self, db_path="jakal.duckdb"):
        self.conn = duckdb.connect(db_path)
        self.db_path = db_path

    def initialize_schema(self):
        """Initialize all required tables and sequences."""
        
        # Sequence generators
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_logs START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_jobs START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_pentest START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_findings START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_scopes START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_insurance START 1")
        
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
            created_at TIMESTAMP DEFAULT now(),
            completed_at TIMESTAMP
        )
        """)

        # Penetration test runs
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS pentest_runs (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_pentest'),
            target VARCHAR,
            scan_type VARCHAR,
            recon_results VARCHAR,
            attack_mappings VARCHAR,
            staged_exploits VARCHAR,
            status VARCHAR,
            created_at TIMESTAMP DEFAULT now(),
            completed_at TIMESTAMP
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
            created_at TIMESTAMP DEFAULT now()
        )
        """)

        # Authorized scopes & RoE
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS scopes (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_scopes'),
            client_name VARCHAR,
            scope_definition VARCHAR,
            start_date TIMESTAMP,
            end_date TIMESTAMP,
            roe_document_path VARCHAR,
            status VARCHAR DEFAULT 'active'
        )
        """)

        # Insurance policies
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS insurance_policies (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_insurance'),
            policy_number VARCHAR,
            provider VARCHAR,
            coverage_amount DECIMAL,
            expiry TIMESTAMP,
            status VARCHAR DEFAULT 'active'
        )
        """)

        # Assessment reports & RFP responses (add as needed)
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS assessment_reports (
            id INTEGER PRIMARY KEY,
            pentest_id INTEGER,
            report_type VARCHAR,
            content VARCHAR,
            created_at TIMESTAMP DEFAULT now()
        )
        """)

        self.conn.commit()

    def insert_log(self, log_data):
        """Insert agent telemetry log entry."""
        self.conn.execute(
            """
            INSERT INTO agent_logs (event, action, status, operator_id, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                log_data.get("event"),
                log_data.get("action"),
                log_data.get("status"),
                log_data.get("operator_id"),
                json.dumps(log_data.get("details", {}))
            )
        )
        self.conn.commit()

    def query(self, sql, params=()):
        """Execute SELECT query."""
        result = self.conn.execute(sql, params).fetchall()
        return result

    def close(self):
        self.conn.close()
