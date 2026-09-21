"""
JAKAL Database Layer - DuckDB (local, embedded, zero-cost)

Schema version: 3.0
  v3.0 - ontological_object_nodes, lattice_edge_telemetry (a Palantir
          Foundry-style Object/Link digital twin -- see
          services/ontology_engine.py), maya_vigesimal_auth_sessions (a
          Maya-calendar-coordinate second-factor challenge interlocked
          with the existing v2.3 Human Approval Gate for HIGH/CRITICAL
          staged payloads -- see security_agents/exploit_agent.py),
          resonance_policy_enforcements (named, module-scoped policy
          objects -- distinct from automation_settings's small set of
          global knobs and from Batch 1's isolation-specific
          resonance_policy), q_aip_inference_registry (an audit trail of
          quantum-circuit executions, PQC-signed like everything else in
          this schema). All five tables are additive; nothing existing
          changed shape.
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
  v2.4 - ai_safety_events, agentic_remediation_tasks, global_fleet_matrix,
          global_security_settings, quantum_orbital_comms.
          These back four new API surfaces requested directly by the
          operator: Horizon (AI-safety/compliance event stream), Agentic
          Canvas (patch-deployment tasks), Resonance/Global Dashboard
          (fleet posture + org-wide security config), and Q'AIP (LLM/
          quantum inference-chain ledger + a rate-limiting "Energy Core").
          None of these bypass the existing gates: Canvas patch deploys
          route through the same approval_requests table as every other
          high-risk action (v2.3), and global_security_settings mirrors
          -- rather than duplicates -- the real operators/encryption_keys/
          pqc_audit_log tables instead of inventing a second source of truth.
  v2.5 - unified_security_events, horizon_trust_fabric ("Ares Unified
          Control Plane"): a cross-pillar telemetry bus that Horizon,
          Resonance/Q'AIP, and recon/dark-web intake all write into, plus
          a derived executive rollup (compliance %, active agents, threats
          blocked, Shadow AI / SOC2 / adversarial-defense / DLP health).
          approval_requests (v2.3) gains one nullable origin_module column
          rather than a second, parallel `agentic_approval_queue` table --
          see the CREATE TABLE comment below for why.
          Also: encryption_keys (v2.1 table, previously never written to by
          any live code path) is now actually populated -- see
          crypto/encryption_manager.py's KEK-wrapped key persistence, and
          list_encryption_keys()'s new status=None ("all lifecycle states")
          option below.
"""

import hmac
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import duckdb

logger = logging.getLogger(__name__)


class _MaterializedResult:
    """Result of one _LockedConnection.execute() call: rows and column
    description captured eagerly (see _LockedConnection's docstring for
    why), served from an in-memory list rather than the shared connection's
    live cursor state. fetchone() advances a position pointer so code that
    fetches one row at a time still drains the result set incrementally,
    matching normal DB-API cursor behavior."""
    __slots__ = ("_rows", "_pos", "description")

    def __init__(self, rows, description):
        self._rows = rows
        self._pos = 0
        self.description = description

    def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row


class _LockedConnection:
    """
    Thread-safe wrapper around a single shared duckdb.DuckDBPyConnection.

    CRITICAL FIX: a bare duckdb.Connection is NOT safe for concurrent
    .execute() calls from multiple threads -- confirmed by direct
    reproduction (10 threads each looping conn.execute("SELECT ...")
    against one shared connection reliably segfaults the process,
    `python3` exits with SIGSEGV / code 139). Every router in this
    codebase reaches this connection via get_db_manager()'s process-wide
    singleton, and FastAPI's run_in_threadpool() genuinely runs different
    requests' DB calls on different worker threads whenever two requests
    overlap in time -- completely ordinary under real concurrent usage
    (two browser tabs, one tab plus an open SSE stream, etc.), not just
    synthetic load tests. Without this fix the entire backend can crash
    under normal multi-request traffic.

    execute() acquires a lock, runs the real execute()+fetchall(), and
    captures .description -- all still inside the lock -- then returns a
    _MaterializedResult built from that already-fetched data, safe to read
    from without touching the shared connection again. This covers the
    chained call pattern used almost everywhere in this codebase
    (`conn.execute(sql).fetchall()` / `.fetchone()`).

    A second pattern also appears throughout (`conn.execute(sql)` on one
    line, `conn.description` read separately on a later line): that
    `.description` access is served from `threading.local()` storage --
    each thread's own last execute() call populates only that thread's
    slot, so a standalone read always reflects that SAME thread's own
    last query. Since one HTTP request's DB work runs synchronously on one
    threadpool worker thread (execute, then whatever follows, in order,
    before the thread is returned to the pool), this is exactly the
    isolation the separate-statement pattern needs -- no cross-request
    interference is possible even though the underlying storage is
    process-wide.
    """

    def __init__(self, conn: "duckdb.DuckDBPyConnection"):
        self._conn = conn
        self._lock = threading.Lock()
        self._local = threading.local()

    def execute(self, *args, **kwargs) -> _MaterializedResult:
        with self._lock:
            self._conn.execute(*args, **kwargs)
            rows = self._conn.fetchall()
            description = self._conn.description
        self._local.last_description = description
        return _MaterializedResult(rows, description)

    @property
    def description(self):
        return getattr(self._local, "last_description", None)

    def commit(self):
        with self._lock:
            return self._conn.commit()

    def close(self):
        with self._lock:
            return self._conn.close()

    def __getattr__(self, name):
        # Fallback for anything not explicitly wrapped above (e.g. the
        # rare direct .cursor() use) -- passed through unlocked, so avoid
        # introducing new call sites that bypass execute()/commit() above.
        return getattr(self._conn, name)

# Agents actually wired in app.py as *Agent instances (ReconAgent, EnumAgent,
# WebAgent, ReportAgent, WirelessAgent, ExploitAgent) -- kept as a plain
# constant here rather than a DB table, since it only changes when app.py's
# instantiation block changes; a table would just be a second place that
# same number could drift out of sync. Used by horizon_trust_fabric_snapshot().
WIRED_SECURITY_AGENTS = (
    "ReconAgent", "EnumAgent", "WebAgent", "ReportAgent", "WirelessAgent", "ExploitAgent",
)


