"""
JAKAL Database Layer - DuckDB (local, embedded, zero-cost)

Schema version: 2.3
  v1.0 - agent_logs, quantum_jobs, pentest_runs, findings, scopes,
          insurance_policies, assessment_reports
  v2.0 - sandboxes, compliance_reports, playbooks, playbook_executions
  v2.1 - pqc_audit_log, encryption_keys, payload_executions,
          network_map, vuln_db, threat_intel
  v2.2 - fabric_modules, fabric_events, zt_posture_assessments
  v2.3 - operators, attack_mappings, compliance_checkpoints, rfp_responses,
          approval_requests (human-in-the-loop oversight gate)
          Salvaged/hardened from the abandoned `master` branch's
          phase1_database.py design before that branch was retired --
          real column ideas kept, weak points (substring scope matching,
          no PQC signing) fixed against the v2.1+ authorization/PQC layer.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import duckdb

logger = logging.getLogger(__name__)


class DuckDBManager:
    def __init__(self, db_path: str = "jakal.duckdb"):
        self.db_path = db_path
        self.conn = duckdb.connect(db_path)
        self.initialize_schema()

    def initialize_schema(self):
        c = self.conn

        # ── Sequences ─────────────────────────────────────────────────────
        for seq in [
            "seq_logs", "seq_jobs", "seq_pentest", "seq_findings",
            "seq_scopes", "seq_insurance", "seq_reports", "seq_sandboxes",
            "seq_compliance", "seq_playbooks", "seq_playbook_exec",
            # v2.1 sequences
            "seq_pqc_audit", "seq_enc_keys", "seq_payload_exec",
            "seq_network_map", "seq_vuln_db", "seq_threat_intel",
            # v2.2 Unified Security Fabric sequences
            "seq_fabric_mod", "seq_fabric_evt", "seq_posture",
            # v2.3 sequences
            "seq_operators", "seq_attack_map", "seq_compliance_chk",
            "seq_rfp", "seq_approval",
        ]:
            c.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq} START 1")

        # ── v1.0 Tables ───────────────────────────────────────────────────

        c.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id          INTEGER PRIMARY KEY DEFAULT nextval('seq_logs'),
            timestamp   TIMESTAMPTZ DEFAULT now(),
            event       VARCHAR,
            action      VARCHAR,
            status      VARCHAR,
            operator_id VARCHAR,
            details     VARCHAR
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS quantum_jobs (
            id            INTEGER PRIMARY KEY DEFAULT nextval('seq_jobs'),
            job_id        VARCHAR UNIQUE,
            circuit_name  VARCHAR,
            backend       VARCHAR,
            shots         INTEGER,
            result        VARCHAR,
            status        VARCHAR,
            created_at    TIMESTAMPTZ DEFAULT now(),
            completed_at  TIMESTAMPTZ
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS pentest_runs (
            id              INTEGER PRIMARY KEY DEFAULT nextval('seq_pentest'),
            target          VARCHAR,
            scan_type       VARCHAR,
            recon_results   VARCHAR,
            attack_mappings VARCHAR,
            staged_exploits VARCHAR,
            status          VARCHAR,
            created_at      TIMESTAMPTZ DEFAULT now(),
            completed_at    TIMESTAMPTZ
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS findings (
            id               INTEGER PRIMARY KEY DEFAULT nextval('seq_findings'),
            pentest_id       INTEGER,
            severity         VARCHAR,
            title            VARCHAR,
            description      VARCHAR,
            attack_technique VARCHAR,
            remediation      VARCHAR,
            created_at       TIMESTAMPTZ DEFAULT now()
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS scopes (
            id                INTEGER PRIMARY KEY DEFAULT nextval('seq_scopes'),
            client_name       VARCHAR,
            scope_definition  VARCHAR,
            start_date        TIMESTAMPTZ,
            end_date          TIMESTAMPTZ,
            roe_document_path VARCHAR,
            status            VARCHAR DEFAULT 'active'
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS insurance_policies (
            id              INTEGER PRIMARY KEY DEFAULT nextval('seq_insurance'),
            policy_number   VARCHAR,
            provider        VARCHAR,
            coverage_amount DECIMAL,
            expiry          TIMESTAMPTZ,
            status          VARCHAR DEFAULT 'active'
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS assessment_reports (
            id          INTEGER PRIMARY KEY DEFAULT nextval('seq_reports'),
            pentest_id  INTEGER,
            report_type VARCHAR,
            content     VARCHAR,
            created_at  TIMESTAMPTZ DEFAULT now()
        )
        """)

        # ── v2.0 Tables ───────────────────────────────────────────────────

        c.execute("""
        CREATE TABLE IF NOT EXISTS sandboxes (
            id             INTEGER PRIMARY KEY DEFAULT nextval('seq_sandboxes'),
            sandbox_id     VARCHAR,
            container_id   VARCHAR,
            container_name VARCHAR UNIQUE,
            name           VARCHAR,
            image          VARCHAR,
            status         VARCHAR,
            operator_id    VARCHAR,
            created_at     TIMESTAMPTZ DEFAULT now(),
            destroyed_at   TIMESTAMPTZ
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS compliance_reports (
            id         INTEGER PRIMARY KEY DEFAULT nextval('seq_compliance'),
            framework  VARCHAR,
            scope_id   INTEGER,
            content    VARCHAR,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS playbooks (
            id         INTEGER PRIMARY KEY DEFAULT nextval('seq_playbooks'),
            key        VARCHAR UNIQUE,
            name       VARCHAR,
            category   VARCHAR,
            steps      VARCHAR,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS playbook_executions (
            id           INTEGER PRIMARY KEY DEFAULT nextval('seq_playbook_exec'),
            playbook_id  INTEGER,
            context      VARCHAR,
            operator_id  VARCHAR,
            status       VARCHAR DEFAULT 'in_progress',
            step_log     VARCHAR DEFAULT '[]',
            started_at   TIMESTAMPTZ DEFAULT now(),
            completed_at TIMESTAMPTZ
        )
        """)

        # ── v2.1 Tables ───────────────────────────────────────────────────

        # PQC-signed immutable audit log
        c.execute("""
        CREATE TABLE IF NOT EXISTS pqc_audit_log (
            id            INTEGER PRIMARY KEY DEFAULT nextval('seq_pqc_audit'),
            entry_id      VARCHAR UNIQUE NOT NULL,   -- UUID per entry
            timestamp     TIMESTAMPTZ DEFAULT now(),
            agent_id      VARCHAR NOT NULL,
            operator_id   VARCHAR NOT NULL,
            action_type   VARCHAR NOT NULL,          -- e.g. authorization, pentest, crypto_op
            action_detail VARCHAR NOT NULL,          -- JSON blob of action payload
            payload_hash  VARCHAR NOT NULL,          -- SHA3-256 hex of action_detail
            pqc_signature VARCHAR NOT NULL,          -- ML-DSA-65 signature hex
            algorithm     VARCHAR NOT NULL,          -- 'ML-DSA-65' | 'Ed25519'
            public_key    VARCHAR NOT NULL,          -- signer public key hex
            chain_index   INTEGER DEFAULT 0,        -- position in audit chain
            prev_hash     VARCHAR                    -- SHA3-256 of previous entry signature (chain link)
        )
        """)

        # Encryption key metadata (never store raw private keys)
        c.execute("""
        CREATE TABLE IF NOT EXISTS encryption_keys (
            id            INTEGER PRIMARY KEY DEFAULT nextval('seq_enc_keys'),
            key_id        VARCHAR UNIQUE NOT NULL,   -- UUID
            created_at    TIMESTAMPTZ DEFAULT now(),
            algorithm     VARCHAR NOT NULL,          -- AES-256-GCM | ChaCha20-Poly1305 | RSA-4096-OAEP
            key_purpose   VARCHAR NOT NULL,          -- session | report | backup | kek
            operator_id   VARCHAR NOT NULL,
            status        VARCHAR DEFAULT 'active',  -- active | rotated | revoked
            rotated_at    TIMESTAMPTZ,
            revoked_at    TIMESTAMPTZ,
            public_key_pem VARCHAR,                  -- RSA public key PEM (asymmetric only)
            key_wrapping_algo VARCHAR,               -- algorithm used to wrap the session key
            wrapped_key   VARCHAR,                   -- symmetric key wrapped with RSA-OAEP (hex)
            salt_hex      VARCHAR,                   -- KDF salt if PBKDF2-derived
            metadata      VARCHAR DEFAULT '{}'       -- JSON extra metadata
        )
        """)

        # Payload execution tracking
        c.execute("""
        CREATE TABLE IF NOT EXISTS payload_executions (
            id            INTEGER PRIMARY KEY DEFAULT nextval('seq_payload_exec'),
            execution_id  VARCHAR UNIQUE NOT NULL,
            pentest_id    INTEGER,
            target        VARCHAR NOT NULL,
            phase         VARCHAR NOT NULL,          -- recon_passive | recon_active | enumeration | …
            command       VARCHAR NOT NULL,          -- actual command run
            technique_id  VARCHAR,                  -- MITRE T-number e.g. T1595
            tool          VARCHAR,                  -- nmap | nuclei | etc.
            risk_level    VARCHAR,                  -- LOW | MEDIUM | HIGH
            operator_id   VARCHAR NOT NULL,
            authorized    BOOLEAN DEFAULT false,     -- passed authorization gate?
            stdout        VARCHAR,
            stderr        VARCHAR,
            exit_code     INTEGER,
            started_at    TIMESTAMPTZ DEFAULT now(),
            completed_at  TIMESTAMPTZ,
            pqc_signed    BOOLEAN DEFAULT false,     -- was result PQC-signed?
            pqc_entry_id  VARCHAR                   -- FK to pqc_audit_log.entry_id
        )
        """)

        # Network mapping / asset inventory
        c.execute("""
        CREATE TABLE IF NOT EXISTS network_map (
            id            INTEGER PRIMARY KEY DEFAULT nextval('seq_network_map'),
            discovered_at TIMESTAMPTZ DEFAULT now(),
            pentest_id    INTEGER,
            ip_address    VARCHAR NOT NULL,
            hostname      VARCHAR,
            mac_address   VARCHAR,
            os_fingerprint VARCHAR,
            open_ports    VARCHAR DEFAULT '[]',      -- JSON array of {port, proto, service, version}
            tags          VARCHAR DEFAULT '[]',      -- JSON array of tags e.g. ["web","db"]
            risk_score    DECIMAL DEFAULT 0.0,
            last_seen     TIMESTAMPTZ DEFAULT now(),
            notes         VARCHAR
        )
        """)

        # Vulnerability database entries (local CVE / custom findings library)
        c.execute("""
        CREATE TABLE IF NOT EXISTS vuln_db (
            id              INTEGER PRIMARY KEY DEFAULT nextval('seq_vuln_db'),
            vuln_id         VARCHAR UNIQUE NOT NULL, -- CVE-YYYY-NNNNN or JAKAL-custom-id
            title           VARCHAR NOT NULL,
            description     VARCHAR NOT NULL,
            severity        VARCHAR NOT NULL,        -- CRITICAL | HIGH | MEDIUM | LOW | INFO
            cvss_score      DECIMAL,
            cvss_vector     VARCHAR,
            cwe_id          VARCHAR,                -- CWE-XXX
            mitre_technique VARCHAR,                -- T-number
            affected_products VARCHAR DEFAULT '[]', -- JSON array
            patch_available BOOLEAN DEFAULT false,
            patch_reference VARCHAR,
            exploit_available BOOLEAN DEFAULT false,
            exploit_reference VARCHAR,
            created_at      TIMESTAMPTZ DEFAULT now(),
            updated_at      TIMESTAMPTZ DEFAULT now(),
            source          VARCHAR DEFAULT 'manual' -- manual | nvd | cisa_kev | custom
        )
        """)

        # Threat intelligence — IOCs, TTPs, threat actors
        c.execute("""
        CREATE TABLE IF NOT EXISTS threat_intel (
            id           INTEGER PRIMARY KEY DEFAULT nextval('seq_threat_intel'),
            ingested_at  TIMESTAMPTZ DEFAULT now(),
            feed_source  VARCHAR NOT NULL,           -- e.g. MISP | STIX | manual | CISA_KEV
            intel_type   VARCHAR NOT NULL,           -- IOC | TTP | actor | campaign | malware
            indicator    VARCHAR NOT NULL,           -- IP, domain, hash, technique ID, actor name
            indicator_type VARCHAR,                  -- ip | domain | hash_sha256 | url | email | technique
            confidence   INTEGER DEFAULT 50,         -- 0-100
            severity     VARCHAR DEFAULT 'MEDIUM',
            tlp          VARCHAR DEFAULT 'WHITE',    -- TLP:WHITE | GREEN | AMBER | RED
            tags         VARCHAR DEFAULT '[]',       -- JSON array
            first_seen   TIMESTAMPTZ,
            last_seen    TIMESTAMPTZ,
            expiry       TIMESTAMPTZ,
            context      VARCHAR DEFAULT '{}',       -- JSON — actor, campaign, malware family, etc.
            active       BOOLEAN DEFAULT true
        )
        """)

        # ── v2.2 Tables — Unified Security Fabric ─────────────────────────

        # One row per Fabric capability (MDR, Zero Trust, SASE, PAM, DNS, Email, DLP)
        c.execute("""
        CREATE TABLE IF NOT EXISTS fabric_modules (
            id          INTEGER PRIMARY KEY DEFAULT nextval('seq_fabric_mod'),
            module_key  VARCHAR UNIQUE NOT NULL,    -- mdr | zero_trust | sase | pam | dns_filter | email_security | dlp
            label       VARCHAR NOT NULL,
            pillar      VARCHAR NOT NULL,           -- NSA/CISA Zero Trust pillar
            icon        VARCHAR,
            description  VARCHAR,
            maturity    VARCHAR DEFAULT 'Initial',  -- Traditional | Initial | Advanced | Optimal
            status      VARCHAR DEFAULT 'active',   -- active | degraded | disabled
            controls    VARCHAR DEFAULT '[]',       -- JSON array of control strings
            metrics     VARCHAR DEFAULT '{}',       -- JSON metrics blob
            updated_at  TIMESTAMPTZ DEFAULT now()
        )
        """)

        # Fabric event stream (unified across all capabilities)
        c.execute("""
        CREATE TABLE IF NOT EXISTS fabric_events (
            id          INTEGER PRIMARY KEY DEFAULT nextval('seq_fabric_evt'),
            event_id    VARCHAR UNIQUE NOT NULL,
            timestamp   TIMESTAMPTZ DEFAULT now(),
            module_key  VARCHAR NOT NULL,
            event_type  VARCHAR NOT NULL,           -- maturity_change | status_change | detection | policy | alert
            detail      VARCHAR,
            severity    VARCHAR DEFAULT 'info',     -- info | low | medium | high | critical
            operator_id VARCHAR
        )
        """)

        # Zero Trust posture snapshots (trend analysis)
        c.execute("""
        CREATE TABLE IF NOT EXISTS zt_posture_assessments (
            id            INTEGER PRIMARY KEY DEFAULT nextval('seq_posture'),
            assessment_id VARCHAR UNIQUE NOT NULL,
            assessed_at   TIMESTAMPTZ DEFAULT now(),
            overall_score DECIMAL,
            overall_level VARCHAR,                  -- Traditional | Initial | Advanced | Optimal
            by_pillar     VARCHAR DEFAULT '{}',     -- JSON per-pillar breakdown
            operator_id   VARCHAR
        )
        """)

        # ── v2.3 Tables — real-demo readiness ─────────────────────────────
        # Salvaged from the retired `master` branch's phase1_database.py
        # design, hardened to fit the v2.1+ authorization/PQC layer (that
        # draft had its own ad-hoc scope-substring check and no signing --
        # here these tables are populated/consumed through the existing
        # check_authorization_and_scope() + PQCAuditManager path instead).

        # Operators — the people/service-accounts allowed to drive JAKAL.
        c.execute("""
        CREATE TABLE IF NOT EXISTS operators (
            id           INTEGER PRIMARY KEY DEFAULT nextval('seq_operators'),
            operator_id  VARCHAR UNIQUE NOT NULL,
            email        VARCHAR UNIQUE,
            display_name VARCHAR,
            role         VARCHAR DEFAULT 'operator',   -- operator | lead | admin | approver
            active       BOOLEAN DEFAULT true,
            last_login   TIMESTAMPTZ,
            created_at   TIMESTAMPTZ DEFAULT now()
        )
        """)

        # MITRE ATT&CK mappings — links a finding to the technique(s) it
        # demonstrates. Kept separate from `findings` (v1.0) so one finding
        # can map to multiple techniques/sub-techniques without denormalizing
        # findings itself.
        c.execute("""
        CREATE TABLE IF NOT EXISTS attack_mappings (
            id               INTEGER PRIMARY KEY DEFAULT nextval('seq_attack_map'),
            pentest_id       INTEGER,
            finding_id       INTEGER,
            tactic           VARCHAR NOT NULL,          -- e.g. Credential Access
            technique_id     VARCHAR NOT NULL,          -- e.g. T1110
            technique_name   VARCHAR NOT NULL,
            sub_technique_id VARCHAR,                   -- e.g. T1110.002
            confidence       DECIMAL DEFAULT 0.8,
            mapped_at        TIMESTAMPTZ DEFAULT now()
        )
        """)

        # Compliance checkpoints — one immutable row per authorization
        # decision, hash-chained to the previous row so the sequence itself
        # is tamper-evident (separate from, and coarser-grained than, the
        # full PQC-signed pqc_audit_log -- this is the fast "did engagement
        # X stay in-bounds the whole time" report source).
        c.execute("""
        CREATE TABLE IF NOT EXISTS compliance_checkpoints (
            id                  INTEGER PRIMARY KEY DEFAULT nextval('seq_compliance_chk'),
            timestamp           TIMESTAMPTZ DEFAULT now(),
            action_type         VARCHAR NOT NULL,
            operator_id         VARCHAR NOT NULL,
            target              VARCHAR,
            authorization_result VARCHAR,               -- granted | denied
            scope_status        VARCHAR,
            insurance_status    VARCHAR,
            allowed_to_proceed  BOOLEAN,
            pqc_entry_id        VARCHAR,                 -- FK to pqc_audit_log.entry_id
            hash_chain          VARCHAR,                 -- sha3-256(prev hash_chain + this row)
            prev_hash           VARCHAR
        )
        """)

        # RFP responses — client-facing proposal boilerplate, useful for a
        # sales/demo showcase of the platform's own methodology.
        c.execute("""
        CREATE TABLE IF NOT EXISTS rfp_responses (
            id                   INTEGER PRIMARY KEY DEFAULT nextval('seq_rfp'),
            client_name          VARCHAR NOT NULL,
            methodology          VARCHAR,
            tools_list           VARCHAR DEFAULT '[]',   -- JSON array
            timeline             VARCHAR,
            pricing              VARCHAR,
            insurance_statement  VARCHAR,
            sample_report_path   VARCHAR,
            created_at           TIMESTAMPTZ DEFAULT now()
        )
        """)

        # Human Approval Gate — every HIGH/CRITICAL-risk staged payload
        # (from AIPPayloadGenerator or ExploitAgent) lands here as 'pending'
        # before it may be marked executable. This table is the persistence
        # layer behind security_agents/exploit_agent.py's approval flow and
        # AIPPayloadGenerator's auto-staging of high-risk plans.
        c.execute("""
        CREATE TABLE IF NOT EXISTS approval_requests (
            id              INTEGER PRIMARY KEY DEFAULT nextval('seq_approval'),
            request_id      VARCHAR UNIQUE NOT NULL,
            requested_at    TIMESTAMPTZ DEFAULT now(),
            requested_by    VARCHAR NOT NULL,           -- operator_id or agent id
            action_type     VARCHAR NOT NULL,           -- e.g. payload_execution, exploit_staging
            target          VARCHAR,
            phase           VARCHAR,
            technique_id    VARCHAR,
            risk_level      VARCHAR DEFAULT 'MEDIUM',   -- LOW | MEDIUM | HIGH | CRITICAL
            summary         VARCHAR,                    -- human-readable description of what's being requested
            payload_detail  VARCHAR DEFAULT '{}',       -- JSON — the staged command(s)/payload
            status          VARCHAR DEFAULT 'pending',  -- pending | approved | denied | expired
            decided_by      VARCHAR,
            decided_at      TIMESTAMPTZ,
            decision_reason VARCHAR,
            pqc_entry_id    VARCHAR,                    -- FK to pqc_audit_log.entry_id (staging signature)
            expires_at      TIMESTAMPTZ
        )
        """)

        self.conn.commit()
        logger.info("Schema v2.3 initialized at %s", self.db_path)

    # ======================================================================
    # Generic helpers
    # ======================================================================

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

    # ======================================================================
    # VM Orchestrator / Sandboxes
    # ======================================================================

    def insert_sandbox(self, record: Dict[str, Any]) -> int:
        self.conn.execute(
            """
            INSERT INTO sandboxes
                (sandbox_id, container_id, container_name, name, image, status, operator_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("sandbox_id"), record.get("container_id"),
                record.get("container_name"), record.get("name"),
                record.get("image"), record.get("status", "running"),
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

    # ======================================================================
    # Compliance Reports
    # ======================================================================

    def insert_compliance_report(
        self, framework: str, scope_id: Optional[int], content: Dict[str, Any]
    ) -> int:
        self.conn.execute(
            "INSERT INTO compliance_reports (framework, scope_id, content) VALUES (?, ?, ?)",
            (framework, scope_id, json.dumps(content, default=str)),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_compliance')").fetchone()
        return row[0] if row else -1

    # ======================================================================
    # Playbooks (EDR/MDR)
    # ======================================================================

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
        return {
            "id": row[0], "key": row[1], "name": row[2],
            "category": row[3], "steps": json.loads(row[4]),
        }

    def list_playbooks(self) -> list:
        rows = self.conn.execute(
            "SELECT id, key, name, category, steps FROM playbooks ORDER BY id"
        ).fetchall()
        return [
            {"id": r[0], "key": r[1], "name": r[2], "category": r[3], "steps": json.loads(r[4])}
            for r in rows
        ]

    def insert_playbook_execution(self, playbook_id: int, context: str, operator_id: str) -> int:
        self.conn.execute(
            "INSERT INTO playbook_executions (playbook_id, context, operator_id) VALUES (?, ?, ?)",
            (playbook_id, context, operator_id),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_playbook_exec')").fetchone()
        return row[0] if row else -1

    def update_playbook_execution_step(
        self, execution_id: int, step_index: int, notes: str
    ) -> Dict[str, Any]:
        row = self.conn.execute(
            "SELECT step_log FROM playbook_executions WHERE id = ?", (execution_id,)
        ).fetchone()
        if not row:
            return {"status": "error", "error": "execution not found"}
        log = json.loads(row[0])
        log.append({
            "step_index": step_index,
            "notes": notes,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        self.conn.execute(
            "UPDATE playbook_executions SET step_log = ? WHERE id = ?",
            (json.dumps(log), execution_id),
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

    # ======================================================================
    # v2.1 — PQC Audit Log
    # ======================================================================

    def insert_pqc_audit_entry(self, entry: Dict[str, Any]) -> int:
        """
        Insert a PQC-signed audit entry.

        Required keys:
          entry_id, agent_id, operator_id, action_type, action_detail (str JSON),
          payload_hash, pqc_signature, algorithm, public_key
        Optional:
          chain_index (int), prev_hash (str)
        """
        self.conn.execute(
            """
            INSERT INTO pqc_audit_log
                (entry_id, agent_id, operator_id, action_type, action_detail,
                 payload_hash, pqc_signature, algorithm, public_key,
                 chain_index, prev_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["entry_id"],
                entry["agent_id"],
                entry["operator_id"],
                entry["action_type"],
                entry["action_detail"] if isinstance(entry["action_detail"], str)
                    else json.dumps(entry["action_detail"], default=str),
                entry["payload_hash"],
                entry["pqc_signature"],
                entry["algorithm"],
                entry["public_key"],
                entry.get("chain_index", 0),
                entry.get("prev_hash"),
            ),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_pqc_audit')").fetchone()
        return row[0] if row else -1

    def get_pqc_audit_entry(self, entry_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM pqc_audit_log WHERE entry_id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, row))

    def list_pqc_audit_entries(
        self,
        operator_id: Optional[str] = None,
        action_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        where, params = [], []
        if operator_id:
            where.append("operator_id = ?")
            params.append(operator_id)
        if action_type:
            where.append("action_type = ?")
            params.append(action_type)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM pqc_audit_log {clause} ORDER BY id DESC LIMIT ?", params
        ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def count_pqc_entries(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM pqc_audit_log").fetchone()
        return row[0] if row else 0

    # ======================================================================
    # v2.1 — Encryption Key Registry
    # ======================================================================

    def register_encryption_key(self, record: Dict[str, Any]) -> int:
        """
        Store key metadata — NEVER the raw private/symmetric key bytes.

        Required: key_id, algorithm, key_purpose, operator_id
        Optional: public_key_pem, key_wrapping_algo, wrapped_key, salt_hex, metadata
        """
        self.conn.execute(
            """
            INSERT INTO encryption_keys
                (key_id, algorithm, key_purpose, operator_id,
                 public_key_pem, key_wrapping_algo, wrapped_key, salt_hex, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["key_id"],
                record["algorithm"],
                record["key_purpose"],
                record["operator_id"],
                record.get("public_key_pem"),
                record.get("key_wrapping_algo"),
                record.get("wrapped_key"),
                record.get("salt_hex"),
                json.dumps(record.get("metadata", {})),
            ),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_enc_keys')").fetchone()
        return row[0] if row else -1

    def rotate_encryption_key(self, key_id: str) -> bool:
        result = self.conn.execute(
            "UPDATE encryption_keys SET status = 'rotated', rotated_at = now() WHERE key_id = ?",
            (key_id,),
        )
        self.conn.commit()
        return (result.rowcount or 0) > 0

    def revoke_encryption_key(self, key_id: str) -> bool:
        result = self.conn.execute(
            "UPDATE encryption_keys SET status = 'revoked', revoked_at = now() WHERE key_id = ?",
            (key_id,),
        )
        self.conn.commit()
        return (result.rowcount or 0) > 0

    def list_encryption_keys(
        self, operator_id: Optional[str] = None, status: str = "active"
    ) -> List[Dict[str, Any]]:
        where, params = ["status = ?"], [status]
        if operator_id:
            where.append("operator_id = ?")
            params.append(operator_id)
        rows = self.conn.execute(
            f"SELECT key_id, algorithm, key_purpose, operator_id, status, "
            f"created_at, rotated_at, revoked_at, metadata "
            f"FROM encryption_keys WHERE {' AND '.join(where)} ORDER BY id DESC",
            params,
        ).fetchall()
        cols = ["key_id", "algorithm", "key_purpose", "operator_id", "status",
                "created_at", "rotated_at", "revoked_at", "metadata"]
        return [dict(zip(cols, r)) for r in rows]

    # ======================================================================
    # v2.1 — Payload Execution Tracking
    # ======================================================================

    def log_payload_execution(self, record: Dict[str, Any]) -> int:
        """
        Log a payload/command execution for audit and reporting.

        Required: execution_id, target, phase, command, operator_id
        Optional: pentest_id, technique_id, tool, risk_level, authorized,
                  stdout, stderr, exit_code, pqc_signed, pqc_entry_id
        """
        self.conn.execute(
            """
            INSERT INTO payload_executions
                (execution_id, pentest_id, target, phase, command,
                 technique_id, tool, risk_level, operator_id, authorized,
                 stdout, stderr, exit_code, pqc_signed, pqc_entry_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["execution_id"],
                record.get("pentest_id"),
                record["target"],
                record["phase"],
                record["command"],
                record.get("technique_id"),
                record.get("tool"),
                record.get("risk_level", "MEDIUM"),
                record["operator_id"],
                record.get("authorized", False),
                record.get("stdout"),
                record.get("stderr"),
                record.get("exit_code"),
                record.get("pqc_signed", False),
                record.get("pqc_entry_id"),
            ),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_payload_exec')").fetchone()
        return row[0] if row else -1

    def complete_payload_execution(
        self,
        execution_id: str,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = 0,
        pqc_entry_id: Optional[str] = None,
    ):
        self.conn.execute(
            """
            UPDATE payload_executions
            SET stdout = ?, stderr = ?, exit_code = ?, completed_at = now(),
                pqc_signed = ?, pqc_entry_id = ?
            WHERE execution_id = ?
            """,
            (stdout, stderr, exit_code,
             pqc_entry_id is not None, pqc_entry_id, execution_id),
        )
        self.conn.commit()

    def list_payload_executions(
        self,
        pentest_id: Optional[int] = None,
        phase: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        where, params = [], []
        if pentest_id:
            where.append("pentest_id = ?")
            params.append(pentest_id)
        if phase:
            where.append("phase = ?")
            params.append(phase)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM payload_executions {clause} ORDER BY id DESC LIMIT ?", params
        ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    # ======================================================================
    # v2.1 — Network Map / Asset Inventory
    # ======================================================================

    def upsert_network_host(self, record: Dict[str, Any]) -> int:
        """
        Insert or update a discovered host in the network map.
        Uses ip_address as the natural key per pentest.
        """
        existing = self.conn.execute(
            "SELECT id FROM network_map WHERE ip_address = ? AND pentest_id IS NOT DISTINCT FROM ?",
            (record["ip_address"], record.get("pentest_id")),
        ).fetchone()

        if existing:
            self.conn.execute(
                """
                UPDATE network_map
                SET hostname = COALESCE(?, hostname),
                    mac_address = COALESCE(?, mac_address),
                    os_fingerprint = COALESCE(?, os_fingerprint),
                    open_ports = ?,
                    tags = ?,
                    risk_score = ?,
                    last_seen = now(),
                    notes = COALESCE(?, notes)
                WHERE id = ?
                """,
                (
                    record.get("hostname"),
                    record.get("mac_address"),
                    record.get("os_fingerprint"),
                    json.dumps(record.get("open_ports", [])),
                    json.dumps(record.get("tags", [])),
                    record.get("risk_score", 0.0),
                    record.get("notes"),
                    existing[0],
                ),
            )
            self.conn.commit()
            return existing[0]

        self.conn.execute(
            """
            INSERT INTO network_map
                (pentest_id, ip_address, hostname, mac_address, os_fingerprint,
                 open_ports, tags, risk_score, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("pentest_id"),
                record["ip_address"],
                record.get("hostname"),
                record.get("mac_address"),
                record.get("os_fingerprint"),
                json.dumps(record.get("open_ports", [])),
                json.dumps(record.get("tags", [])),
                record.get("risk_score", 0.0),
                record.get("notes"),
            ),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_network_map')").fetchone()
        return row[0] if row else -1

    def get_network_map(self, pentest_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if pentest_id:
            rows = self.conn.execute(
                "SELECT * FROM network_map WHERE pentest_id = ? ORDER BY id", (pentest_id,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM network_map ORDER BY id").fetchall()
        cols = [d[0] for d in self.conn.description]
        result = []
        for r in rows:
            d = dict(zip(cols, r))
            d["open_ports"] = json.loads(d.get("open_ports") or "[]")
            d["tags"] = json.loads(d.get("tags") or "[]")
            result.append(d)
        return result

    # ======================================================================
    # v2.1 — Vulnerability Database
    # ======================================================================

    def upsert_vuln(self, record: Dict[str, Any]) -> int:
        """Insert or update a vulnerability entry. vuln_id is the natural key."""
        existing = self.conn.execute(
            "SELECT id FROM vuln_db WHERE vuln_id = ?", (record["vuln_id"],)
        ).fetchone()

        if existing:
            self.conn.execute(
                """
                UPDATE vuln_db
                SET title = ?, description = ?, severity = ?, cvss_score = ?,
                    cvss_vector = ?, cwe_id = ?, mitre_technique = ?,
                    affected_products = ?, patch_available = ?, patch_reference = ?,
                    exploit_available = ?, exploit_reference = ?, updated_at = now(), source = ?
                WHERE vuln_id = ?
                """,
                (
                    record["title"], record["description"], record["severity"],
                    record.get("cvss_score"), record.get("cvss_vector"),
                    record.get("cwe_id"), record.get("mitre_technique"),
                    json.dumps(record.get("affected_products", [])),
                    record.get("patch_available", False), record.get("patch_reference"),
                    record.get("exploit_available", False), record.get("exploit_reference"),
                    record.get("source", "manual"),
                    record["vuln_id"],
                ),
            )
            self.conn.commit()
            return existing[0]

        self.conn.execute(
            """
            INSERT INTO vuln_db
                (vuln_id, title, description, severity, cvss_score, cvss_vector,
                 cwe_id, mitre_technique, affected_products, patch_available,
                 patch_reference, exploit_available, exploit_reference, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["vuln_id"], record["title"], record["description"],
                record["severity"], record.get("cvss_score"), record.get("cvss_vector"),
                record.get("cwe_id"), record.get("mitre_technique"),
                json.dumps(record.get("affected_products", [])),
                record.get("patch_available", False), record.get("patch_reference"),
                record.get("exploit_available", False), record.get("exploit_reference"),
                record.get("source", "manual"),
            ),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_vuln_db')").fetchone()
        return row[0] if row else -1

    def search_vulns(
        self,
        severity: Optional[str] = None,
        mitre_technique: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        where, params = [], []
        if severity:
            where.append("severity = ?")
            params.append(severity.upper())
        if mitre_technique:
            where.append("mitre_technique = ?")
            params.append(mitre_technique)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM vuln_db {clause} ORDER BY cvss_score DESC NULLS LAST LIMIT ?",
            params,
        ).fetchall()
        cols = [d[0] for d in self.conn.description]
        result = []
        for r in rows:
            d = dict(zip(cols, r))
            d["affected_products"] = json.loads(d.get("affected_products") or "[]")
            result.append(d)
        return result

    # ======================================================================
    # v2.1 — Threat Intelligence
    # ======================================================================

    def ingest_threat_intel(self, record: Dict[str, Any]) -> int:
        """
        Ingest a threat intelligence indicator/entry.

        Required: feed_source, intel_type, indicator
        Optional: indicator_type, confidence, severity, tlp, tags,
                  first_seen, last_seen, expiry, context
        """
        self.conn.execute(
            """
            INSERT INTO threat_intel
                (feed_source, intel_type, indicator, indicator_type,
                 confidence, severity, tlp, tags, first_seen, last_seen,
                 expiry, context, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["feed_source"],
                record["intel_type"],
                record["indicator"],
                record.get("indicator_type"),
                record.get("confidence", 50),
                record.get("severity", "MEDIUM"),
                record.get("tlp", "WHITE"),
                json.dumps(record.get("tags", [])),
                record.get("first_seen"),
                record.get("last_seen"),
                record.get("expiry"),
                json.dumps(record.get("context", {})),
                record.get("active", True),
            ),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_threat_intel')").fetchone()
        return row[0] if row else -1

    def search_threat_intel(
        self,
        indicator: Optional[str] = None,
        intel_type: Optional[str] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        where, params = [], []
        if active_only:
            where.append("active = true")
        if indicator:
            where.append("indicator ILIKE ?")
            params.append(f"%{indicator}%")
        if intel_type:
            where.append("intel_type = ?")
            params.append(intel_type)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM threat_intel {clause} ORDER BY confidence DESC LIMIT ?", params
        ).fetchall()
        cols = [d[0] for d in self.conn.description]
        result = []
        for r in rows:
            d = dict(zip(cols, r))
            d["tags"] = json.loads(d.get("tags") or "[]")
            d["context"] = json.loads(d.get("context") or "{}")
            result.append(d)
        return result

    def expire_threat_intel(self) -> int:
        """Mark expired indicators as inactive. Call periodically."""
        result = self.conn.execute(
            "UPDATE threat_intel SET active = false WHERE expiry < now() AND active = true"
        )
        self.conn.commit()
        return result.rowcount or 0

    def threat_intel_stats(self) -> Dict[str, Any]:
        total = self.conn.execute("SELECT COUNT(*) FROM threat_intel").fetchone()[0]
        active = self.conn.execute("SELECT COUNT(*) FROM threat_intel WHERE active = true").fetchone()[0]
        by_type = self.conn.execute(
            "SELECT intel_type, COUNT(*) FROM threat_intel GROUP BY intel_type ORDER BY 2 DESC"
        ).fetchall()
        by_severity = self.conn.execute(
            "SELECT severity, COUNT(*) FROM threat_intel WHERE active = true "
            "GROUP BY severity ORDER BY 2 DESC"
        ).fetchall()
        return {
            "total": total,
            "active": active,
            "by_type": {r[0]: r[1] for r in by_type},
            "by_severity": {r[0]: r[1] for r in by_severity},
        }

    # ======================================================================
    # v2.2 — Unified Security Fabric
    # ======================================================================

    def upsert_fabric_module(self, record: Dict[str, Any]) -> int:
        """Insert or update a Fabric capability row. module_key is the natural key."""
        existing = self.conn.execute(
            "SELECT id FROM fabric_modules WHERE module_key = ?", (record["module_key"],)
        ).fetchone()
        controls = json.dumps(record.get("controls", []))
        metrics = json.dumps(record.get("metrics", {}))
        if existing:
            self.conn.execute(
                """
                UPDATE fabric_modules
                SET label = ?, pillar = ?, icon = ?, description = ?, maturity = ?,
                    status = ?, controls = ?, metrics = ?, updated_at = now()
                WHERE module_key = ?
                """,
                (record["label"], record["pillar"], record.get("icon"),
                 record.get("description"), record.get("maturity", "Initial"),
                 record.get("status", "active"), controls, metrics, record["module_key"]),
            )
            self.conn.commit()
            return existing[0]
        self.conn.execute(
            """
            INSERT INTO fabric_modules
                (module_key, label, pillar, icon, description, maturity, status, controls, metrics)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (record["module_key"], record["label"], record["pillar"], record.get("icon"),
             record.get("description"), record.get("maturity", "Initial"),
             record.get("status", "active"), controls, metrics),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_fabric_mod')").fetchone()
        return row[0] if row else -1

    def get_fabric_module(self, module_key: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT module_key, label, pillar, icon, description, maturity, status, "
            "controls, metrics, updated_at FROM fabric_modules WHERE module_key = ?",
            (module_key,),
        ).fetchone()
        if not row:
            return None
        return {
            "module_key": row[0], "label": row[1], "pillar": row[2], "icon": row[3],
            "description": row[4], "maturity": row[5], "status": row[6],
            "controls": json.loads(row[7] or "[]"), "metrics": json.loads(row[8] or "{}"),
            "updated_at": row[9],
        }

    def list_fabric_modules(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT module_key FROM fabric_modules ORDER BY id"
        ).fetchall()
        return [self.get_fabric_module(r[0]) for r in rows]

    def insert_fabric_event(self, evt: Dict[str, Any]) -> int:
        self.conn.execute(
            """
            INSERT INTO fabric_events (event_id, module_key, event_type, detail, severity, operator_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (evt["event_id"], evt["module_key"], evt["event_type"], evt.get("detail"),
             evt.get("severity", "info"), evt.get("operator_id")),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_fabric_evt')").fetchone()
        return row[0] if row else -1

    def list_fabric_events(self, module_key: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        if module_key:
            rows = self.conn.execute(
                "SELECT event_id, timestamp, module_key, event_type, detail, severity, operator_id "
                "FROM fabric_events WHERE module_key = ? ORDER BY id DESC LIMIT ?",
                (module_key, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT event_id, timestamp, module_key, event_type, detail, severity, operator_id "
                "FROM fabric_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        cols = ["event_id", "timestamp", "module_key", "event_type", "detail", "severity", "operator_id"]
        return [dict(zip(cols, r)) for r in rows]

    def insert_posture_assessment(self, record: Dict[str, Any]) -> int:
        self.conn.execute(
            """
            INSERT INTO zt_posture_assessments
                (assessment_id, overall_score, overall_level, by_pillar, operator_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (record["assessment_id"], record["overall_score"], record["overall_level"],
             json.dumps(record.get("by_pillar", {})), record.get("operator_id")),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_posture')").fetchone()
        return row[0] if row else -1

    def list_posture_assessments(self, limit: int = 30) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT assessment_id, assessed_at, overall_score, overall_level, by_pillar, operator_id "
            "FROM zt_posture_assessments ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "assessment_id": r[0], "assessed_at": r[1], "overall_score": r[2],
                "overall_level": r[3], "by_pillar": json.loads(r[4] or "{}"), "operator_id": r[5],
            })
        return out

    # ======================================================================
    # v2.3 — Operators
    # ======================================================================

    def upsert_operator(self, record: Dict[str, Any]) -> int:
        """Insert or update an operator. operator_id is the natural key."""
        existing = self.conn.execute(
            "SELECT id FROM operators WHERE operator_id = ?", (record["operator_id"],)
        ).fetchone()
        if existing:
            self.conn.execute(
                """
                UPDATE operators
                SET email = COALESCE(?, email), display_name = COALESCE(?, display_name),
                    role = ?, active = ?
                WHERE operator_id = ?
                """,
                (record.get("email"), record.get("display_name"),
                 record.get("role", "operator"), record.get("active", True),
                 record["operator_id"]),
            )
            self.conn.commit()
            return existing[0]
        self.conn.execute(
            """
            INSERT INTO operators (operator_id, email, display_name, role, active)
            VALUES (?, ?, ?, ?, ?)
            """,
            (record["operator_id"], record.get("email"), record.get("display_name"),
             record.get("role", "operator"), record.get("active", True)),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_operators')").fetchone()
        return row[0] if row else -1

    def get_operator(self, operator_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT operator_id, email, display_name, role, active, last_login, created_at "
            "FROM operators WHERE operator_id = ?", (operator_id,),
        ).fetchone()
        if not row:
            return None
        cols = ["operator_id", "email", "display_name", "role", "active", "last_login", "created_at"]
        return dict(zip(cols, row))

    def list_operators(self, active_only: bool = True) -> List[Dict[str, Any]]:
        clause = "WHERE active = true" if active_only else ""
        rows = self.conn.execute(
            f"SELECT operator_id, email, display_name, role, active, last_login, created_at "
            f"FROM operators {clause} ORDER BY id"
        ).fetchall()
        cols = ["operator_id", "email", "display_name", "role", "active", "last_login", "created_at"]
        return [dict(zip(cols, r)) for r in rows]

    def touch_operator_login(self, operator_id: str):
        self.conn.execute(
            "UPDATE operators SET last_login = now() WHERE operator_id = ?", (operator_id,)
        )
        self.conn.commit()

    # ======================================================================
    # v2.3 — MITRE ATT&CK Mappings
    # ======================================================================

    def insert_attack_mapping(self, record: Dict[str, Any]) -> int:
        self.conn.execute(
            """
            INSERT INTO attack_mappings
                (pentest_id, finding_id, tactic, technique_id, technique_name,
                 sub_technique_id, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("pentest_id"), record.get("finding_id"),
                record["tactic"], record["technique_id"], record["technique_name"],
                record.get("sub_technique_id"), record.get("confidence", 0.8),
            ),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_attack_map')").fetchone()
        return row[0] if row else -1

    def list_attack_mappings(self, pentest_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if pentest_id:
            rows = self.conn.execute(
                "SELECT * FROM attack_mappings WHERE pentest_id = ? ORDER BY id", (pentest_id,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM attack_mappings ORDER BY id DESC LIMIT 500").fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def attack_coverage_summary(self) -> Dict[str, Any]:
        """Distinct tactics/techniques demonstrated — a MITRE ATT&CK Navigator-style rollup."""
        by_tactic = self.conn.execute(
            "SELECT tactic, COUNT(DISTINCT technique_id) FROM attack_mappings GROUP BY tactic ORDER BY 2 DESC"
        ).fetchall()
        total_techniques = self.conn.execute(
            "SELECT COUNT(DISTINCT technique_id) FROM attack_mappings"
        ).fetchone()
        return {
            "distinct_techniques": total_techniques[0] if total_techniques else 0,
            "by_tactic": {r[0]: r[1] for r in by_tactic},
        }

    # ======================================================================
    # v2.3 — Compliance Checkpoints (hash-chained)
    # ======================================================================

    def insert_compliance_checkpoint(self, record: Dict[str, Any]) -> int:
        """
        Append a hash-chained compliance checkpoint. Each row's hash_chain is
        sha3-256(prev_hash + canonical row content), so any row tampered with
        after the fact breaks the chain for every row after it — the same
        tamper-evidence idea as pqc_audit_log's chain_index/prev_hash, at a
        coarser "was this action in-bounds" grain.
        """
        import hashlib
        prev = self.conn.execute(
            "SELECT hash_chain FROM compliance_checkpoints ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_hash = prev[0] if prev else "genesis"
        row_content = json.dumps({
            "action_type": record["action_type"], "operator_id": record["operator_id"],
            "target": record.get("target"), "authorization_result": record.get("authorization_result"),
            "prev_hash": prev_hash,
        }, sort_keys=True, default=str)
        hash_chain = hashlib.sha3_256((prev_hash + row_content).encode()).hexdigest()

        self.conn.execute(
            """
            INSERT INTO compliance_checkpoints
                (action_type, operator_id, target, authorization_result, scope_status,
                 insurance_status, allowed_to_proceed, pqc_entry_id, hash_chain, prev_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["action_type"], record["operator_id"], record.get("target"),
                record.get("authorization_result"), record.get("scope_status"),
                record.get("insurance_status"), record.get("allowed_to_proceed"),
                record.get("pqc_entry_id"), hash_chain, prev_hash,
            ),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_compliance_chk')").fetchone()
        return row[0] if row else -1

    def verify_compliance_chain(self) -> Dict[str, Any]:
        """Recompute the hash chain end-to-end and report the first break, if any."""
        import hashlib
        rows = self.conn.execute(
            "SELECT id, action_type, operator_id, target, authorization_result, "
            "hash_chain, prev_hash FROM compliance_checkpoints ORDER BY id"
        ).fetchall()
        expected_prev = "genesis"
        for r in rows:
            row_id, action_type, operator_id, target, auth_result, hash_chain, prev_hash = r
            if prev_hash != expected_prev:
                return {"valid": False, "broken_at_id": row_id, "reason": "prev_hash mismatch"}
            row_content = json.dumps({
                "action_type": action_type, "operator_id": operator_id, "target": target,
                "authorization_result": auth_result, "prev_hash": expected_prev,
            }, sort_keys=True, default=str)
            recomputed = hashlib.sha3_256((expected_prev + row_content).encode()).hexdigest()
            if recomputed != hash_chain:
                return {"valid": False, "broken_at_id": row_id, "reason": "hash mismatch"}
            expected_prev = hash_chain
        return {"valid": True, "checkpoints_verified": len(rows)}

    def list_compliance_checkpoints(self, limit: int = 200) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM compliance_checkpoints ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    # ======================================================================
    # v2.3 — RFP Responses
    # ======================================================================

    def insert_rfp_response(self, record: Dict[str, Any]) -> int:
        self.conn.execute(
            """
            INSERT INTO rfp_responses
                (client_name, methodology, tools_list, timeline, pricing,
                 insurance_statement, sample_report_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["client_name"], record.get("methodology"),
                json.dumps(record.get("tools_list", [])), record.get("timeline"),
                record.get("pricing"), record.get("insurance_statement"),
                record.get("sample_report_path"),
            ),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_rfp')").fetchone()
        return row[0] if row else -1

    def list_rfp_responses(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, client_name, methodology, tools_list, timeline, pricing, "
            "insurance_statement, sample_report_path, created_at FROM rfp_responses ORDER BY id DESC"
        ).fetchall()
        cols = ["id", "client_name", "methodology", "tools_list", "timeline", "pricing",
                "insurance_statement", "sample_report_path", "created_at"]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            d["tools_list"] = json.loads(d.get("tools_list") or "[]")
            out.append(d)
        return out

    # ======================================================================
    # v2.3 — Human Approval Gate
    # ======================================================================

    def create_approval_request(self, record: Dict[str, Any]) -> int:
        """
        Required: request_id, requested_by, action_type
        Optional: target, phase, technique_id, risk_level, summary,
                  payload_detail (dict/JSON), pqc_entry_id, expires_at
        """
        self.conn.execute(
            """
            INSERT INTO approval_requests
                (request_id, requested_by, action_type, target, phase, technique_id,
                 risk_level, summary, payload_detail, pqc_entry_id, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["request_id"], record["requested_by"], record["action_type"],
                record.get("target"), record.get("phase"), record.get("technique_id"),
                record.get("risk_level", "MEDIUM"), record.get("summary"),
                json.dumps(record.get("payload_detail", {}), default=str),
                record.get("pqc_entry_id"), record.get("expires_at"),
            ),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_approval')").fetchone()
        return row[0] if row else -1

    def decide_approval_request(
        self, request_id: str, decision: str, decided_by: str, reason: str = "",
    ) -> bool:
        """decision must be 'approved' or 'denied'."""
        result = self.conn.execute(
            """
            UPDATE approval_requests
            SET status = ?, decided_by = ?, decided_at = now(), decision_reason = ?
            WHERE request_id = ? AND status = 'pending'
            """,
            (decision, decided_by, reason, request_id),
        )
        self.conn.commit()
        return (result.rowcount or 0) > 0

    def get_approval_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        d = dict(zip(cols, row))
        d["payload_detail"] = json.loads(d.get("payload_detail") or "{}")
        return d

    def list_approval_requests(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM approval_requests WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM approval_requests ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        cols = [d[0] for d in self.conn.description]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            d["payload_detail"] = json.loads(d.get("payload_detail") or "{}")
            out.append(d)
        return out

    def expire_stale_approval_requests(self) -> int:
        result = self.conn.execute(
            "UPDATE approval_requests SET status = 'expired' "
            "WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at < now()"
        )
        self.conn.commit()
        return result.rowcount or 0

    def approval_gate_stats(self) -> Dict[str, Any]:
        by_status = self.conn.execute(
            "SELECT status, COUNT(*) FROM approval_requests GROUP BY status"
        ).fetchall()
        by_risk_pending = self.conn.execute(
            "SELECT risk_level, COUNT(*) FROM approval_requests WHERE status = 'pending' GROUP BY risk_level"
        ).fetchall()
        return {
            "by_status": {r[0]: r[1] for r in by_status},
            "pending_by_risk": {r[0]: r[1] for r in by_risk_pending},
        }

    # ======================================================================
    # Utility
    # ======================================================================

    def table_stats(self) -> Dict[str, int]:
        """Return row counts for all tables — useful for health checks."""
        tables = [
            "agent_logs", "quantum_jobs", "pentest_runs", "findings",
            "scopes", "insurance_policies", "assessment_reports",
            "sandboxes", "compliance_reports", "playbooks", "playbook_executions",
            "pqc_audit_log", "encryption_keys", "payload_executions",
            "network_map", "vuln_db", "threat_intel",
            "fabric_modules", "fabric_events", "zt_posture_assessments",
            "operators", "attack_mappings", "compliance_checkpoints",
            "rfp_responses", "approval_requests",
        ]
        stats = {}
        for t in tables:
            try:
                row = self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
                stats[t] = row[0] if row else 0
            except Exception:
                stats[t] = -1
        return stats

    def close(self):
        self.conn.close()
