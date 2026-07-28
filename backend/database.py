"""
JAKAL DuckDB Manager – Expanded Schema
Includes original tables + scopes, insurance, assessment_reports,
compliance_checkpoints, and RFP support for CPENT-aligned workflows.
"""

import duckdb
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


class DuckDBManager:
    def __init__(self, db_path: str = "jakal.duckdb"):
        self.conn = duckdb.connect(db_path)
        self.db_path = db_path

    def initialize_schema(self):
        """Initialize all required tables and sequences."""

        # Sequences
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_logs START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_jobs START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_pentest START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_findings START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_scopes START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_insurance START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_assessment START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_rfp START 1")
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_compliance START 1")

        # Agent logs
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

        # Quantum jobs
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

        # Authorized scopes & Rules of Engagement
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS scopes (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_scopes'),
            client_name VARCHAR,
            scope_definition VARCHAR,
            start_date TIMESTAMP,
            end_date TIMESTAMP,
            roe_document_path VARCHAR,
            status VARCHAR DEFAULT 'active',
            created_at TIMESTAMP DEFAULT now()
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
            status VARCHAR DEFAULT 'active',
            notes VARCHAR,
            created_at TIMESTAMP DEFAULT now()
        )
        """)

        # Assessment reports
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS assessment_reports (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_assessment'),
            pentest_id INTEGER,
            report_type VARCHAR,
            title VARCHAR,
            content VARCHAR,
            severity_summary VARCHAR,
            created_at TIMESTAMP DEFAULT now()
        )
        """)

        # RFP responses
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS rfp_responses (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_rfp'),
            rfp_title VARCHAR,
            client_name VARCHAR,
            methodology VARCHAR,
            tools_list VARCHAR,
            legal_posture VARCHAR,
            insurance_summary VARCHAR,
            content VARCHAR,
            status VARCHAR DEFAULT 'draft',
            created_at TIMESTAMP DEFAULT now()
        )
        """)

        # Continuous compliance checkpoints
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS compliance_checkpoints (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_compliance'),
            checkpoint_type VARCHAR,
            status VARCHAR,
            details VARCHAR,
            operator_id VARCHAR,
            created_at TIMESTAMP DEFAULT now()
        )
        """)

        self.conn.commit()
        print("[DuckDB] Schema initialized (scopes, insurance, assessment, RFP, compliance included).")

    # ------------------------------------------------------------------
    # Core helpers
    # ------------------------------------------------------------------

    def insert_log(self, log_data: Dict[str, Any]) -> None:
        """Insert agent telemetry / authorization log entry."""
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
                json.dumps(log_data.get("details", {})),
            ),
        )
        self.conn.commit()

    def insert_pentest(self, data: Dict[str, Any]) -> int:
        """Insert a new pentest run and return its id."""
        self.conn.execute(
            """
            INSERT INTO pentest_runs
            (target, scan_type, recon_results, attack_mappings, staged_exploits, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("target"),
                data.get("scan_type"),
                json.dumps(data.get("recon_results", {})),
                json.dumps(data.get("attack_mappings", {})),
                json.dumps(data.get("staged_exploits", {})),
                data.get("status", "awaiting_approval"),
                data.get("created_at", datetime.utcnow()),
            ),
        )
        self.conn.commit()
        # Return last inserted id
        result = self.conn.execute("SELECT currval('seq_pentest')").fetchone()
        return result[0] if result else -1

    def query(self, sql: str, params: Tuple = ()) -> List[Tuple]:
        """Execute SELECT query and return rows."""
        return self.conn.execute(sql, params).fetchall()

    def execute(self, sql: str, params: Tuple = ()) -> None:
        """Execute a non-SELECT statement."""
        self.conn.execute(sql, params)
        self.conn.commit()

    # ------------------------------------------------------------------
    # Scope & Insurance helpers
    # ------------------------------------------------------------------

    def add_scope(
        self,
        client_name: str,
        scope_definition: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        roe_path: str = "",
    ) -> int:
        self.conn.execute(
            """
            INSERT INTO scopes (client_name, scope_definition, start_date, end_date, roe_document_path, status)
            VALUES (?, ?, ?, ?, ?, 'active')
            """,
            (
                client_name,
                scope_definition,
                start_date or datetime.utcnow(),
                end_date,
                roe_path,
            ),
        )
        self.conn.commit()
        result = self.conn.execute("SELECT currval('seq_scopes')").fetchone()
        return result[0] if result else -1

    def add_insurance(
        self,
        policy_number: str,
        provider: str,
        coverage_amount: float,
        expiry: datetime,
        notes: str = "",
    ) -> int:
        self.conn.execute(
            """
            INSERT INTO insurance_policies
            (policy_number, provider, coverage_amount, expiry, status, notes)
            VALUES (?, ?, ?, ?, 'active', ?)
            """,
            (policy_number, provider, coverage_amount, expiry, notes),
        )
        self.conn.commit()
        result = self.conn.execute("SELECT currval('seq_insurance')").fetchone()
        return result[0] if result else -1

    def close(self):
        self.conn.close()
