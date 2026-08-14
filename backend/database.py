"""
JAKAL Database Layer - DuckDB (local, embedded, zero-cost)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import duckdb

logger = logging.getLogger(__name__)


class DuckDBManager:
    def __init__(self, db_path: str = "jakal.duckdb"):
        self.db_path = db_path
        self.conn = duckdb.connect(db_path)
        self.initialize_schema()

    def initialize_schema(self):
        c = self.conn

        c.execute("CREATE SEQUENCE IF NOT EXISTS seq_logs START 1")
        c.execute("CREATE SEQUENCE IF NOT EXISTS seq_jobs START 1")
        c.execute("CREATE SEQUENCE IF NOT EXISTS seq_pentest START 1")
        c.execute("CREATE SEQUENCE IF NOT EXISTS seq_findings START 1")
        c.execute("CREATE SEQUENCE IF NOT EXISTS seq_scopes START 1")
        c.execute("CREATE SEQUENCE IF NOT EXISTS seq_insurance START 1")
        c.execute("CREATE SEQUENCE IF NOT EXISTS seq_reports START 1")

        c.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_logs'),
            timestamp TIMESTAMP DEFAULT now(),
            event VARCHAR,
            action VARCHAR,
            status VARCHAR,
            operator_id VARCHAR,
            details VARCHAR
        )
        """)

        c.execute("""
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

        c.execute("""
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

        c.execute("""
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

        c.execute("""
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

        c.execute("""
        CREATE TABLE IF NOT EXISTS insurance_policies (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_insurance'),
            policy_number VARCHAR,
            provider VARCHAR,
            coverage_amount DECIMAL,
            expiry TIMESTAMP,
            status VARCHAR DEFAULT 'active'
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS assessment_reports (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_reports'),
            pentest_id INTEGER,
            report_type VARCHAR,
            content VARCHAR,
            created_at TIMESTAMP DEFAULT now()
        )
        """)

        self.conn.commit()
        logger.info("Schema initialized at %s", self.db_path)

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------

    def insert_log(self, log_data: Dict[str, Any]):
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
                json.dumps(log_data.get("details", {}), default=str),
            ),
        )
        self.conn.commit()

    def query(self, sql: str, params: tuple = ()):
        return self.conn.execute(sql, params).fetchall()

    def insert_pentest(self, data: Dict[str, Any]) -> int:
        self.conn.execute(
            """
            INSERT INTO pentest_runs
                (target, scan_type, recon_results, attack_mappings, staged_exploits, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("target"),
                data.get("scan_type"),
                json.dumps(data.get("recon_results", {}), default=str),
                json.dumps(data.get("attack_mappings", []), default=str),
                json.dumps(data.get("staged_exploits", []), default=str),
                data.get("status", "created"),
            ),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_pentest')").fetchone()
        return row[0] if row else -1

    def add_scope(
        self,
        client_name: str,
        scope_definition: str,
        start_date: datetime,
        end_date: datetime,
        roe_document_path: Optional[str] = None,
    ) -> int:
        """
        scope_definition: comma-separated CIDRs and/or domain suffixes,
        e.g. "203.0.113.0/24, client-staging.example.com"
        """
        self.conn.execute(
            """
            INSERT INTO scopes (client_name, scope_definition, start_date, end_date, roe_document_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            (client_name, scope_definition, start_date, end_date, roe_document_path),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_scopes')").fetchone()
        return row[0] if row else -1

    def add_insurance_policy(
        self, policy_number: str, provider: str, coverage_amount: float, expiry: datetime
    ) -> int:
        self.conn.execute(
            """
            INSERT INTO insurance_policies (policy_number, provider, coverage_amount, expiry)
            VALUES (?, ?, ?, ?)
            """,
            (policy_number, provider, coverage_amount, expiry),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_insurance')").fetchone()
        return row[0] if row else -1

    def close(self):
        self.conn.close()