class DuckDBManager:
    def __init__(self, db_path: str = "jakal.duckdb"):
        self.db_path = db_path
        self.conn = _LockedConnection(duckdb.connect(db_path))
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
            # v2.4 tables all key off app-generated VARCHAR UUIDs (event_id,
            # task_id, machine_id, config_id, comm_id) — no sequences needed.
            # v2.6 sequences
            "seq_users", "seq_roles", "seq_permissions", "seq_sessions",
            "seq_api_keys", "seq_audit_log", "seq_vault", "seq_darkweb_watch",
            "seq_darkweb_finding", "seq_training_module", "seq_training_completion",
            "seq_phishing_campaign", "seq_phishing_target",
            # v2.7 sequences
            "seq_remediation",
            # v2.8 tables key off app-generated VARCHAR policy_key / connector
            # call IDs -- no sequences needed.
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

        # ── v2.4 Tables — Horizon / Agentic Canvas / Resonance / Q'AIP ─────
        # DDL as specified by the operator's v2.4 directive, DuckDB-adapted
        # (TIMESTAMP -> TIMESTAMPTZ for consistency with every other table
        # in this schema; everything else is as given).

        c.execute("""
        CREATE TABLE IF NOT EXISTS ai_safety_events (
            event_id                 VARCHAR PRIMARY KEY,
            client_id                VARCHAR,
            soc_compliance_tier      VARCHAR,           -- e.g. SOC2 Type II, HIPAA
            protection_layer         VARCHAR,
            alert_severity           INTEGER,
            regulatory_schema_status VARCHAR DEFAULT 'Syncing',  -- Syncing | Resolved | Attention Required
            event_timestamp          TIMESTAMPTZ DEFAULT now()
        )
        """)

        # Every deploy-patch action lands here AND as an approval_requests
        # row (v2.3) — operator_approval_status here mirrors that row's
        # status rather than being a second, independent approval path.
        c.execute("""
        CREATE TABLE IF NOT EXISTS agentic_remediation_tasks (
            task_id                  VARCHAR PRIMARY KEY,
            target_machine_ip        VARCHAR,
            patch_id                 VARCHAR,
            autonomous_action_taken  VARCHAR,
            deployment_progress      INTEGER DEFAULT 0,   -- 0..100
            remediation_status       VARCHAR DEFAULT 'queued',
            operator_approval_status VARCHAR DEFAULT 'pending',  -- mirrors approval_requests.status
            approval_request_id      VARCHAR,             -- FK -> approval_requests.request_id
            created_at                TIMESTAMPTZ DEFAULT now(),
            updated_at                TIMESTAMPTZ DEFAULT now()
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS global_fleet_matrix (
            machine_id                VARCHAR PRIMARY KEY,
            network_segment            VARCHAR,
            predictive_threat_score    DOUBLE,
            resonance_load_metric      DOUBLE,           -- Q'AIP computational load, 0.0-1.0
            last_diagnostic_timestamp  TIMESTAMPTZ DEFAULT now(),
            is_quarantined              BOOLEAN DEFAULT false
        )
        """)

        # Deliberately a single-row "current config" table, mirroring live
        # values from operators/encryption_keys/pqc_audit_log rather than
        # being an independently-editable second source of truth for
        # security posture -- see resonance_settings_snapshot() below.
        c.execute("""
        CREATE TABLE IF NOT EXISTS global_security_settings (
            config_id              VARCHAR PRIMARY KEY,
            rbac_policy_hash        VARCHAR,
            api_encryption_standard VARCHAR DEFAULT 'ML-DSA-65 + AES-256-GCM',
            key_management_status   VARCHAR,
            trade_secret_isolation  BOOLEAN DEFAULT true,
            recorded_at             TIMESTAMPTZ DEFAULT now()
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS quantum_orbital_comms (
            comm_id                 VARCHAR PRIMARY KEY,
            event_type              VARCHAR,             -- llm_inference | quantum_job | aip_prioritization
            computational_agent_id  VARCHAR,
            inference_chain_hash    VARCHAR,
            quantum_entropy_seed    VARCHAR,
            execution_latency_ms    INTEGER,
            recorded_at             TIMESTAMPTZ DEFAULT now()
        )
        """)

        # ── v2.5 Tables — Ares Unified Control Plane ───────────────────────
        # Cross-pillar telemetry bus + a derived Horizon "trust fabric"
        # snapshot, per the operator's Ares architecture directive. Two
        # deliberate deviations from the directive's literal DDL, both
        # flagged here for review:
        #   1. horizon_trust_fabric is a DERIVED snapshot (one write path,
        #      horizon_trust_fabric_snapshot() below) instead of a freely
        #      writable table -- same reasoning as global_security_settings
        #      in v2.4: a status table anyone can write into can silently
        #      drift from what's actually true.
        #   2. No `agentic_approval_queue` table. approval_requests (v2.3)
        #      already IS that queue -- Agentic Canvas, ExploitAgent, and
        #      now Ares recon-intel ingestion all stage into it. A second,
        #      parallel queue would recreate exactly the two-sources-of-
        #      truth problem the v2.3 Human Approval Gate exists to avoid.
        #      A request's origin (origin_module) is recorded inside the
        #      existing payload_detail JSON column rather than as a new
        #      approval_requests column -- deliberately NOT an ALTER TABLE
        #      ADD COLUMN. Testing this change hit a reproducible DuckDB
        #      WAL-replay crash ("GetDefaultDatabase with no default
        #      database set") on the *next* process to open a persistent
        #      .duckdb file after an ALTER TABLE ADD COLUMN had run against
        #      it -- confirmed by isolating the statement, not a fluke.
        #      approval_requests already has production rows in deployed
        #      installs, so no DDL migration touches that table here.
        c.execute("""
        CREATE TABLE IF NOT EXISTS unified_security_events (
            event_id             VARCHAR PRIMARY KEY,
            source_module        VARCHAR NOT NULL,      -- HORIZON | RESONANCE_QAIP | GOD_S_EYE_RECON | DARK_WEB | ...
            threat_category      VARCHAR,                -- SHADOW_AI | SOC2_VIOLATION | EXPOSED_SERVICE | DLP_MATCH | ...
            severity_score       DOUBLE DEFAULT 0.0,      -- 0.0-1.0, from threat_scoring.score_recon_finding()
            raw_payload          VARCHAR DEFAULT '{}',    -- JSON — the full inbound finding
            approval_request_id  VARCHAR,                 -- set once severity crosses the HITL threshold
            timestamp             TIMESTAMPTZ DEFAULT now()
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS horizon_trust_fabric (
            fabric_id                  VARCHAR PRIMARY KEY,
            operator_id                VARCHAR,
            compliance_coverage_pct    DOUBLE,
            active_agent_count         INTEGER,
            threats_blocked_count      INTEGER,
            shadow_ai_status           VARCHAR,
            soc2_compliance_status     VARCHAR,
            adversarial_defense_status VARCHAR,
            dlp_status                 VARCHAR,
            fabric_status               VARCHAR,          -- SECURE | DEGRADED | UNINITIALIZED, from fabric_modules
            last_schema_sync           TIMESTAMPTZ,
            recorded_at                 TIMESTAMPTZ DEFAULT now()
        )
        """)

        # ── v2.6 Tables — Global Settings & Security (IAM / Vault / Awareness) ──
        # Backs the Global Settings & Security tab's Profile, Login Encryption,
        # API Integration, RBAC, Auditing and Key Management sub-tabs, plus the
        # EAS R&D / Trade Secrets vault and the Dark Web Monitoring / Awareness
        # Training / Phishing Campaigns modules. Passwords are NEVER stored in
        # plaintext (Argon2id via passlib — see routers/iam.py); this table
        # only ever holds the hash.

        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id             INTEGER PRIMARY KEY DEFAULT nextval('seq_users'),
            user_id        VARCHAR UNIQUE NOT NULL,      -- UUID, stable external identifier
            username       VARCHAR UNIQUE NOT NULL,
            email          VARCHAR UNIQUE,
            password_hash  VARCHAR NOT NULL,             -- Argon2id hash (passlib)
            mfa_secret     VARCHAR,                       -- TOTP base32 secret, only once MFA enabled
            mfa_enabled    BOOLEAN DEFAULT false,
            status         VARCHAR DEFAULT 'active',      -- active | disabled | locked
            failed_logins  INTEGER DEFAULT 0,
            locked_until   TIMESTAMPTZ,
            created_at     TIMESTAMPTZ DEFAULT now(),
            last_login_at  TIMESTAMPTZ,
            last_login_ip  VARCHAR
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS roles (
            id           INTEGER PRIMARY KEY DEFAULT nextval('seq_roles'),
            role_key     VARCHAR UNIQUE NOT NULL,        -- e.g. root_admin, security_analyst, read_only
            label        VARCHAR NOT NULL,
            description  VARCHAR,
            is_system    BOOLEAN DEFAULT false,           -- seeded/reserved role, cannot be deleted
            created_at   TIMESTAMPTZ DEFAULT now()
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS permissions (
            id             INTEGER PRIMARY KEY DEFAULT nextval('seq_permissions'),
            permission_key VARCHAR UNIQUE NOT NULL,       -- e.g. vm:exec, iam:manage_roles, vault:read
            label          VARCHAR NOT NULL,
            category       VARCHAR                        -- groups permissions in the RBAC UI
        )
        """)

        # Many-to-many join tables — plain VARCHAR keys (not FKs; DuckDB has no
        # enforced FK constraints, kept consistent with the rest of this schema).
        c.execute("""
        CREATE TABLE IF NOT EXISTS role_permissions (
            role_key       VARCHAR NOT NULL,
            permission_key VARCHAR NOT NULL,
            PRIMARY KEY (role_key, permission_key)
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS user_roles (
            user_id  VARCHAR NOT NULL,
            role_key VARCHAR NOT NULL,
            PRIMARY KEY (user_id, role_key)
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id           INTEGER PRIMARY KEY DEFAULT nextval('seq_sessions'),
            session_id   VARCHAR UNIQUE NOT NULL,         -- jti claim of the issued JWT
            user_id      VARCHAR NOT NULL,
            issued_at    TIMESTAMPTZ DEFAULT now(),
            expires_at   TIMESTAMPTZ NOT NULL,
            revoked      BOOLEAN DEFAULT false,
            ip_address   VARCHAR,
            user_agent   VARCHAR
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id            INTEGER PRIMARY KEY DEFAULT nextval('seq_api_keys'),
            key_id        VARCHAR UNIQUE NOT NULL,        -- public prefix, safe to log/display
            key_hash      VARCHAR NOT NULL,                -- SHA3-256 of the full secret; secret shown once
            owner_user_id VARCHAR NOT NULL,
            label         VARCHAR,
            scopes        VARCHAR DEFAULT '[]',            -- JSON array of permission_keys this key may use
            status        VARCHAR DEFAULT 'active',        -- active | revoked
            created_at    TIMESTAMPTZ DEFAULT now(),
            last_used_at  TIMESTAMPTZ,
            expires_at    TIMESTAMPTZ,
            revoked_at    TIMESTAMPTZ
        )
        """)

        # Structured, queryable/exportable audit trail for the Auditing sub-tab —
        # deliberately separate from agent_logs (which is agent/pentest telemetry,
        # not operator/security-relevant actions) and from pqc_audit_log (which is
        # the cryptographically-signed chain for HIGH/CRITICAL actions specifically).
        c.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id            INTEGER PRIMARY KEY DEFAULT nextval('seq_audit_log'),
            timestamp     TIMESTAMPTZ DEFAULT now(),
            actor_user_id VARCHAR,                         -- NULL for unauthenticated/system actions
            actor_label   VARCHAR,                         -- denormalized username, survives user deletion
            action        VARCHAR NOT NULL,                -- e.g. login, role_grant, key_rotate, vault_read
            resource_type VARCHAR,
            resource_id   VARCHAR,
            outcome       VARCHAR NOT NULL,                -- success | denied | error
            ip_address    VARCHAR,
            detail        VARCHAR DEFAULT '{}'              -- JSON
        )
        """)

        # EAS R&D / Trade Secrets vault — every blob is AES-256-GCM encrypted at
        # rest via crypto/encryption_manager.py before it reaches this table;
        # DuckDB never sees plaintext IP.
        c.execute("""
        CREATE TABLE IF NOT EXISTS trade_secrets_vault (
            id               INTEGER PRIMARY KEY DEFAULT nextval('seq_vault'),
            item_id          VARCHAR UNIQUE NOT NULL,
            title            VARCHAR NOT NULL,
            classification   VARCHAR DEFAULT 'TRADE_SECRET', -- TRADE_SECRET | EAS_RD | CONFIDENTIAL
            owner_user_id    VARCHAR NOT NULL,
            ciphertext_envelope VARCHAR NOT NULL,           -- JSON envelope from EncryptionManager.encrypt()
            content_sha3_256 VARCHAR NOT NULL,               -- integrity hash of the plaintext, for tamper checks
            allowed_roles    VARCHAR DEFAULT '[]',           -- JSON array of role_keys permitted to read
            created_at       TIMESTAMPTZ DEFAULT now(),
            updated_at       TIMESTAMPTZ DEFAULT now(),
            status           VARCHAR DEFAULT 'active'         -- active | archived
        )
        """)

        # Dark Web Monitoring — a watchlist of identifiers (emails/domains) plus
        # findings from pluggable threat-intel connectors (HIBP wired for real
        # breach data; paid feeds like Recorded Future/SpyCloud/Flashpoint are
        # architected as the same connector interface — see routers/darkweb.py).
        c.execute("""
        CREATE TABLE IF NOT EXISTS darkweb_watchlist (
            id            INTEGER PRIMARY KEY DEFAULT nextval('seq_darkweb_watch'),
            watch_id      VARCHAR UNIQUE NOT NULL,
            identifier    VARCHAR NOT NULL,                 -- email or domain being monitored
            identifier_type VARCHAR NOT NULL,                -- email | domain
            added_by      VARCHAR,
            added_at      TIMESTAMPTZ DEFAULT now(),
            active        BOOLEAN DEFAULT true,
            last_checked_at TIMESTAMPTZ
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS darkweb_findings (
            id            INTEGER PRIMARY KEY DEFAULT nextval('seq_darkweb_finding'),
            finding_id    VARCHAR UNIQUE NOT NULL,
            watch_id      VARCHAR NOT NULL,
            source        VARCHAR NOT NULL,                 -- hibp | manual | <connector name>
            breach_name   VARCHAR,
            breach_date   VARCHAR,
            data_classes  VARCHAR DEFAULT '[]',              -- JSON array e.g. ["Passwords","Emails"]
            severity      VARCHAR DEFAULT 'MEDIUM',
            discovered_at TIMESTAMPTZ DEFAULT now(),
            acknowledged  BOOLEAN DEFAULT false
        )
        """)

        # Human Layer Security — Awareness Training + Phishing Campaigns
        c.execute("""
        CREATE TABLE IF NOT EXISTS training_modules (
            id           INTEGER PRIMARY KEY DEFAULT nextval('seq_training_module'),
            module_key   VARCHAR UNIQUE NOT NULL,
            title        VARCHAR NOT NULL,
            category     VARCHAR,                           -- phishing | password_hygiene | data_handling | ...
            duration_min INTEGER DEFAULT 10,
            passing_score INTEGER DEFAULT 80,
            content_url  VARCHAR,
            active       BOOLEAN DEFAULT true,
            created_at   TIMESTAMPTZ DEFAULT now()
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS training_completions (
            id            INTEGER PRIMARY KEY DEFAULT nextval('seq_training_completion'),
            completion_id VARCHAR UNIQUE NOT NULL,
            module_key    VARCHAR NOT NULL,
            user_id       VARCHAR NOT NULL,
            score         INTEGER,
            passed        BOOLEAN,
            completed_at  TIMESTAMPTZ DEFAULT now()
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS phishing_campaigns (
            id            INTEGER PRIMARY KEY DEFAULT nextval('seq_phishing_campaign'),
            campaign_id   VARCHAR UNIQUE NOT NULL,
            name          VARCHAR NOT NULL,
            template_key  VARCHAR NOT NULL,                  -- keys into a template library, see awareness.py
            launched_by   VARCHAR,
            status        VARCHAR DEFAULT 'draft',            -- draft | active | completed
            launched_at   TIMESTAMPTZ,
            completed_at  TIMESTAMPTZ
        )
        """)

        # ── v2.7 Tables — Detection & Response / Script Catalog ─────────────
        # Backs routers/response.py: real (auto-executed, reversible,
        # data-layer) actions like IOC blocking and artifact quarantine, plus
        # a record of every staged-for-approval action that touches live
        # infrastructure (host isolation, host quarantine) or runs a
        # gacyber_toolkit script -- those always go through the existing
        # approval_requests table (create_approval_request/decide_approval_
        # request), this table is the response-specific outcome ledger.
        c.execute("""
        CREATE TABLE IF NOT EXISTS remediation_actions (
            id                 INTEGER PRIMARY KEY DEFAULT nextval('seq_remediation'),
            action_id          VARCHAR UNIQUE NOT NULL,
            action_type        VARCHAR NOT NULL,        -- ioc_block | quarantine_artifact | quarantine_host_staged | isolate_host_staged | script_catalog_execution | triage
            target             VARCHAR,
            status             VARCHAR NOT NULL,        -- completed | staged | approved | denied | executed_in_sandbox
            risk_level         VARCHAR DEFAULT 'LOW',
            approval_request_id VARCHAR,                -- FK to approval_requests.request_id when staged
            operator_id        VARCHAR,
            d3fend_technique   VARCHAR,                  -- e.g. D3-CQ, D3-NI, D3-EI
            detail             VARCHAR DEFAULT '{}',     -- JSON
            created_at         TIMESTAMPTZ DEFAULT now(),
            resolved_at        TIMESTAMPTZ
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS phishing_targets (
            id            INTEGER PRIMARY KEY DEFAULT nextval('seq_phishing_target'),
            campaign_id   VARCHAR NOT NULL,
            target_email  VARCHAR NOT NULL,
            sent_at       TIMESTAMPTZ,
            opened_at     TIMESTAMPTZ,
            clicked_at    TIMESTAMPTZ,
            reported_at   TIMESTAMPTZ                        -- target reported it as suspicious (best outcome)
        )
        """)

        # ── v2.8 Tables — Resonance Wave Automation policy ──────────────────
        # Deliberately NOT touching global_security_settings (v2.4) --
        # that table is a DERIVED snapshot by design (see
        # resonance_settings_snapshot()'s docstring: computed fresh from
        # operators/encryption_keys/pqc_audit_log, never independently
        # editable, specifically to avoid a second, driftable source of
        # truth for security posture). automation_settings is a genuinely
        # separate concept: a small set of real, independently-meaningful
        # automation knobs -- each one is read by a real enforcement point
        # (routers/response.py, vault.py, cheatsheet.py) rather than being
        # a decorative flag nothing checks.
        #
        # RECONCILIATION NOTE (merge of a parallel local build, "Batch 1"):
        # a separately-run session added its OWN table also named
        # `resonance_policy` with a materially different shape (a
        # multi-row, per-policy-object table: policy_name/threat_threshold/
        # trigger_type/isolation_mode/auto_enforce/webhook_url/enabled,
        # oriented around named enforcement policies) alongside
        # `resonance_actions` and `resonance_audit_trail`. That is a
        # different concept from this single-row-per-knob settings table,
        # so rather than collide on the name (and silently corrupt either
        # schema), this table was renamed automation_settings and every
        # endpoint/test/doc that referenced /resonance/policy now uses
        # /resonance/automation-settings. Batch 1's resonance_policy /
        # resonance_actions / resonance_audit_trail tables are kept as-is
        # below (see their own CREATE TABLE blocks) since they serve a
        # distinct, complementary purpose: named, reusable enforcement
        # policy objects vs. this table's small set of global on/off and
        # threshold knobs.
        c.execute("""
        CREATE TABLE IF NOT EXISTS automation_settings (
            policy_key   VARCHAR PRIMARY KEY,
            value        VARCHAR NOT NULL,       -- JSON-encoded (bool/number/string)
            value_type   VARCHAR NOT NULL,        -- bool | number | string
            label        VARCHAR,
            description  VARCHAR,
            updated_by   VARCHAR,
            updated_at   TIMESTAMPTZ DEFAULT now()
        )
        """)

        # ── Batch 1 Tables (merged from a parallel local build) ─────────────
        # Reconciliation: these tables were added directly on main by a
        # separate session while the automation_settings work above was in
        # progress on this branch. resonance_policy here is a DIFFERENT,
        # complementary concept to automation_settings (named, reusable,
        # multi-row enforcement-policy objects vs. a small set of global
        # single-row on/off and threshold knobs) -- kept as-is, not merged
        # or renamed, since it does not collide once automation_settings
        # was renamed off of the resonance_policy name. script_library /
        # script_executions back routers/scripts.py, the operator-uploaded
        # script marketplace, distinct from payloads/script_catalog.py's
        # auto-indexed, prepopulated gacyber_toolkit corpus that
        # routers/cheatsheet.py exposes.
        #
        # BUG FIX: these tables' PRIMARY KEY columns use
        # DEFAULT nextval('seq_...') -- DuckDB resolves the sequence name at
        # CREATE TABLE time (not lazily at first INSERT), so the sequences
        # must exist before any of these five CREATE TABLEs run. The
        # original code created them in the opposite order (sequences
        # created in a block AFTER all five tables), which raised
        # `CatalogException: Sequence with name seq_resonance_policy does
        # not exist!` on the very first fresh-database initialize_schema()
        # call -- confirmed by reproducing it here. Moved sequence creation
        # to right here, ahead of the tables that reference it.
        try:
            c.execute("CREATE SEQUENCE IF NOT EXISTS seq_resonance_policy START 1")
            c.execute("CREATE SEQUENCE IF NOT EXISTS seq_resonance_actions START 1")
            c.execute("CREATE SEQUENCE IF NOT EXISTS seq_resonance_audit START 1")
            c.execute("CREATE SEQUENCE IF NOT EXISTS seq_script_lib START 1")
            c.execute("CREATE SEQUENCE IF NOT EXISTS seq_script_exec START 1")
        except Exception:
            pass  # Sequences may already exist

        # ══════════════════════════════════════════════════════════════════════════════
        # v2.5 Enhanced - Resonance Policy Management & Enforcement
        # ══════════════════════════════════════════════════════════════════════════════

        c.execute("""
        CREATE TABLE IF NOT EXISTS resonance_policy (
            id                  INTEGER PRIMARY KEY DEFAULT nextval('seq_resonance_policy'),
            policy_id           VARCHAR UNIQUE NOT NULL,
            policy_name         VARCHAR NOT NULL,
            description         VARCHAR,
            threat_threshold    DECIMAL DEFAULT 0.7,    -- Severity at which isolation triggers
            trigger_type        VARCHAR DEFAULT 'threat_detection',  -- threat_detection, compliance_breach, etc.
            isolation_mode      VARCHAR DEFAULT 'network_only',      -- network_only, full_isolation, monitored
            auto_enforce        BOOLEAN DEFAULT false,   -- Skip approval gate if true
            webhook_url         VARCHAR,                 -- Send signed webhooks to this URL
            enabled             BOOLEAN DEFAULT true,
            created_at          TIMESTAMPTZ DEFAULT now(),
            updated_at          TIMESTAMPTZ DEFAULT now()
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS resonance_actions (
            id                  INTEGER PRIMARY KEY DEFAULT nextval('seq_resonance_actions'),
            policy_id           VARCHAR NOT NULL,
            action_type         VARCHAR NOT NULL,        -- isolate_host, kill_process, quarantine_data, snapshot_state
            trigger_threshold   DECIMAL,                 -- Specific threshold for this action
            enforcement_mode    VARCHAR DEFAULT 'block', -- block, alert_only, staged
            created_at          TIMESTAMPTZ DEFAULT now()
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS resonance_audit_trail (
            id                  INTEGER PRIMARY KEY DEFAULT nextval('seq_resonance_audit'),
            event_id            VARCHAR UNIQUE NOT NULL,
            event_type          VARCHAR NOT NULL,        -- isolation_requested, isolation_simulated, isolation_enforced, etc.
            isolation_id        VARCHAR,
            policy_id           VARCHAR,
            actor                VARCHAR,                 -- Operator ID
            status               VARCHAR,                 -- pending, simulated, approved, executing, active, released, failed
            event_data          VARCHAR DEFAULT '{}',    -- JSON event details
            signature_hmac      VARCHAR,                 -- HMAC-SHA256 signature for non-repudiation
            timestamp           TIMESTAMPTZ DEFAULT now()
        )
        """)

        # core/enforcement.py's AuditedHostIsolationEngine originally had no
        # dedicated table to persist AuditedHostIsolation state to -- its
        # own _persist_isolation() docstring said so explicitly ("This is a
        # placeholder; in production, add dedicated table to database.py")
        # and instead stuffed a JSON blob into agent_logs.details, fetched
        # back via `details LIKE '%"<isolation_id>"%' ORDER BY timestamp
        # DESC LIMIT 1`. That broke in two ways once actually exercised
        # (this reconciliation was the first time it ran end-to-end): the
        # LIKE search doesn't scope to a single isolation reliably, and
        # every persist wrote the object's ORIGINAL created_at as the row's
        # timestamp (never the current write time), so "ORDER BY timestamp
        # DESC" ties on every update after the first -- confirmed by
        # reproducing a stale-status read after enforce_isolation(). One
        # real table, upserted by isolation_id, fixes both.
        c.execute("""
        CREATE TABLE IF NOT EXISTS resonance_isolations (
            isolation_id  VARCHAR PRIMARY KEY,
            status        VARCHAR NOT NULL,         -- pending | simulated | approved | active | released | failed
            target_hostname VARCHAR,
            state         VARCHAR NOT NULL,          -- JSON: AuditedHostIsolation.model_dump()
            created_at    TIMESTAMPTZ DEFAULT now(),
            updated_at    TIMESTAMPTZ DEFAULT now()
        )
        """)

        # ══════════════════════════════════════════════════════════════════════════════
        # v2.5 Enhanced - Script Library Management
        # ══════════════════════════════════════════════════════════════════════════════

        c.execute("""
        CREATE TABLE IF NOT EXISTS script_library (
            id                  INTEGER PRIMARY KEY DEFAULT nextval('seq_script_lib'),
            script_id           VARCHAR UNIQUE NOT NULL,
            name                VARCHAR NOT NULL,
            description         VARCHAR,
            category            VARCHAR NOT NULL,        -- network_recon, endpoint_hardening, threat_hunting, etc.
            language            VARCHAR NOT NULL,        -- python3, bash, powershell, etc.
            script_content      VARCHAR NOT NULL,        -- Full script source code
            parameters          VARCHAR DEFAULT '{}',    -- JSON: {param_name: {type, required, default, description}}
            author              VARCHAR,
            version             VARCHAR DEFAULT '1.0.0',
            tags                VARCHAR DEFAULT '[]',    -- JSON array of tags
            approved            BOOLEAN DEFAULT false,   -- Requires admin approval
            approval_date       TIMESTAMPTZ,
            approval_by         VARCHAR,
            created_at          TIMESTAMPTZ DEFAULT now(),
            updated_at          TIMESTAMPTZ DEFAULT now()
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS script_executions (
            id                  INTEGER PRIMARY KEY DEFAULT nextval('seq_script_exec'),
            execution_id        VARCHAR UNIQUE NOT NULL,
            script_id           VARCHAR NOT NULL,
            operator_id         VARCHAR NOT NULL,
            status              VARCHAR DEFAULT 'queued',    -- queued, executing, success, failure, timeout, cancelled
            parameters          VARCHAR DEFAULT '{}',        -- JSON input parameters
            environment         VARCHAR DEFAULT '{}',        -- JSON environment variables
            timeout_seconds     INTEGER DEFAULT 300,
            start_time          TIMESTAMPTZ DEFAULT now(),
            end_time            TIMESTAMPTZ,
            exit_code           INTEGER,
            stdout              VARCHAR,                     -- First 10KB of output
            stderr              VARCHAR,                     -- First 10KB of error output
            duration_seconds    DECIMAL,
            sandbox_container_id VARCHAR                    -- Docker/VM container ID if applicable
        )
        """)

        # ══════════════════════════════════════════════════════════════════
        # v3.0 — Ontology Engine + Maya-Vigesimal Calendar 2FA
        # ══════════════════════════════════════════════════════════════════
        # A Palantir Foundry-style Object/Link digital twin
        # (ontological_object_nodes + lattice_edge_telemetry) that scan
        # results, findings, and remediation actions can be materialized
        # into and linked together for blast-radius/attack-path queries
        # (see services/ontology_engine.py); a second-factor calendar
        # challenge (maya_vigesimal_auth_sessions) that interlocks with the
        # existing v2.3 Human Approval Gate for HIGH/CRITICAL staged
        # payloads (security_agents/exploit_agent.py) rather than
        # replacing it; a named, reusable policy-enforcement table
        # (resonance_policy_enforcements) -- distinct from both
        # automation_settings (this app's small set of global on/off
        # knobs) and Batch 1's resonance_policy (named isolation-specific
        # enforcement policies), scoped generically to `module_target` so
        # any module can register its own threshold/action policy; and an
        # audit registry for Q'AIP quantum-circuit executions
        # (q_aip_inference_registry).
        #
        # All five primary keys are UUID strings (str(uuid.uuid4())), not
        # sequence-backed integers, so unlike every other table in this
        # schema none of them need a CREATE SEQUENCE.
        #
        # lattice_edge_telemetry.source_node/target_node and
        # q_aip_inference_registry.related_node_id are application-level
        # foreign keys to ontological_object_nodes(node_id) -- NOT declared
        # as SQL FOREIGN KEY REFERENCES, matching this schema's existing,
        # explicit convention elsewhere (see role_permissions' own comment:
        # "not FKs; DuckDB has no enforced FK constraints, kept consistent
        # with the rest of this schema"). This was tried and reverted after
        # two confirmed DuckDB 0.10.0 problems: (1) creating a secondary
        # index on a table BEFORE another table adds a REFERENCES pointing
        # at it raises `Cannot alter entry ... because there are entries
        # that depend on it`, forcing all CREATE TABLEs before any CREATE
        # INDEX; (2) far more seriously, once any row is referenced by a
        # REFERENCES elsewhere, DuckDB blocks UPDATE on *any* column of
        # that row -- not just the key column -- with `Violates foreign
        # key constraint`, reproduced directly against this exact schema.
        # That would make update_node_confidence() permanently fail on any
        # node that has ever been linked into the graph, which is the
        # normal case, not an edge case. get_ontological_node() and
        # create/link methods below check referenced IDs exist before
        # inserting instead (see link_ontological_nodes()/
        # register_qaip_inference()'s docstrings).
        c.execute("""
        CREATE TABLE IF NOT EXISTS ontological_object_nodes (
            node_id           VARCHAR PRIMARY KEY,
            object_type       VARCHAR NOT NULL,
            attributes_json   VARCHAR NOT NULL DEFAULT '{}',
            confidence_score  DOUBLE NOT NULL DEFAULT 1.0
                CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by        VARCHAR,
            pqc_entry_id      VARCHAR
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS lattice_edge_telemetry (
            telemetry_id      VARCHAR PRIMARY KEY,
            source_node       VARCHAR NOT NULL,   -- application-level FK to ontological_object_nodes(node_id); see comment above
            target_node       VARCHAR NOT NULL,   -- application-level FK to ontological_object_nodes(node_id); see comment above
            event_type        VARCHAR NOT NULL,
            vector_payload    VARCHAR NOT NULL DEFAULT '{}',
            recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            operator_id       VARCHAR,
            pqc_signature     VARCHAR
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS maya_vigesimal_auth_sessions (
            session_id            VARCHAR PRIMARY KEY,
            payload_id            VARCHAR NOT NULL,
            operator_id           VARCHAR NOT NULL,
            tzolkin_coordinate    VARCHAR NOT NULL,
            haab_coordinate       VARCHAR NOT NULL,
            challenge_token       VARCHAR NOT NULL UNIQUE,
            status                VARCHAR NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'denied', 'expired', 'consumed')),
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at            TIMESTAMPTZ NOT NULL,
            responded_at          TIMESTAMPTZ,
            response_token        VARCHAR,
            pqc_entry_id          VARCHAR,
            display_issued_at     TIMESTAMPTZ NOT NULL,
            display_expires_at    TIMESTAMPTZ NOT NULL
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS resonance_policy_enforcements (
            policy_id             VARCHAR PRIMARY KEY,
            module_target         VARCHAR NOT NULL,
            action_signature      VARCHAR NOT NULL,
            threshold_limit       DOUBLE NOT NULL DEFAULT 0.8
                CHECK (threshold_limit >= 0.0 AND threshold_limit <= 1.0),
            enforcement_mode      VARCHAR NOT NULL DEFAULT 'require_approval'
                CHECK (enforcement_mode IN ('require_approval', 'auto_deny', 'auto_allow', 'log_only')),
            is_active             BOOLEAN NOT NULL DEFAULT true,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by            VARCHAR,
            pqc_signature         VARCHAR
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS q_aip_inference_registry (
            inference_id          VARCHAR PRIMARY KEY,
            circuit_type          VARCHAR NOT NULL,
            execution_metrics_json VARCHAR NOT NULL DEFAULT '{}',
            pqc_signature         VARCHAR NOT NULL,
            executed_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            operator_id           VARCHAR,
            related_node_id       VARCHAR    -- application-level FK to ontological_object_nodes(node_id); see comment above
        )
        """)

        # NOTE: ontological_object_nodes and maya_vigesimal_auth_sessions
        # deliberately have NO secondary indexes (only their implicit
        # PRIMARY KEY index). Both get UPDATEd (update_node_confidence(),
        # consume_maya_session()'s status transitions) and this DuckDB
        # version has a confirmed, reproducible bug where UPDATE against a
        # table that has ANY separate CREATE INDEX raises a spurious
        # `Constraint Error: Duplicate key ... violates primary key
        # constraint` -- regardless of which column is indexed or which
        # column the UPDATE actually touches (DuckDB's own error message
        # points at "known index limitations" in their docs). Reproduced
        # directly: adding a single CREATE INDEX on either table turns
        # every UPDATE against it into a hard failure. The other three v3.0
        # tables are append-only (no UPDATE method touches them), so their
        # indexes are safe and kept for query performance.
        c.execute("CREATE INDEX IF NOT EXISTS idx_let_source ON lattice_edge_telemetry(source_node)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_let_target ON lattice_edge_telemetry(target_node)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_let_event_type ON lattice_edge_telemetry(event_type)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_let_recorded_at ON lattice_edge_telemetry(recorded_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_rpe_module ON resonance_policy_enforcements(module_target)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_rpe_active ON resonance_policy_enforcements(is_active)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_qaip_circuit ON q_aip_inference_registry(circuit_type)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_qaip_executed ON q_aip_inference_registry(executed_at)")

        self.conn.commit()
        logger.info("Schema v3.0 initialized at %s", self.db_path)

    # ======================================================================
    # v3.0 helpers — Ontology Engine, Maya-Vigesimal 2FA, resonance policy
    # enforcements, Q'AIP inference registry
    #
    # All of these use self.conn directly (the process-wide singleton's
    # already lock-protected _LockedConnection -- see its docstring above)
    # rather than opening a fresh duckdb.connect() per call. A fresh
    # connection per call would be actively wrong here: DUCKDB_PATH can be
    # ":memory:" (config.py's test config), and duckdb.connect(":memory:")
    # creates a brand new, independent, empty in-memory database on every
    # single call -- every method would see a blank schema, not the real
    # one. It would also bypass the _LockedConnection wrapper entirely,
    # reintroducing the exact concurrent-access SIGSEGV that wrapper was
    # built to fix. None of these methods wrap explicit BEGIN/COMMIT
    # either, matching this file's existing convention throughout (single
    # auto-committed statements) -- with a per-call lock, a multi-statement
    # BEGIN...COMMIT sequence provides no real cross-thread isolation
    # anyway (another thread's unrelated query could interleave between
    # the BEGIN and the COMMIT, since the lock is only held for the
    # duration of each individual execute() call).
    # ======================================================================

    def create_ontological_node(self, object_type: str, attributes: Dict[str, Any],
                                 confidence: float = 1.0, operator_id: str = "system",
                                 pqc_entry_id: Optional[str] = None) -> str:
        node_id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO ontological_object_nodes
                (node_id, object_type, attributes_json, confidence_score, created_by, pqc_entry_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (node_id, object_type, json.dumps(attributes, default=str), confidence, operator_id, pqc_entry_id),
        )
        self.conn.commit()
        return node_id

    def link_ontological_nodes(self, source_id: str, target_id: str, event_type: str,
                                vector_payload: Dict[str, Any], operator_id: str = "system",
                                pqc_signature: Optional[str] = None) -> str:
        """Raises ValueError if source_id or target_id doesn't name an
        existing node -- application-level referential-integrity check,
        since source_node/target_node are not SQL FOREIGN KEYs (see the
        ontological_object_nodes CREATE TABLE comment for why)."""
        for label, node_id in (("source_id", source_id), ("target_id", target_id)):
            if not self.get_ontological_node(node_id):
                raise ValueError(f"{label} '{node_id}' does not name an existing ontological node")
        telemetry_id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO lattice_edge_telemetry
                (telemetry_id, source_node, target_node, event_type, vector_payload, operator_id, pqc_signature)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (telemetry_id, source_id, target_id, event_type,
             json.dumps(vector_payload, default=str), operator_id, pqc_signature),
        )
        self.conn.commit()
        return telemetry_id

    def update_node_confidence(self, node_id: str, new_score: float) -> bool:
        # SELECT-then-UPDATE rather than trusting UPDATE's own result: this
        # DuckDB version's cursor.rowcount is always -1 for UPDATE
        # statements (confirmed empirically), so it can't be used to tell
        # whether a row actually matched -- same DuckDB-0.10.0-era
        # limitation already worked around elsewhere in this file (see
        # rotate_encryption_key/decide_approval_request and friends).
        existing = self.conn.execute(
            "SELECT 1 FROM ontological_object_nodes WHERE node_id = ?", (node_id,)
        ).fetchone()
        if not existing:
            return False
        self.conn.execute(
            "UPDATE ontological_object_nodes SET confidence_score = ?, updated_at = now() WHERE node_id = ?",
            (new_score, node_id),
        )
        self.conn.commit()
        return True

    def get_ontological_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM ontological_object_nodes WHERE node_id = ?", (node_id,)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, row))

    def find_ontological_node_by_attribute(
        self, object_type: Optional[str], attr_key: str, attr_value: Any,
    ) -> Optional[Dict[str, Any]]:
        """v3.0 Phase 5: best-effort lookup for a node whose
        attributes_json[attr_key] == attr_value, optionally filtered to
        object_type (None searches every type) -- used both to reuse
        (rather than duplicate) the "Asset" node for a given target
        across every payload staged against it, and to find a staged
        payload's own action node by its payload_id attribute.
        attributes_json has no index, so this scans; fine for this
        table's expected size (one node per staged payload/target, not
        per raw event), same caveat as get_audit_entries_for_payload()."""
        if object_type:
            rows = self.conn.execute(
                "SELECT * FROM ontological_object_nodes WHERE object_type = ? ORDER BY created_at DESC",
                (object_type,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM ontological_object_nodes ORDER BY created_at DESC"
            ).fetchall()
        cols = [d[0] for d in self.conn.description]
        for r in rows:
            d = dict(zip(cols, r))
            try:
                attrs = json.loads(d.get("attributes_json") or "{}")
            except Exception:
                attrs = {}
            if attrs.get(attr_key) == attr_value:
                d["attributes"] = attrs
                return d
        return None

    def query_subgraph(self, root_id: str, max_depth: int = 2) -> Dict[str, Any]:
        """Breadth-first traversal of lattice_edge_telemetry out from
        root_id, up to max_depth hops, returning every node and edge
        visited. Used for attack-path / blast-radius style queries."""
        nodes: Dict[str, Any] = {}
        edges: List[Dict[str, Any]] = []
        visited = set()
        queue = [(root_id, 0)]

        while queue:
            nid, depth = queue.pop(0)
            if nid in visited or depth > max_depth:
                continue
            visited.add(nid)

            row = self.conn.execute(
                "SELECT * FROM ontological_object_nodes WHERE node_id = ?", (nid,)
            ).fetchone()
            if not row:
                continue
            cols = [d[0] for d in self.conn.description]
            nodes[nid] = dict(zip(cols, row))

            if depth < max_depth:
                edge_rows = self.conn.execute(
                    "SELECT * FROM lattice_edge_telemetry WHERE source_node = ? OR target_node = ?",
                    (nid, nid),
                ).fetchall()
                ecols = [d[0] for d in self.conn.description]
                for erow in edge_rows:
                    e = dict(zip(ecols, erow))
                    edges.append(e)
                    other = e["target_node"] if e["source_node"] == nid else e["source_node"]
                    if other not in visited:
                        queue.append((other, depth + 1))

        return {"nodes": nodes, "edges": edges}

    def create_maya_session(self, payload_id: str, operator_id: str,
                             tzolkin: str, haab: str, challenge_token: str,
                             expires_at: datetime, pqc_entry_id: Optional[str] = None) -> str:
        session_id = str(uuid.uuid4())
        issued_at = datetime.now(timezone.utc)
        self.conn.execute(
            """
            INSERT INTO maya_vigesimal_auth_sessions
                (session_id, payload_id, operator_id, tzolkin_coordinate, haab_coordinate,
                 challenge_token, status, expires_at, pqc_entry_id,
                 display_issued_at, display_expires_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (session_id, payload_id, operator_id, tzolkin, haab, challenge_token, expires_at, pqc_entry_id,
             issued_at, expires_at),
        )
        self.conn.commit()
        return session_id

    def get_maya_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM maya_vigesimal_auth_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, row))

    def get_maya_session_by_payload_id(self, payload_id: str) -> Optional[Dict[str, Any]]:
        """Most recent Maya session for a payload_id -- approve_payload()/
        reject_payload() only have payload_id, not session_id, when they
        need to enforce the interlock."""
        row = self.conn.execute(
            "SELECT * FROM maya_vigesimal_auth_sessions WHERE payload_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (payload_id,),
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, row))

    def consume_maya_session(self, session_id: str, response_token: str, operator_id: str) -> Dict[str, Any]:
        """Verify and consume a pending Maya-Vigesimal challenge. Once
        successfully consumed, a session is single-use -- a second call
        with the correct token is rejected ('session already consumed').
        A WRONG token, however, does NOT burn the session: it just returns
        an error and leaves status='pending', so a mistyped token can be
        retried until expiry. (A wrong-token attempt permanently marking
        the session 'denied' was tried first, matching this feature's
        original spec -- but that spec's own lifecycle test submits a
        wrong token and then the correct one against the SAME session and
        expects the second call to succeed, which a permanent denial on
        first mismatch makes impossible. Retry-until-expiry is the
        behavior that actually matches the intended lifecycle.)
        Constant-time token comparison via hmac.compare_digest to avoid a
        timing side-channel on the challenge_token, consistent with this
        codebase's other signature/token comparisons
        (security_agents/edr_connector.py, etc.)."""
        row = self.conn.execute(
            "SELECT * FROM maya_vigesimal_auth_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return {"status": "error", "message": "session not found"}
        cols = [d[0] for d in self.conn.description]
        sess = dict(zip(cols, row))

        if sess["status"] != "pending":
            return {"status": "error", "message": f"session already {sess['status']}"}

        now = datetime.now(timezone.utc)
        expires_at = sess["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            self.conn.execute(
                "UPDATE maya_vigesimal_auth_sessions SET status = 'expired' WHERE session_id = ?",
                (session_id,),
            )
            self.conn.commit()
            return {"status": "error", "message": "session expired"}

        if not hmac.compare_digest(sess["challenge_token"], response_token):
            return {"status": "error", "message": "invalid response token"}

        self.conn.execute(
            """
            UPDATE maya_vigesimal_auth_sessions
            SET status = 'consumed', response_token = ?, responded_at = now()
            WHERE session_id = ?
            """,
            (response_token, session_id),
        )
        self.conn.commit()
        return {"status": "consumed", "payload_id": sess["payload_id"], "session_id": session_id}

    def upsert_resonance_policy(self, module_target: str, action_signature: str,
                                 threshold_limit: float = 0.8, enforcement_mode: str = "require_approval",
                                 is_active: bool = True, operator_id: str = "system",
                                 pqc_signature: Optional[str] = None) -> str:
        policy_id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO resonance_policy_enforcements
                (policy_id, module_target, action_signature, threshold_limit,
                 enforcement_mode, is_active, created_by, pqc_signature)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (policy_id, module_target, action_signature, threshold_limit,
             enforcement_mode, is_active, operator_id, pqc_signature),
        )
        self.conn.commit()
        return policy_id

    def list_active_policies(self, module_target: Optional[str] = None) -> List[Dict[str, Any]]:
        if module_target:
            rows = self.conn.execute(
                "SELECT * FROM resonance_policy_enforcements WHERE is_active = true AND module_target = ?",
                (module_target,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM resonance_policy_enforcements WHERE is_active = true"
            ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def register_qaip_inference(self, circuit_type: str, metrics: Dict[str, Any],
                                 pqc_signature: str, operator_id: str = "system",
                                 related_node_id: Optional[str] = None) -> str:
        """Raises ValueError if related_node_id is given but doesn't name
        an existing node -- see link_ontological_nodes()'s docstring for
        why this is an application-level check, not a SQL FOREIGN KEY."""
        if related_node_id and not self.get_ontological_node(related_node_id):
            raise ValueError(f"related_node_id '{related_node_id}' does not name an existing ontological node")
        inference_id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO q_aip_inference_registry
                (inference_id, circuit_type, execution_metrics_json, pqc_signature, operator_id, related_node_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (inference_id, circuit_type, json.dumps(metrics, default=str), pqc_signature, operator_id, related_node_id),
        )
        self.conn.commit()
        return inference_id

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

    def get_execution_log_events(self, payload_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Best-effort lookup of EXPLOIT_EXECUTED/EXPLOIT_COMPLETED
        agent_logs rows for one payload_id (v3.0 Phase 3's status
        timeline needs to know if/when a payload was actually executed).
        details is a JSON string column with no index on it, so this
        scans the recent tail rather than the whole table -- fine for a
        per-payload lookup, not meant for bulk queries."""
        rows = self.conn.execute(
            "SELECT * FROM agent_logs WHERE event IN ('EXPLOIT_EXECUTED', 'EXPLOIT_COMPLETED') "
            "ORDER BY id DESC LIMIT 2000"
        ).fetchall()
        cols = [d[0] for d in self.conn.description]
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(zip(cols, r))
            try:
                details = json.loads(d.get("details") or "{}")
            except Exception:
                details = {}
            if details.get("payload_id") == payload_id:
                d["details"] = details
                out.append(d)
                if len(out) >= limit:
                    break
        return out

    def get_audit_entries_for_payload(self, payload_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Best-effort match: pqc_audit_log entries whose action_detail
        JSON has this payload_id, newest first -- used to attach PQC
        entry IDs to a payload's status timeline (v3.0 Phase 3). Same
        scan-the-tail caveat as get_execution_log_events(): action_detail
        has no index, so this is for a single payload's context, not bulk
        audit queries (use list_pqc_audit_entries() for those)."""
        rows = self.conn.execute(
            "SELECT * FROM pqc_audit_log ORDER BY id DESC LIMIT 2000"
        ).fetchall()
        cols = [d[0] for d in self.conn.description]
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(zip(cols, r))
            try:
                detail = json.loads(d.get("action_detail") or "{}")
            except Exception:
                detail = {}
            if detail.get("payload_id") == payload_id:
                d["action_detail_parsed"] = detail
                out.append(d)
                if len(out) >= limit:
                    break
        return out

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
        # DuckDB's Python API reports rowcount == -1 for every UPDATE in
        # this version regardless of how many rows matched (verified while
        # building v2.5 -- see the CREATE TABLE / v2.5 comment block for
        # the fuller writeup), so this used to read "did this actually
        # match a row" off UPDATE ... RETURNING key_id instead of
        # result.rowcount.
        #
        # v2.6 bug fix: that RETURNING form throws
        # `duckdb.duckdb.ConstraintException: Duplicate key "id: 1"
        # violates primary key constraint` against encryption_keys
        # specifically, on the pinned duckdb==0.10.0 in requirements.txt --
        # 100% reproducible (see tests/test_v25_encryption_persistence.py,
        # which caught it: 4 tests failing on every clean install of this
        # exact pin, not a flake). encryption_keys.id is
        # `INTEGER PRIMARY KEY DEFAULT nextval('seq_enc_keys')`; this
        # version of DuckDB's UPDATE...RETURNING implementation appears to
        # re-evaluate the DEFAULT expression for the PK column during the
        # RETURNING row materialization instead of just echoing the
        # existing row, so it collides with the row's own already-assigned
        # id. Confirmed by removing RETURNING entirely (this fix) --
        # the collision disappears. Switched to the same
        # check-existence-first-then-UPDATE pattern already used
        # elsewhere in this file (e.g. rotate_user_role-adjacent helpers)
        # rather than relying on rowcount, which this DuckDB version
        # doesn't report reliably either.
        exists = self.conn.execute(
            "SELECT 1 FROM encryption_keys WHERE key_id = ?", (key_id,)
        ).fetchone()
        if not exists:
            return False
        self.conn.execute(
            "UPDATE encryption_keys SET status = 'rotated', rotated_at = now() WHERE key_id = ?",
            (key_id,),
        )
        self.conn.commit()
        return True

    def revoke_encryption_key(self, key_id: str) -> bool:
        exists = self.conn.execute(
            "SELECT 1 FROM encryption_keys WHERE key_id = ?", (key_id,)
        ).fetchone()
        if not exists:
            return False
        self.conn.execute(
            "UPDATE encryption_keys SET status = 'revoked', revoked_at = now() WHERE key_id = ?",
            (key_id,),
        )
        self.conn.commit()
        return True

    def list_encryption_keys(
        self, operator_id: Optional[str] = None, status: Optional[str] = "active"
    ) -> List[Dict[str, Any]]:
        """status=None lists every lifecycle state (active/rotated/revoked);
        the default of 'active' preserves the original behavior."""
        where, params = [], []
        if status is not None:
            where.append("status = ?"); params.append(status)
        if operator_id:
            where.append("operator_id = ?")
            params.append(operator_id)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self.conn.execute(
            f"SELECT key_id, algorithm, key_purpose, operator_id, status, "
            f"created_at, rotated_at, revoked_at, metadata "
            f"FROM encryption_keys {clause} ORDER BY id DESC",
            params,
        ).fetchall()
        cols = ["key_id", "algorithm", "key_purpose", "operator_id", "status",
                "created_at", "rotated_at", "revoked_at", "metadata"]
        return [dict(zip(cols, r)) for r in rows]

    def list_encryption_key_material(self, status: str = "active") -> List[Dict[str, Any]]:
        """
        Like list_encryption_keys(), but ALSO includes wrapped_key/
        key_wrapping_algo -- the KEK-wrapped (never raw) key bytes. This is
        for EncryptionManager's own startup rehydration only; never expose
        it over the public API the way list_encryption_keys() is exposed
        via GET /crypto/keys.
        """
        rows = self.conn.execute(
            "SELECT key_id, algorithm, key_purpose, operator_id, status, "
            "key_wrapping_algo, wrapped_key, salt_hex, metadata "
            "FROM encryption_keys WHERE status = ? ORDER BY id DESC",
            (status,),
        ).fetchall()
        cols = ["key_id", "algorithm", "key_purpose", "operator_id", "status",
                "key_wrapping_algo", "wrapped_key", "salt_hex", "metadata"]
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
        # v2.6: dropped RETURNING id -- see rotate_encryption_key()'s
        # comment for why UPDATE...RETURNING against a
        # DEFAULT nextval(...) primary key throws a spurious duplicate-key
        # ConstraintException on the pinned duckdb==0.10.0. Count matching
        # rows before the UPDATE instead.
        expired_count = self.conn.execute(
            "SELECT COUNT(*) FROM threat_intel WHERE expiry < now() AND active = true"
        ).fetchone()[0]
        self.conn.execute(
            "UPDATE threat_intel SET active = false WHERE expiry < now() AND active = true"
        )
        self.conn.commit()
        return expired_count

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
                  payload_detail (dict/JSON), pqc_entry_id, expires_at,
                  origin_module (v2.5 — which Ares pillar raised this, e.g.
                  'GOD_S_EYE_RECON', 'HORIZON', 'agentic_canvas'; folded into
                  payload_detail JSON rather than a dedicated column -- see
                  the v2.5 CREATE TABLE comment above for why: an ALTER
                  TABLE ADD COLUMN here hit a reproducible DuckDB WAL-replay
                  crash on this table, which already has production rows)
        """
        payload_detail = dict(record.get("payload_detail", {}) or {})
        if record.get("origin_module") is not None:
            payload_detail["origin_module"] = record["origin_module"]

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
                json.dumps(payload_detail, default=str),
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
        # v2.6: dropped RETURNING request_id -- see rotate_encryption_key()'s
        # comment for the root cause (UPDATE...RETURNING against a
        # DEFAULT nextval(...) primary key throws a spurious duplicate-key
        # ConstraintException on the pinned duckdb==0.10.0). This exact bug
        # broke the Human Approval Gate's approve/deny path end to end --
        # every approval_gate test that called this method failed.
        exists = self.conn.execute(
            "SELECT 1 FROM approval_requests WHERE request_id = ? AND status = 'pending'",
            (request_id,),
        ).fetchone()
        if not exists:
            return False
        self.conn.execute(
            """
            UPDATE approval_requests
            SET status = ?, decided_by = ?, decided_at = now(), decision_reason = ?
            WHERE request_id = ? AND status = 'pending'
            """,
            (decision, decided_by, reason, request_id),
        )
        self.conn.commit()
        return True

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
        expired_count = self.conn.execute(
            "SELECT COUNT(*) FROM approval_requests "
            "WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at < now()"
        ).fetchone()[0]
        self.conn.execute(
            "UPDATE approval_requests SET status = 'expired' "
            "WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at < now()"
        )
        self.conn.commit()
        return expired_count

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
    # v2.4 — Horizon (AI Safety events)
    # ======================================================================

    def insert_ai_safety_event(self, record: Dict[str, Any]) -> str:
        """Required: event_id. Optional: client_id, soc_compliance_tier,
        protection_layer, alert_severity, regulatory_schema_status."""
        self.conn.execute(
            """
            INSERT INTO ai_safety_events
                (event_id, client_id, soc_compliance_tier, protection_layer,
                 alert_severity, regulatory_schema_status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (record["event_id"], record.get("client_id"), record.get("soc_compliance_tier"),
             record.get("protection_layer"), record.get("alert_severity", 0),
             record.get("regulatory_schema_status", "Syncing")),
        )
        self.conn.commit()
        return record["event_id"]

    def list_ai_safety_events(self, client_id: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        if client_id:
            rows = self.conn.execute(
                "SELECT * FROM ai_safety_events WHERE client_id = ? ORDER BY event_timestamp DESC LIMIT ?",
                (client_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM ai_safety_events ORDER BY event_timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def horizon_regulatory_summary(self) -> Dict[str, Any]:
        """Executive rollup: alert-severity distribution + compliance-status gaps."""
        by_severity = self.conn.execute(
            "SELECT alert_severity, COUNT(*) FROM ai_safety_events GROUP BY alert_severity ORDER BY 1 DESC"
        ).fetchall()
        by_status = self.conn.execute(
            "SELECT regulatory_schema_status, COUNT(*) FROM ai_safety_events GROUP BY regulatory_schema_status"
        ).fetchall()
        by_tier = self.conn.execute(
            "SELECT soc_compliance_tier, COUNT(*) FROM ai_safety_events "
            "WHERE regulatory_schema_status = 'Attention Required' GROUP BY soc_compliance_tier"
        ).fetchall()
        total = self.conn.execute("SELECT COUNT(*) FROM ai_safety_events").fetchone()[0]
        return {
            "total_events": total,
            "by_severity": {str(r[0]): r[1] for r in by_severity},
            "by_regulatory_status": {r[0]: r[1] for r in by_status},
            "compliance_gaps_by_tier": {r[0] or "unspecified": r[1] for r in by_tier},
        }

    # ======================================================================
    # v2.4 — Agentic Canvas (patch deployment tasks)
    # ======================================================================

    def create_remediation_task(self, record: Dict[str, Any]) -> str:
        """Required: task_id. Optional: target_machine_ip, patch_id,
        autonomous_action_taken, approval_request_id."""
        self.conn.execute(
            """
            INSERT INTO agentic_remediation_tasks
                (task_id, target_machine_ip, patch_id, autonomous_action_taken,
                 deployment_progress, remediation_status, operator_approval_status,
                 approval_request_id)
            VALUES (?, ?, ?, ?, 0, 'queued', 'pending', ?)
            """,
            (record["task_id"], record.get("target_machine_ip"), record.get("patch_id"),
             record.get("autonomous_action_taken"), record.get("approval_request_id")),
        )
        self.conn.commit()
        return record["task_id"]

    def sync_remediation_task_approval(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Pull the linked approval_requests row's current status into this
        task's operator_approval_status — call before advancing progress."""
        task = self.get_remediation_task(task_id)
        if not task or not task.get("approval_request_id"):
            return task
        approval = self.get_approval_request(task["approval_request_id"])
        if approval:
            self.conn.execute(
                "UPDATE agentic_remediation_tasks SET operator_approval_status = ?, updated_at = now() WHERE task_id = ?",
                (approval["status"], task_id),
            )
            self.conn.commit()
            task = self.get_remediation_task(task_id)
        return task

    def advance_remediation_task(self, task_id: str, progress: int, status: Optional[str] = None) -> Dict[str, Any]:
        """Advance deployment_progress. Refuses to move past 0 unless the
        linked approval is 'approved' — mirrors the same not-unless-approved
        rule as ExploitAgent.execute_staged_payload()."""
        task = self.sync_remediation_task_approval(task_id)
        if not task:
            return {"status": "error", "message": "task not found"}
        if progress > 0 and task.get("operator_approval_status") != "approved":
            return {"status": "blocked", "message": "patch not approved by a human operator", "task_id": task_id}
        self.conn.execute(
            "UPDATE agentic_remediation_tasks SET deployment_progress = ?, remediation_status = ?, updated_at = now() WHERE task_id = ?",
            (progress, status or ("completed" if progress >= 100 else "in_progress"), task_id),
        )
        self.conn.commit()
        return self.get_remediation_task(task_id)

    def get_remediation_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM agentic_remediation_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, row))

    def list_remediation_tasks(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM agentic_remediation_tasks WHERE remediation_status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM agentic_remediation_tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    # ======================================================================
    # v2.4 — Resonance / Global Dashboard
    # ======================================================================

    def upsert_fleet_host(self, record: Dict[str, Any]) -> str:
        existing = self.conn.execute(
            "SELECT machine_id FROM global_fleet_matrix WHERE machine_id = ?", (record["machine_id"],)
        ).fetchone()
        if existing:
            self.conn.execute(
                """
                UPDATE global_fleet_matrix
                SET network_segment = ?, predictive_threat_score = ?, resonance_load_metric = ?,
                    last_diagnostic_timestamp = now(), is_quarantined = ?
                WHERE machine_id = ?
                """,
                (record.get("network_segment"), record.get("predictive_threat_score", 0.0),
                 record.get("resonance_load_metric", 0.0), record.get("is_quarantined", False),
                 record["machine_id"]),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO global_fleet_matrix
                    (machine_id, network_segment, predictive_threat_score, resonance_load_metric, is_quarantined)
                VALUES (?, ?, ?, ?, ?)
                """,
                (record["machine_id"], record.get("network_segment"),
                 record.get("predictive_threat_score", 0.0), record.get("resonance_load_metric", 0.0),
                 record.get("is_quarantined", False)),
            )
        self.conn.commit()
        return record["machine_id"]

    def list_fleet_matrix(self, quarantined_only: bool = False) -> List[Dict[str, Any]]:
        clause = "WHERE is_quarantined = true" if quarantined_only else ""
        rows = self.conn.execute(
            f"SELECT * FROM global_fleet_matrix {clause} ORDER BY predictive_threat_score DESC"
        ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def resonance_settings_snapshot(self, config_id: str) -> Dict[str, Any]:
        """
        Records a global_security_settings row DERIVED from the real,
        already-authoritative tables (operators for RBAC, encryption_keys +
        pqc_audit_log for key management / crypto standard) rather than
        letting this table drift into being an independent, editable copy
        of the truth. This is intentionally the only write path in — no
        separate "set_security_settings" that could disagree with reality.
        """
        import hashlib
        roles = self.conn.execute(
            "SELECT operator_id, role FROM operators WHERE active = true ORDER BY operator_id"
        ).fetchall()
        rbac_hash = hashlib.sha3_256(json.dumps(roles, default=str).encode()).hexdigest()[:32]
        active_keys = self.conn.execute(
            "SELECT COUNT(*) FROM encryption_keys WHERE status = 'active'"
        ).fetchone()[0]
        pqc_entries = self.conn.execute("SELECT COUNT(*) FROM pqc_audit_log").fetchone()[0]
        key_status = f"{active_keys} active key(s), {pqc_entries} PQC audit entries"

        self.conn.execute(
            """
            INSERT INTO global_security_settings
                (config_id, rbac_policy_hash, api_encryption_standard, key_management_status, trade_secret_isolation)
            VALUES (?, ?, 'ML-DSA-65 + AES-256-GCM', ?, true)
            """,
            (config_id, rbac_hash, key_status),
        )
        self.conn.commit()
        return self.get_security_settings(config_id)

    def get_security_settings(self, config_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM global_security_settings WHERE config_id = ?", (config_id,)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, row))

    def latest_security_settings(self) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM global_security_settings ORDER BY recorded_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, row))

    # ======================================================================
    # v2.4 — Q'AIP Logic & Quantum Orchestration
    # ======================================================================

    def log_orbital_comm(self, record: Dict[str, Any]) -> str:
        """Required: comm_id, event_type. Optional: computational_agent_id,
        inference_chain_hash, quantum_entropy_seed, execution_latency_ms."""
        self.conn.execute(
            """
            INSERT INTO quantum_orbital_comms
                (comm_id, event_type, computational_agent_id, inference_chain_hash,
                 quantum_entropy_seed, execution_latency_ms)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (record["comm_id"], record["event_type"], record.get("computational_agent_id"),
             record.get("inference_chain_hash"), record.get("quantum_entropy_seed"),
             record.get("execution_latency_ms")),
        )
        self.conn.commit()
        return record["comm_id"]

    def list_orbital_comms(self, event_type: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if event_type:
            rows = self.conn.execute(
                "SELECT * FROM quantum_orbital_comms WHERE event_type = ? ORDER BY recorded_at DESC LIMIT ?",
                (event_type, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM quantum_orbital_comms ORDER BY recorded_at DESC LIMIT ?", (limit,)
            ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def orbital_comms_stats(self) -> Dict[str, Any]:
        total = self.conn.execute("SELECT COUNT(*) FROM quantum_orbital_comms").fetchone()[0]
        avg_latency = self.conn.execute("SELECT AVG(execution_latency_ms) FROM quantum_orbital_comms").fetchone()[0]
        by_type = self.conn.execute(
            "SELECT event_type, COUNT(*) FROM quantum_orbital_comms GROUP BY event_type"
        ).fetchall()
        return {
            "total": total,
            "avg_latency_ms": round(avg_latency, 2) if avg_latency is not None else None,
            "by_event_type": {r[0]: r[1] for r in by_type},
        }

    # ======================================================================
    # v2.5 — Ares Unified Control Plane
    # ======================================================================

    def insert_unified_security_event(self, record: Dict[str, Any]) -> str:
        """Required: event_id, source_module. Optional: threat_category,
        severity_score, raw_payload (dict), approval_request_id."""
        self.conn.execute(
            """
            INSERT INTO unified_security_events
                (event_id, source_module, threat_category, severity_score,
                 raw_payload, approval_request_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (record["event_id"], record["source_module"], record.get("threat_category"),
             record.get("severity_score", 0.0),
             json.dumps(record.get("raw_payload", {}), default=str),
             record.get("approval_request_id")),
        )
        self.conn.commit()
        return record["event_id"]

    def link_unified_event_approval(self, event_id: str, approval_request_id: str) -> bool:
        exists = self.conn.execute(
            "SELECT 1 FROM unified_security_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        if not exists:
            return False
        self.conn.execute(
            "UPDATE unified_security_events SET approval_request_id = ? WHERE event_id = ?",
            (approval_request_id, event_id),
        )
        self.conn.commit()
        return True

    def list_unified_security_events(
        self, source_module: Optional[str] = None, threat_category: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if source_module:
            clauses.append("source_module = ?"); params.append(source_module)
        if threat_category:
            clauses.append("threat_category = ?"); params.append(threat_category)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM unified_security_events {where} ORDER BY timestamp DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        cols = [d[0] for d in self.conn.description]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            d["raw_payload"] = json.loads(d.get("raw_payload") or "{}")
            out.append(d)
        return out

    def unified_security_events_stats(self) -> Dict[str, Any]:
        total = self.conn.execute("SELECT COUNT(*) FROM unified_security_events").fetchone()[0]
        avg_sev = self.conn.execute("SELECT AVG(severity_score) FROM unified_security_events").fetchone()[0]
        by_source = self.conn.execute(
            "SELECT source_module, COUNT(*) FROM unified_security_events GROUP BY source_module"
        ).fetchall()
        by_category = self.conn.execute(
            "SELECT threat_category, COUNT(*) FROM unified_security_events "
            "WHERE threat_category IS NOT NULL GROUP BY threat_category"
        ).fetchall()
        blocked = self.conn.execute(
            "SELECT COUNT(*) FROM unified_security_events WHERE severity_score >= 0.5"
        ).fetchone()[0]
        return {
            "total": total,
            "avg_severity": round(avg_sev, 4) if avg_sev is not None else None,
            "by_source_module": {r[0]: r[1] for r in by_source},
            "by_threat_category": {r[0]: r[1] for r in by_category},
            "threats_blocked_count": blocked,
        }

    def horizon_trust_fabric_snapshot(self, fabric_id: str, operator_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Records a horizon_trust_fabric row DERIVED from real tables --
        ai_safety_events (via horizon_regulatory_summary), unified_security_events,
        and fabric_modules -- rather than an independently-settable status
        blob. Same "one write path in" pattern as resonance_settings_snapshot().
        """
        reg = self.horizon_regulatory_summary()
        total_events = reg["total_events"]
        attention = reg["by_regulatory_status"].get("Attention Required", 0)
        compliance_pct = 100.0 if total_events == 0 else round(
            100.0 * (total_events - attention) / total_events, 1
        )

        uni_stats = self.unified_security_events_stats()
        by_cat = uni_stats["by_threat_category"]

        def _status(count: int, clear: str = "CLEAR", flagged: str = "ATTENTION_REQUIRED") -> str:
            return flagged if count else clear

        shadow_ai_status = _status(by_cat.get("SHADOW_AI", 0), flagged="DETECTED")
        soc2_status = _status(attention, clear="COMPLIANT")
        dlp_status = _status(by_cat.get("DLP_MATCH", 0), flagged="MATCHES_DETECTED")
        # "Open" = high-severity and not yet routed through the approval
        # gate -- once it's staged for human review it's no longer an
        # unaddressed adversarial threat, it's a pending decision.
        critical_open = self.conn.execute(
            "SELECT COUNT(*) FROM unified_security_events "
            "WHERE severity_score >= 0.8 AND approval_request_id IS NULL"
        ).fetchone()[0]
        adversarial_status = _status(critical_open, clear="NOMINAL", flagged="ACTIVE_THREATS_DETECTED")

        modules = self.list_fabric_modules()
        if not modules:
            fabric_status = "UNINITIALIZED"
        elif all(m["status"] == "active" for m in modules):
            fabric_status = "SECURE"
        else:
            fabric_status = "DEGRADED"

        self.conn.execute(
            """
            INSERT INTO horizon_trust_fabric
                (fabric_id, operator_id, compliance_coverage_pct, active_agent_count,
                 threats_blocked_count, shadow_ai_status, soc2_compliance_status,
                 adversarial_defense_status, dlp_status, fabric_status, last_schema_sync)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
            """,
            (fabric_id, operator_id, compliance_pct, len(WIRED_SECURITY_AGENTS),
             uni_stats["threats_blocked_count"], shadow_ai_status, soc2_status,
             adversarial_status, dlp_status, fabric_status),
        )
        self.conn.commit()
        return self.get_horizon_trust_fabric(fabric_id)

    def get_horizon_trust_fabric(self, fabric_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM horizon_trust_fabric WHERE fabric_id = ?", (fabric_id,)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, row))

    def latest_horizon_trust_fabric(self) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM horizon_trust_fabric ORDER BY recorded_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, row))

    # ======================================================================
    # v2.6 — IAM (users / roles / permissions / sessions / API keys / audit)
    # ======================================================================

    def create_user(self, user_id: str, username: str, email: Optional[str], password_hash: str) -> str:
        self.conn.execute(
            "INSERT INTO users (user_id, username, email, password_hash) VALUES (?, ?, ?, ?)",
            (user_id, username, email, password_hash),
        )
        self.conn.commit()
        return user_id

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, row))

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, row))

    def count_users(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return row[0] if row else 0

    def list_users(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT user_id, username, email, mfa_enabled, status, created_at, last_login_at "
            "FROM users ORDER BY created_at"
        ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def record_login_success(self, user_id: str, ip_address: Optional[str]) -> None:
        self.conn.execute(
            "UPDATE users SET failed_logins = 0, last_login_at = now(), last_login_ip = ? WHERE user_id = ?",
            (ip_address, user_id),
        )
        self.conn.commit()

    def record_login_failure(self, user_id: str, lock_after: int = 5, lock_minutes: int = 15) -> int:
        self.conn.execute(
            "UPDATE users SET failed_logins = failed_logins + 1 WHERE user_id = ?", (user_id,)
        )
        row = self.conn.execute("SELECT failed_logins FROM users WHERE user_id = ?", (user_id,)).fetchone()
        failed = row[0] if row else 0
        if failed >= lock_after:
            self.conn.execute(
                "UPDATE users SET locked_until = now() + INTERVAL '{}' MINUTE WHERE user_id = ?".format(lock_minutes),
                (user_id,),
            )
        self.conn.commit()
        return failed

    def set_mfa_secret(self, user_id: str, secret: str, enabled: bool) -> None:
        self.conn.execute(
            "UPDATE users SET mfa_secret = ?, mfa_enabled = ? WHERE user_id = ?",
            (secret, enabled, user_id),
        )
        self.conn.commit()

    def upsert_role(self, role_key: str, label: str, description: str = "", is_system: bool = False) -> None:
        exists = self.conn.execute("SELECT 1 FROM roles WHERE role_key = ?", (role_key,)).fetchone()
        if exists:
            return
        self.conn.execute(
            "INSERT INTO roles (role_key, label, description, is_system) VALUES (?, ?, ?, ?)",
            (role_key, label, description, is_system),
        )
        self.conn.commit()

    def upsert_permission(self, permission_key: str, label: str, category: str = "") -> None:
        exists = self.conn.execute(
            "SELECT 1 FROM permissions WHERE permission_key = ?", (permission_key,)
        ).fetchone()
        if exists:
            return
        self.conn.execute(
            "INSERT INTO permissions (permission_key, label, category) VALUES (?, ?, ?)",
            (permission_key, label, category),
        )
        self.conn.commit()

    def grant_role_permission(self, role_key: str, permission_key: str) -> None:
        exists = self.conn.execute(
            "SELECT 1 FROM role_permissions WHERE role_key = ? AND permission_key = ?",
            (role_key, permission_key),
        ).fetchone()
        if exists:
            return
        self.conn.execute(
            "INSERT INTO role_permissions (role_key, permission_key) VALUES (?, ?)",
            (role_key, permission_key),
        )
        self.conn.commit()

    def assign_user_role(self, user_id: str, role_key: str) -> None:
        exists = self.conn.execute(
            "SELECT 1 FROM user_roles WHERE user_id = ? AND role_key = ?", (user_id, role_key)
        ).fetchone()
        if exists:
            return
        self.conn.execute(
            "INSERT INTO user_roles (user_id, role_key) VALUES (?, ?)", (user_id, role_key)
        )
        self.conn.commit()

    def revoke_user_role(self, user_id: str, role_key: str) -> None:
        self.conn.execute(
            "DELETE FROM user_roles WHERE user_id = ? AND role_key = ?", (user_id, role_key)
        )
        self.conn.commit()

    def list_roles(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM roles ORDER BY role_key").fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def list_permissions(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM permissions ORDER BY category, permission_key").fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def get_role_permissions(self, role_key: str) -> List[str]:
        rows = self.conn.execute(
            "SELECT permission_key FROM role_permissions WHERE role_key = ?", (role_key,)
        ).fetchall()
        return [r[0] for r in rows]

    def get_user_roles(self, user_id: str) -> List[str]:
        rows = self.conn.execute(
            "SELECT role_key FROM user_roles WHERE user_id = ?", (user_id,)
        ).fetchall()
        return [r[0] for r in rows]

    def get_user_permissions(self, user_id: str) -> List[str]:
        rows = self.conn.execute(
            """
            SELECT DISTINCT rp.permission_key FROM user_roles ur
            JOIN role_permissions rp ON rp.role_key = ur.role_key
            WHERE ur.user_id = ?
            """,
            (user_id,),
        ).fetchall()
        return [r[0] for r in rows]

    def create_session(self, session_id: str, user_id: str, expires_at: datetime,
                        ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> None:
        self.conn.execute(
            "INSERT INTO sessions (session_id, user_id, expires_at, ip_address, user_agent) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, expires_at, ip_address, user_agent),
        )
        self.conn.commit()

    def is_session_valid(self, session_id: str) -> bool:
        row = self.conn.execute(
            "SELECT revoked, expires_at FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return False
        revoked, expires_at = row
        if revoked:
            return False
        if expires_at and expires_at < datetime.now(timezone.utc).replace(tzinfo=expires_at.tzinfo):
            return False
        return True

    def revoke_session(self, session_id: str) -> bool:
        self.conn.execute("UPDATE sessions SET revoked = true WHERE session_id = ?", (session_id,))
        self.conn.commit()
        return True

    def create_api_key(self, key_id: str, key_hash: str, owner_user_id: str, label: str,
                        scopes: List[str], expires_at: Optional[datetime] = None) -> None:
        self.conn.execute(
            "INSERT INTO api_keys (key_id, key_hash, owner_user_id, label, scopes, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (key_id, key_hash, owner_user_id, label, json.dumps(scopes), expires_at),
        )
        self.conn.commit()

    def list_api_keys(self, owner_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if owner_user_id:
            rows = self.conn.execute(
                "SELECT key_id, owner_user_id, label, scopes, status, created_at, last_used_at, expires_at "
                "FROM api_keys WHERE owner_user_id = ? ORDER BY created_at DESC",
                (owner_user_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT key_id, owner_user_id, label, scopes, status, created_at, last_used_at, expires_at "
                "FROM api_keys ORDER BY created_at DESC"
            ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def get_api_key_by_id(self, key_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM api_keys WHERE key_id = ?", (key_id,)).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, row))

    def touch_api_key(self, key_id: str) -> None:
        self.conn.execute("UPDATE api_keys SET last_used_at = now() WHERE key_id = ?", (key_id,))
        self.conn.commit()

    def revoke_api_key(self, key_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM api_keys WHERE key_id = ?", (key_id,)).fetchone()
        if not row:
            return False
        self.conn.execute(
            "UPDATE api_keys SET status = 'revoked', revoked_at = now() WHERE key_id = ?", (key_id,)
        )
        self.conn.commit()
        return True

    def insert_audit_entry(self, entry: Dict[str, Any]) -> int:
        self.conn.execute(
            """
            INSERT INTO audit_log
                (actor_user_id, actor_label, action, resource_type, resource_id, outcome, ip_address, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.get("actor_user_id"), entry.get("actor_label"), entry.get("action"),
                entry.get("resource_type"), entry.get("resource_id"), entry.get("outcome", "success"),
                entry.get("ip_address"), json.dumps(entry.get("detail", {}), default=str),
            ),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT currval('seq_audit_log')").fetchone()
        return row[0] if row else -1

    def list_audit_entries(self, actor_user_id: Optional[str] = None, action: Optional[str] = None,
                            limit: int = 100) -> List[Dict[str, Any]]:
        query = "SELECT * FROM audit_log WHERE 1=1"
        params: List[Any] = []
        if actor_user_id:
            query += " AND actor_user_id = ?"
            params.append(actor_user_id)
        if action:
            query += " AND action = ?"
            params.append(action)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(query, tuple(params)).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    # ======================================================================
    # v2.6 — Trade Secrets / EAS R&D Vault
    # ======================================================================

    def vault_insert(self, item_id: str, title: str, classification: str, owner_user_id: str,
                      ciphertext_envelope: Dict[str, Any], content_sha3_256: str,
                      allowed_roles: List[str]) -> str:
        self.conn.execute(
            """
            INSERT INTO trade_secrets_vault
                (item_id, title, classification, owner_user_id, ciphertext_envelope,
                 content_sha3_256, allowed_roles)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (item_id, title, classification, owner_user_id, json.dumps(ciphertext_envelope),
             content_sha3_256, json.dumps(allowed_roles)),
        )
        self.conn.commit()
        return item_id

    def vault_list(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT item_id, title, classification, owner_user_id, allowed_roles, "
            "created_at, updated_at, status FROM trade_secrets_vault WHERE status = 'active' "
            "ORDER BY created_at DESC"
        ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def vault_get(self, item_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM trade_secrets_vault WHERE item_id = ?", (item_id,)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, row))

    def vault_archive(self, item_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM trade_secrets_vault WHERE item_id = ?", (item_id,)).fetchone()
        if not row:
            return False
        self.conn.execute(
            "UPDATE trade_secrets_vault SET status = 'archived', updated_at = now() WHERE item_id = ?",
            (item_id,),
        )
        self.conn.commit()
        return True

    # ======================================================================
    # v2.6 — Dark Web Monitoring
    # ======================================================================

    def darkweb_add_watch(self, watch_id: str, identifier: str, identifier_type: str,
                           added_by: Optional[str]) -> str:
        self.conn.execute(
            "INSERT INTO darkweb_watchlist (watch_id, identifier, identifier_type, added_by) "
            "VALUES (?, ?, ?, ?)",
            (watch_id, identifier, identifier_type, added_by),
        )
        self.conn.commit()
        return watch_id

    def darkweb_list_watch(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM darkweb_watchlist WHERE active = true ORDER BY added_at DESC"
        ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def darkweb_touch_watch(self, watch_id: str) -> None:
        self.conn.execute(
            "UPDATE darkweb_watchlist SET last_checked_at = now() WHERE watch_id = ?", (watch_id,)
        )
        self.conn.commit()

    def darkweb_insert_finding(self, finding: Dict[str, Any]) -> str:
        self.conn.execute(
            """
            INSERT INTO darkweb_findings
                (finding_id, watch_id, source, breach_name, breach_date, data_classes, severity)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                finding["finding_id"], finding["watch_id"], finding["source"],
                finding.get("breach_name"), finding.get("breach_date"),
                json.dumps(finding.get("data_classes", [])), finding.get("severity", "MEDIUM"),
            ),
        )
        self.conn.commit()
        return finding["finding_id"]

    def darkweb_list_findings(self, watch_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if watch_id:
            rows = self.conn.execute(
                "SELECT * FROM darkweb_findings WHERE watch_id = ? ORDER BY discovered_at DESC LIMIT ?",
                (watch_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM darkweb_findings ORDER BY discovered_at DESC LIMIT ?", (limit,)
            ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    # ======================================================================
    # v2.6 — Awareness Training + Phishing Campaigns
    # ======================================================================

    def training_seed_module(self, module_key: str, title: str, category: str,
                              duration_min: int = 10, passing_score: int = 80) -> None:
        exists = self.conn.execute(
            "SELECT 1 FROM training_modules WHERE module_key = ?", (module_key,)
        ).fetchone()
        if exists:
            return
        self.conn.execute(
            "INSERT INTO training_modules (module_key, title, category, duration_min, passing_score) "
            "VALUES (?, ?, ?, ?, ?)",
            (module_key, title, category, duration_min, passing_score),
        )
        self.conn.commit()

    def training_list_modules(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM training_modules WHERE active = true ORDER BY category, title"
        ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def training_record_completion(self, completion_id: str, module_key: str, user_id: str,
                                    score: int, passed: bool) -> str:
        self.conn.execute(
            "INSERT INTO training_completions (completion_id, module_key, user_id, score, passed) "
            "VALUES (?, ?, ?, ?, ?)",
            (completion_id, module_key, user_id, score, passed),
        )
        self.conn.commit()
        return completion_id

    def training_completion_stats(self) -> Dict[str, Any]:
        row = self.conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN passed THEN 1 ELSE 0 END), AVG(score) FROM training_completions"
        ).fetchone()
        total, passed, avg_score = (row or (0, 0, None))
        return {
            "total_completions": total or 0,
            "passed": passed or 0,
            "pass_rate_pct": round(100.0 * (passed or 0) / total, 1) if total else 0.0,
            "avg_score": round(avg_score, 1) if avg_score is not None else None,
        }

    def phishing_create_campaign(self, campaign_id: str, name: str, template_key: str,
                                  launched_by: str, targets: List[str]) -> str:
        self.conn.execute(
            "INSERT INTO phishing_campaigns (campaign_id, name, template_key, launched_by, status) "
            "VALUES (?, ?, ?, ?, 'active')",
            (campaign_id, name, template_key, launched_by),
        )
        self.conn.execute("UPDATE phishing_campaigns SET launched_at = now() WHERE campaign_id = ?", (campaign_id,))
        for email in targets:
            self.conn.execute(
                "INSERT INTO phishing_targets (campaign_id, target_email, sent_at) VALUES (?, ?, now())",
                (campaign_id, email),
            )
        self.conn.commit()
        return campaign_id

    def phishing_list_campaigns(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM phishing_campaigns ORDER BY launched_at DESC NULLS LAST"
        ).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def phishing_campaign_stats(self, campaign_id: str) -> Dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT COUNT(*),
                   SUM(CASE WHEN opened_at IS NOT NULL THEN 1 ELSE 0 END),
                   SUM(CASE WHEN clicked_at IS NOT NULL THEN 1 ELSE 0 END),
                   SUM(CASE WHEN reported_at IS NOT NULL THEN 1 ELSE 0 END)
            FROM phishing_targets WHERE campaign_id = ?
            """,
            (campaign_id,),
        ).fetchone()
        sent, opened, clicked, reported = (row or (0, 0, 0, 0))
        return {
            "sent": sent or 0, "opened": opened or 0,
            "clicked": clicked or 0, "reported": reported or 0,
            "click_rate_pct": round(100.0 * (clicked or 0) / sent, 1) if sent else 0.0,
        }

    # ======================================================================
    # v2.7 — Detection & Response
    # ======================================================================

    def insert_remediation_action(self, record: Dict[str, Any]) -> str:
        self.conn.execute(
            """
            INSERT INTO remediation_actions
                (action_id, action_type, target, status, risk_level,
                 approval_request_id, operator_id, d3fend_technique, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["action_id"], record["action_type"], record.get("target"),
                record["status"], record.get("risk_level", "LOW"),
                record.get("approval_request_id"), record.get("operator_id"),
                record.get("d3fend_technique"), json.dumps(record.get("detail", {}), default=str),
            ),
        )
        self.conn.commit()
        return record["action_id"]

    def update_remediation_action_status(self, action_id: str, status: str) -> bool:
        exists = self.conn.execute(
            "SELECT 1 FROM remediation_actions WHERE action_id = ?", (action_id,)
        ).fetchone()
        if not exists:
            return False
        self.conn.execute(
            "UPDATE remediation_actions SET status = ?, resolved_at = now() WHERE action_id = ?",
            (status, action_id),
        )
        self.conn.commit()
        return True

    def update_remediation_action_status_by_approval(self, approval_request_id: str, status: str) -> bool:
        """
        Same as update_remediation_action_status() but keyed by
        approval_request_id instead of action_id. Needed for the
        v2.8 enforce endpoint (routers/response.py): the remediation_actions
        row a staged isolate/quarantine action created has its OWN
        action_id (see _record_action's `action_id = str(uuid.uuid4())`) --
        it is NOT the same value as the approval_requests.request_id it's
        linked to via the approval_request_id column. Calling the
        action_id-keyed update with an approval_request_id silently
        matched zero rows -- caught by
        test_v28_policy_enforcement.py::test_enforce_endpoint_end_to_end_via_webhook,
        which checked the row's status after a real enforce call and found
        it still 'staged' despite the connector reporting 'enforced'.
        """
        exists = self.conn.execute(
            "SELECT 1 FROM remediation_actions WHERE approval_request_id = ?", (approval_request_id,)
        ).fetchone()
        if not exists:
            return False
        self.conn.execute(
            "UPDATE remediation_actions SET status = ?, resolved_at = now() WHERE approval_request_id = ?",
            (status, approval_request_id),
        )
        self.conn.commit()
        return True

    def list_remediation_actions(self, action_type: Optional[str] = None,
                                  status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        query = "SELECT * FROM remediation_actions WHERE 1=1"
        params: List[Any] = []
        if action_type:
            query += " AND action_type = ?"
            params.append(action_type)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(query, tuple(params)).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def remediation_stats(self) -> Dict[str, Any]:
        rows = self.conn.execute(
            "SELECT action_type, status, COUNT(*) FROM remediation_actions GROUP BY action_type, status"
        ).fetchall()
        by_type: Dict[str, Dict[str, int]] = {}
        for action_type, status, count in rows:
            by_type.setdefault(action_type, {})[status] = count
        total = self.conn.execute("SELECT COUNT(*) FROM remediation_actions").fetchone()[0]
        return {"total": total, "by_type": by_type}

    # ======================================================================
    # v2.8 — Resonance policy (real automation knobs)
    # ======================================================================

    def seed_policy(self, policy_key: str, value: Any, value_type: str, label: str, description: str) -> None:
        exists = self.conn.execute(
            "SELECT 1 FROM automation_settings WHERE policy_key = ?", (policy_key,)
        ).fetchone()
        if exists:
            return
        self.conn.execute(
            "INSERT INTO automation_settings (policy_key, value, value_type, label, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (policy_key, json.dumps(value), value_type, label, description),
        )
        self.conn.commit()

    def get_policy(self, policy_key: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM automation_settings WHERE policy_key = ?", (policy_key,)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        d = dict(zip(cols, row))
        d["value"] = json.loads(d["value"])
        return d

    def get_policy_value(self, policy_key: str, default: Any = None) -> Any:
        p = self.get_policy(policy_key)
        return p["value"] if p is not None else default

    def list_policy(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM automation_settings ORDER BY policy_key").fetchall()
        cols = [d[0] for d in self.conn.description]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            d["value"] = json.loads(d["value"])
            out.append(d)
        return out

    def set_policy_value(self, policy_key: str, value: Any, updated_by: str) -> bool:
        exists = self.conn.execute(
            "SELECT value_type FROM automation_settings WHERE policy_key = ?", (policy_key,)
        ).fetchone()
        if not exists:
            return False
        value_type = exists[0]
        if value_type == "bool" and not isinstance(value, bool):
            raise ValueError(f"policy '{policy_key}' expects a bool value")
        if value_type == "number" and not isinstance(value, (int, float)):
            raise ValueError(f"policy '{policy_key}' expects a numeric value")
        self.conn.execute(
            "UPDATE automation_settings SET value = ?, updated_by = ?, updated_at = now() WHERE policy_key = ?",
            (json.dumps(value), updated_by, policy_key),
        )
        self.conn.commit()
        return True

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
            "ai_safety_events", "agentic_remediation_tasks", "global_fleet_matrix",
            "global_security_settings", "quantum_orbital_comms",
            "unified_security_events", "horizon_trust_fabric",
            "users", "roles", "permissions", "sessions", "api_keys", "audit_log",
            "trade_secrets_vault", "darkweb_watchlist", "darkweb_findings",
            "training_modules", "training_completions", "phishing_campaigns", "phishing_targets",
            "remediation_actions", "automation_settings",
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


# ==============================================================================
# Process-wide singleton
# ==============================================================================
# Every router module used to call `DuckDBManager()` directly at import time.
# Since the app imports 14+ router modules, that meant 14+ separate DuckDB
# connections opened against the same file and 14+ redundant runs of the
# ~40-statement initialize_schema() on every process start. duckdb.connect()
# on a file-backed database also takes an exclusive lock per connection in
# some access patterns, so piling up that many connections is pure waste at
# best and a source of "Conflicting lock" startup errors at worst.
#
# get_db_manager() gives every caller the same instance instead. Call sites
# should prefer `from database import get_db_manager` and call it lazily
# (inside a function, or a module-level `_db = get_db_manager()` guarded the
# same way callers already guard their imports with try/except) rather than
# `DuckDBManager()` directly. Tests that need an isolated in-memory database
# should keep instantiating DuckDBManager(":memory:") directly — the
# singleton is only for the shared on-disk process database.
_singleton: Optional["DuckDBManager"] = None


def get_db_manager(db_path: Optional[str] = None) -> "DuckDBManager":
    """Return the process-wide DuckDBManager, creating it on first call."""
    global _singleton
    if _singleton is None:
        if db_path is None:
            import os
            db_path = os.getenv("DUCKDB_PATH", "jakal.duckdb")
        _singleton = DuckDBManager(db_path)
    return _singleton
