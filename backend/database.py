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
            timestamp TIMESTAMPTZ DEFAULT now(),
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
            created_at TIMESTAMPTZ DEFAULT now(),
            completed_at TIMESTAMPTZ
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
            created_at TIMESTAMPTZ DEFAULT now(),
            completed_at TIMESTAMPTZ
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
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS scopes (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_scopes'),
            client_name VARCHAR,
            scope_definition VARCHAR,
            start_date TIMESTAMPTZ,
            end_date TIMESTAMPTZ,
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
            expiry TIMESTAMPTZ,
            status VARCHAR DEFAULT 'active'
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS assessment_reports (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_reports'),
            pentest_id INTEGER,
            report_type VARCHAR,
            content VARCHAR,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """)

        # --- VM Orchestrator: local lab/sandbox containers ---
        c.execute("CREATE SEQUENCE IF NOT EXISTS seq_sandboxes START 1")
        c.execute("""
        CREATE TABLE IF NOT EXISTS sandboxes (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_sandboxes'),
            sandbox_id VARCHAR,
            container_id VARCHAR,
            container_name VARCHAR UNIQUE,
            name VARCHAR,
            image VARCHAR,
            status VARCHAR,
            operator_id VARCHAR,
            created_at TIMESTAMPTZ DEFAULT now(),
            destroyed_at TIMESTAMPTZ
        )
        """)

        # --- Quantum Compliance Axiom: framework coverage reports ---
        c.execute("CREATE SEQUENCE IF NOT EXISTS seq_compliance START 1")
        c.execute("""
        CREATE TABLE IF NOT EXISTS compliance_reports (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_compliance'),
            framework VARCHAR,
            scope_id INTEGER,
            content VARCHAR,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """)

        # --- Advanced EDR/MDR: playbook library + execution tracking ---
        c.execute("CREATE SEQUENCE IF NOT EXISTS seq_playbooks START 1")
        c.execute("""
        CREATE TABLE IF NOT EXISTS playbooks (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_playbooks'),
            key VARCHAR UNIQUE,
            name VARCHAR,
            category VARCHAR,
            steps VARCHAR,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """)

        c.execute("CREATE SEQUENCE IF NOT EXISTS seq_playbook_exec START 1")
        c.execute("""
        CREATE TABLE IF NOT EXISTS playbook_executions (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_playbook_exec'),
            playbook_id INTEGER,
            context VARCHAR,
            operator_id VARCHAR,
            status VARCHAR DEFAULT 'in_progress',
            step_log VARCHAR DEFAULT '[]',
            started_at TIMESTAMPTZ DEFAULT now(),
            completed_at TIMESTAMPTZ
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

    # ------------------------------------------------------------------
    # VM Orchestrator
    # ------------------------------------------------------------------

    def insert_sandbox(self, record: Dict[str, Any]) -> int:
        self.conn.execute(
            """
            INSERT INTO sandboxes (sandbox_id, container_id, container_name, name, image, status, operator_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("sandbox_id"), record.get("container_id"), record.get("container_name"),
                record.get("name"), record.get("image"), record.get("status", "running"),
                record.get("operator_id"),
            ),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_sandboxes')").fetchone()
        return row[0] if row else -1

    def update_sandbox_status(self, container_name: str, status: str):
        if status == "destroyed":
            self.conn.execute(
                "UPDATE sandboxes SET status = ?, destroyed_at = now() WHERE container_name = ?",
                (status, container_name),
            )
        else:
            self.conn.execute(
                "UPDATE sandboxes SET status = ? WHERE container_name = ?", (status, container_name)
            )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Quantum Compliance Axiom
    # ------------------------------------------------------------------

    def insert_compliance_report(self, framework: str, scope_id: Optional[int], content: Dict[str, Any]) -> int:
        self.conn.execute(
            "INSERT INTO compliance_reports (framework, scope_id, content) VALUES (?, ?, ?)",
            (framework, scope_id, json.dumps(content, default=str)),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_compliance')").fetchone()
        return row[0] if row else -1

    # ------------------------------------------------------------------
    # Advanced EDR/MDR: playbooks
    # ------------------------------------------------------------------

    def insert_playbook(self, key: str, name: str, category: str, steps: list) -> int:
        self.conn.execute(
            "INSERT INTO playbooks (key, name, category, steps) VALUES (?, ?, ?, ?)",
            (key, name, category, json.dumps(steps)),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_playbooks')").fetchone()
        return row[0] if row else -1

    def get_playbook_by_key(self, key: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT id, key, name, category, steps FROM playbooks WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        return {"id": row[0], "key": row[1], "name": row[2], "category": row[3], "steps": json.loads(row[4])}

    def list_playbooks(self) -> list:
        rows = self.conn.execute("SELECT id, key, name, category, steps FROM playbooks ORDER BY id").fetchall()
        return [{"id": r[0], "key": r[1], "name": r[2], "category": r[3], "steps": json.loads(r[4])} for r in rows]

    def insert_playbook_execution(self, playbook_id: int, context: str, operator_id: str) -> int:
        self.conn.execute(
            "INSERT INTO playbook_executions (playbook_id, context, operator_id) VALUES (?, ?, ?)",
            (playbook_id, context, operator_id),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_playbook_exec')").fetchone()
        return row[0] if row else -1

    def update_playbook_execution_step(self, execution_id: int, step_index: int, notes: str) -> Dict[str, Any]:
        row = self.conn.execute(
            "SELECT step_log FROM playbook_executions WHERE id = ?", (execution_id,)
        ).fetchone()
        if not row:
            return {"status": "error", "error": "execution not found"}
        log = json.loads(row[0])
        log.append({"step_index": step_index, "notes": notes, "completed_at": datetime.now(timezone.utc).isoformat()})
        self.conn.execute(
            "UPDATE playbook_executions SET step_log = ? WHERE id = ?", (json.dumps(log), execution_id)
        )
        self.conn.commit()
        return {"status": "ok", "execution_id": execution_id, "step_log": log}

    def finish_playbook_execution(self, execution_id: int) -> Dict[str, Any]:
        self.conn.execute(
            "UPDATE playbook_executions SET status = 'completed', completed_at = now() WHERE id = ?",
            (execution_id,),
        )
        self.conn.commit()
        return {"status": "completed", "execution_id": execution_id}

    def close(self):
        self.conn.close()
