"""
capabilities_seed.py — JAKAL Security Capabilities data layer + seed.

Creates the blueprint tables backing the seven capability domains and seeds
realistic, prepopulated operational data (managed devices, EDR alerts, CVEs,
credential leaks, SOAR playbooks, command/script repo, RBAC, YARA rules,
remote sessions, patch jobs, human-risk metrics, guardrail rules).

Everything is idempotent: tables use CREATE TABLE IF NOT EXISTS and each table
is seeded only when empty. Devices are seeded into the existing `network_map`
table so the Fleet dashboard populates with no frontend change.

Read helpers (get_* / inventory) power /api/capabilities/data/* endpoints and
the module UIs.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

logger = logging.getLogger("capabilities_seed")


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


# ── DDL for the seven-domain tables ───────────────────────────────────────
_DDL = [
    """CREATE TABLE IF NOT EXISTS cap_script_execution_logs (
        execution_id VARCHAR PRIMARY KEY, device_id VARCHAR, shell VARCHAR,
        script_title VARCHAR, script_hash VARCHAR, exit_code INTEGER,
        stdout VARCHAR, stderr VARCHAR, executed_at TIMESTAMPTZ DEFAULT now(),
        executor VARCHAR )""",
    """CREATE TABLE IF NOT EXISTS cap_security_alerts (
        alert_id VARCHAR PRIMARY KEY, source_system VARCHAR, mitre_tactics VARCHAR,
        mitre_technique VARCHAR, severity VARCHAR, host VARCHAR, description VARCHAR,
        raw_payload VARCHAR, resolved BOOLEAN DEFAULT false, created_at TIMESTAMPTZ DEFAULT now() )""",
    """CREATE TABLE IF NOT EXISTS cap_nvd_vulnerabilities (
        cve_id VARCHAR PRIMARY KEY, cvss_score DECIMAL, severity VARCHAR,
        affected_asset VARCHAR, package VARCHAR, fixed_version VARCHAR,
        patch_status VARCHAR, description VARCHAR, published DATE )""",
    """CREATE TABLE IF NOT EXISTS cap_credential_leaks (
        leak_id VARCHAR PRIMARY KEY, exposed_email VARCHAR, hashed_password VARCHAR,
        source_forum VARCHAR, breach VARCHAR, severity VARCHAR, discovered_date DATE,
        reset_status VARCHAR DEFAULT 'open' )""",
    """CREATE TABLE IF NOT EXISTS cap_soar_playbooks (
        playbook_id VARCHAR PRIMARY KEY, name VARCHAR, trigger_event VARCHAR,
        steps VARCHAR, enabled BOOLEAN DEFAULT true, requires_approval BOOLEAN DEFAULT true,
        last_run TIMESTAMPTZ, run_count INTEGER DEFAULT 0 )""",
    """CREATE TABLE IF NOT EXISTS cap_command_repo (
        cmd_id VARCHAR PRIMARY KEY, title VARCHAR, category VARCHAR, platform VARCHAR,
        syntax_template VARCHAR, tags VARCHAR, risk_level VARCHAR )""",
    """CREATE TABLE IF NOT EXISTS cap_rbac_roles (
        role_id VARCHAR PRIMARY KEY, name VARCHAR, description VARCHAR, permissions VARCHAR )""",
    """CREATE TABLE IF NOT EXISTS cap_rbac_users (
        user_id VARCHAR PRIMARY KEY, username VARCHAR, role VARCHAR, mfa_enabled BOOLEAN,
        last_login TIMESTAMPTZ )""",
    """CREATE TABLE IF NOT EXISTS cap_human_risk_metrics (
        user_id VARCHAR PRIMARY KEY, display_name VARCHAR, department VARCHAR,
        phish_click_count INTEGER, training_assigned INTEGER, training_complete INTEGER,
        risk_score INTEGER )""",
    """CREATE TABLE IF NOT EXISTS cap_remote_sessions (
        session_id VARCHAR PRIMARY KEY, device_id VARCHAR, operator VARCHAR, shell VARCHAR,
        opened_at TIMESTAMPTZ DEFAULT now(), recording BOOLEAN DEFAULT true, status VARCHAR DEFAULT 'active' )""",
    """CREATE TABLE IF NOT EXISTS cap_patch_jobs (
        job_id VARCHAR PRIMARY KEY, device_id VARCHAR, kb_ids VARCHAR, reboot_policy VARCHAR,
        state VARCHAR, scheduled_for TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT now() )""",
    """CREATE TABLE IF NOT EXISTS cap_yara_rules (
        rule_id VARCHAR PRIMARY KEY, name VARCHAR, category VARCHAR, severity VARCHAR,
        description VARCHAR, author VARCHAR )""",
    """CREATE TABLE IF NOT EXISTS cap_guardrail_rules (
        rule_id VARCHAR PRIMARY KEY, regex_pattern VARCHAR, severity VARCHAR,
        action_on_match VARCHAR, description VARCHAR )""",
    """CREATE TABLE IF NOT EXISTS cap_asset_relationships (
        rel_id VARCHAR PRIMARY KEY, source_asset VARCHAR, source_type VARCHAR,
        relationship VARCHAR, target_asset VARCHAR, target_type VARCHAR,
        criticality VARCHAR, notes VARCHAR )""",
    """CREATE TABLE IF NOT EXISTS cap_credential_rotation (
        cred_id VARCHAR PRIMARY KEY, label VARCHAR, system VARCHAR, owner VARCHAR,
        last_rotated DATE, rotation_days INTEGER, next_due DATE, status VARCHAR,
        strength VARCHAR )""",
    """CREATE TABLE IF NOT EXISTS cap_remediation_tickets (
        ticket_id VARCHAR PRIMARY KEY, title VARCHAR, source VARCHAR, source_ref VARCHAR,
        severity VARCHAR, asset VARCHAR, assignee VARCHAR, status VARCHAR,
        sla_due TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT now() )""",
    """CREATE TABLE IF NOT EXISTS cap_drift_events (
        drift_id VARCHAR PRIMARY KEY, asset VARCHAR, control VARCHAR, framework VARCHAR,
        expected VARCHAR, observed VARCHAR, severity VARCHAR, detected_at TIMESTAMPTZ DEFAULT now(),
        acknowledged BOOLEAN DEFAULT false )""",
    """CREATE TABLE IF NOT EXISTS cap_phish_failures (
        fail_id VARCHAR PRIMARY KEY, user_id VARCHAR, display_name VARCHAR, department VARCHAR,
        campaign VARCHAR, failed_at TIMESTAMPTZ, action_taken VARCHAR, enrolled_course VARCHAR )""",
    """CREATE TABLE IF NOT EXISTS cap_settings (
        key VARCHAR PRIMARY KEY, value VARCHAR, updated_at TIMESTAMPTZ DEFAULT now() )""",
]

# Tables that carry seed data, with their PK column for the emptiness check.
_SEED_TABLES = [
    "cap_security_alerts", "cap_nvd_vulnerabilities", "cap_credential_leaks",
    "cap_soar_playbooks", "cap_command_repo", "cap_rbac_roles", "cap_rbac_users",
    "cap_human_risk_metrics", "cap_yara_rules", "cap_guardrail_rules",
    "cap_script_execution_logs", "cap_patch_jobs", "cap_remote_sessions",
]


def _count(db, table) -> int:
    try:
        r = db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(r[0]) if r else 0
    except Exception:
        return 0


def _ins(db, sql, rows):
    for r in rows:
        db.conn.execute(sql, r)


# ── Seed data ─────────────────────────────────────────────────────────────
def _seed_network_map(db):
    """Managed devices for the Fleet dashboard (existing network_map table)."""
    if _count(db, "network_map") > 0:
        return 0
    now = _now()
    devices = [
        # ip, hostname, mac, os, open_ports, tags, risk, last_seen_min_ago, notes
        ("10.20.0.11", "WIN-OPS-01", "00:1A:2B:3C:4D:11", "Windows 11 Pro 23H2",
         [{"port": 3389, "proto": "tcp", "service": "rdp"}, {"port": 445, "proto": "tcp", "service": "smb"}],
         ["workstation", "windows", "finance"], 0.22, 1, "RMM agent 1.4.2 · healthy"),
        ("10.20.0.24", "LNX-EDGE-04", "00:1A:2B:3C:4D:24", "Ubuntu 22.04 LTS",
         [{"port": 22, "proto": "tcp", "service": "ssh"}, {"port": 443, "proto": "tcp", "service": "https"}],
         ["server", "linux", "edge", "dmz"], 0.61, 2, "3 patches pending · CVE-2024-3094 candidate"),
        ("10.20.0.31", "MAC-DEV-11", "00:1A:2B:3C:4D:31", "macOS 14.5 Sonoma",
         [{"port": 22, "proto": "tcp", "service": "ssh"}],
         ["laptop", "darwin", "engineering"], 0.18, 1, "FileVault on · healthy"),
        ("10.20.0.40", "WIN-DC-01", "00:1A:2B:3C:4D:40", "Windows Server 2022",
         [{"port": 389, "proto": "tcp", "service": "ldap"}, {"port": 88, "proto": "tcp", "service": "kerberos"}],
         ["server", "windows", "domain-controller", "tier0"], 0.35, 1, "Tier-0 asset · PAM enforced"),
        ("10.20.0.55", "LNX-DB-02", "00:1A:2B:3C:4D:55", "Debian 12",
         [{"port": 5432, "proto": "tcp", "service": "postgres"}],
         ["server", "linux", "database", "pii"], 0.74, 3, "Holds PII · encrypted at rest"),
        ("10.20.0.66", "WIN-HR-07", "00:1A:2B:3C:4D:66", "Windows 10 22H2",
         [{"port": 445, "proto": "tcp", "service": "smb"}],
         ["workstation", "windows", "hr"], 0.48, 5, "EOL OS build · upgrade scheduled"),
        ("10.20.0.72", "IOT-CAM-03", "00:1A:2B:3C:4D:72", "Embedded Linux (RTOS)",
         [{"port": 554, "proto": "tcp", "service": "rtsp"}],
         ["iot", "camera", "isolated-vlan"], 0.66, 8, "Default creds candidate · VLAN-quarantined"),
        ("10.20.0.88", "LNX-K8S-01", "00:1A:2B:3C:4D:88", "Talos Linux (k8s node)",
         [{"port": 6443, "proto": "tcp", "service": "kube-api"}],
         ["server", "linux", "kubernetes", "prod"], 0.29, 1, "Node healthy · admission control on"),
    ]
    sql = ("INSERT INTO network_map (ip_address, hostname, mac_address, os_fingerprint, "
           "open_ports, tags, risk_score, last_seen, discovered_at, notes) "
           "VALUES (?,?,?,?,?,?,?,?,?,?)")
    for d in devices:
        ip, host, mac, os_, ports, tags, risk, mins, notes = d
        ls = now - timedelta(minutes=mins)
        db.conn.execute(sql, (ip, host, mac, os_, json.dumps(ports), json.dumps(tags),
                              risk, ls, now - timedelta(days=7), notes))
    return len(devices)


def _seed_alerts(db):
    now = _now()
    rows = [
        ("alert-8801", "EDR-Wazuh", "Credential Access", "T1003", "HIGH", "WIN-DC-01",
         "LSASS memory access by non-system process", '{"pid":4821,"proc":"rundll32.exe"}', False, 6),
        ("alert-8802", "Sysmon", "Persistence", "T1547", "MEDIUM", "WIN-OPS-01",
         "New Run key registry persistence", '{"key":"HKCU\\\\...\\\\Run"}', False, 42),
        ("alert-8803", "Suricata", "Command and Control", "T1071", "CRITICAL", "LNX-EDGE-04",
         "Beaconing to known C2 (JA3 match)", '{"dst":"185.220.101.4","ja3":"a0e9f5..."}', False, 3),
        ("alert-8804", "EDR-Elastic", "Defense Evasion", "T1562", "HIGH", "WIN-HR-07",
         "Security service tampering (AV disabled)", '{"svc":"WinDefend"}', False, 18),
        ("alert-8805", "auth.log", "Discovery", "T1046", "LOW", "LNX-DB-02",
         "Internal port sweep detected", '{"scanner":"10.20.0.24"}', True, 120),
        ("alert-8806", "M365-Defender", "Initial Access", "T1566", "MEDIUM", "WIN-OPS-01",
         "Phishing link click (safe-links detonated)", '{"url":"hxxp://payroll-login[.]co"}', True, 240),
    ]
    _ins(db, "INSERT INTO cap_security_alerts (alert_id,source_system,mitre_tactics,mitre_technique,severity,host,description,raw_payload,resolved,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
         [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], now - timedelta(minutes=r[9])) for r in rows])
    return len(rows)


def _seed_vulns(db):
    rows = [
        ("CVE-2024-3094", 10.0, "CRITICAL", "LNX-EDGE-04", "xz-utils", "5.6.2", "PENDING",
         "Malicious backdoor in liblzma (xz) affecting sshd", "2024-03-29"),
        ("CVE-2024-21413", 9.8, "CRITICAL", "WIN-OPS-01", "Microsoft Outlook", "KB5034765", "PENDING",
         "Outlook RCE via Moniker link (#MonikerLink)", "2024-02-13"),
        ("CVE-2023-4863", 8.8, "HIGH", "MAC-DEV-11", "libwebp", "1.3.2", "APPLIED",
         "Heap buffer overflow in WebP (0-day, widely exploited)", "2023-09-12"),
        ("CVE-2024-6387", 8.1, "HIGH", "LNX-DB-02", "openssh-server", "9.8p1", "PENDING",
         "regreSSHion — unauthenticated RCE in OpenSSH sshd", "2024-07-01"),
        ("CVE-2022-30190", 7.8, "HIGH", "WIN-HR-07", "MSDT", "KB5014699", "ACCEPTED_RISK",
         "Follina — MSDT remote code execution", "2022-05-30"),
        ("CVE-2021-44228", 10.0, "CRITICAL", "LNX-K8S-01", "log4j-core", "2.17.1", "APPLIED",
         "Log4Shell — JNDI RCE in Apache Log4j", "2021-12-10"),
        ("CVE-2024-23897", 9.8, "CRITICAL", "LNX-K8S-01", "jenkins", "2.442", "PENDING",
         "Jenkins CLI arbitrary file read -> RCE", "2024-01-24"),
    ]
    _ins(db, "INSERT INTO cap_nvd_vulnerabilities (cve_id,cvss_score,severity,affected_asset,package,fixed_version,patch_status,description,published) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _seed_leaks(db):
    rows = [
        ("leak-7841", "ceo@client.com", "$2b$…(bcrypt)", "BreachForums dump #7841", "Collection#1",
         "HIGH", "2026-08-30", "open"),
        ("leak-7842", "helpdesk@client.com", "5f4dcc3b…(md5)", "paste.ee/abc123", "LinkedIn-2021",
         "CRITICAL", "2026-08-28", "reset_forced"),
        ("leak-7843", "j.smith@client.com", "(plaintext)", "Telegram combolist", "Naz.API",
         "CRITICAL", "2026-09-01", "open"),
        ("leak-7844", "vendor-api@client.com", "AKIA…(aws key)", "GitHub public gist", "Exposed-Secret",
         "CRITICAL", "2026-09-03", "revoked"),
        ("leak-7845", "marketing@client.com", "$2y$…(bcrypt)", "RaidForums archive", "Canva-2019",
         "MEDIUM", "2026-07-19", "monitored"),
    ]
    _ins(db, "INSERT INTO cap_credential_leaks (leak_id,exposed_email,hashed_password,source_forum,breach,severity,discovered_date,reset_status) VALUES (?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _seed_playbooks(db):
    def steps(*s):
        return json.dumps(list(s))
    rows = [
        ("pb-ransomware", "Ransomware Containment", "alert.severity>=HIGH && tactic=Impact",
         steps("isolate_host", "kill_process_tree", "snapshot_disk", "notify_soc", "open_ticket"), True, True, 3),
        ("pb-cred-leak", "Credential Exposure Response", "darkweb.new_finding",
         steps("verify_leak", "force_password_reset", "revoke_sessions", "notify_user"), True, True, 11),
        ("pb-phishing", "Phishing Auto-Triage", "email.verdict=malicious",
         steps("quarantine_email", "extract_iocs", "block_ioc", "sweep_mailboxes"), True, False, 47),
        ("pb-vuln-crit", "Critical CVE Emergency Patch", "vuln.cvss>=9.0",
         steps("scan_cve", "stage_patch", "approval_gate", "apply_updates", "verify"), True, True, 5),
        ("pb-c2-beacon", "C2 Beacon Neutralization", "ids.c2_match",
         steps("block_ioc", "isolate_host", "fetch_pcap", "hunt_lateral"), True, True, 2),
        ("pb-newhost", "New Endpoint Onboarding", "fleet.device_registered",
         steps("deploy_agent", "baseline_scan", "apply_policy", "enroll_edr"), True, False, 128),
    ]
    _ins(db, "INSERT INTO cap_soar_playbooks (playbook_id,name,trigger_event,steps,enabled,requires_approval,run_count) VALUES (?,?,?,?,?,?,?)", rows)
    return len(rows)


def _seed_commands(db):
    rows = [
        ("cmd-001", "List established connections", "Recon", "windows", "netstat -ano | findstr ESTABLISHED", '["network","triage"]', "low"),
        ("cmd-002", "Enumerate running processes", "Recon", "windows", "Get-Process | Sort-Object CPU -Descending", '["process","triage"]', "low"),
        ("cmd-003", "Dump failed logons", "IR", "windows", "Get-WinEvent -FilterHashtable @{LogName='Security';Id=4625} -MaxEvents 50", '["auth","edr"]', "low"),
        ("cmd-004", "Kill process by PID", "Response", "windows", "Stop-Process -Id {pid} -Force", '["response","containment"]', "high"),
        ("cmd-005", "Isolate NIC (Windows)", "Response", "windows", "Disable-NetAdapter -Name '*' -Confirm:$false", '["containment"]', "critical"),
        ("cmd-006", "List listening sockets", "Recon", "linux", "ss -tulpn", '["network","triage"]', "low"),
        ("cmd-007", "Recent auth failures", "IR", "linux", "grep 'Failed password' /var/log/auth.log | tail -50", '["auth"]', "low"),
        ("cmd-008", "Kill process tree", "Response", "linux", "pkill -TERM -P {ppid}", '["response"]', "high"),
        ("cmd-009", "Firewall drop IP", "Response", "linux", "iptables -A INPUT -s {ip} -j DROP", '["containment","firewall"]', "high"),
        ("cmd-010", "Nmap service scan", "Recon", "any", "nmap -sV -sC -oN scan.txt {target}", '["scan","recon"]', "medium"),
        ("cmd-011", "YARA scan directory", "Detect", "any", "yara -r {rules} {path}", '["yara","detect"]', "medium"),
        ("cmd-012", "Capture PCAP (60s)", "Forensics", "linux", "timeout 60 tcpdump -i any -w cap.pcap", '["forensics","network"]', "medium"),
    ]
    _ins(db, "INSERT INTO cap_command_repo (cmd_id,title,category,platform,syntax_template,tags,risk_level) VALUES (?,?,?,?,?,?,?)", rows)
    return len(rows)


def _seed_rbac(db):
    def perms(*p):
        return json.dumps(list(p))
    roles = [
        ("role-super", "Super Admin", "Full control of the ecosystem and all tenants",
         perms("*")),
        ("role-soc", "SOC Analyst", "Detection, triage and response (approval-gated for HIGH)",
         perms("detect:scan", "detect:respond", "fleet:read", "soar:execute", "response:manage")),
        ("role-rmm", "RMM Technician", "Fleet monitoring, scripts and patching",
         perms("fleet:read", "fleet:execute", "patch:read", "patch:apply", "remote:shell")),
        ("role-compliance", "Compliance Officer", "Read-only posture, audit and reporting",
         perms("patch:read", "aisafety:read", "fleet:read", "audit:read")),
        ("role-client", "Client Viewer", "Tenant-scoped read-only dashboards",
         perms("fleet:read", "audit:read")),
    ]
    _ins(db, "INSERT INTO cap_rbac_roles (role_id,name,description,permissions) VALUES (?,?,?,?)", roles)
    now = _now()
    users = [
        ("u-alpha", "operator.alpha", "Super Admin", True, now - timedelta(minutes=5)),
        ("u-soc1", "sara.chen", "SOC Analyst", True, now - timedelta(hours=1)),
        ("u-rmm1", "mike.ortiz", "RMM Technician", True, now - timedelta(hours=3)),
        ("u-comp1", "dana.li", "Compliance Officer", True, now - timedelta(days=1)),
        ("u-cli1", "client.viewer", "Client Viewer", False, now - timedelta(days=2)),
    ]
    _ins(db, "INSERT INTO cap_rbac_users (user_id,username,role,mfa_enabled,last_login) VALUES (?,?,?,?,?)", users)
    return len(roles) + len(users)


def _seed_human_risk(db):
    rows = [
        ("u-soc1", "Sara Chen", "Security", 0, 6, 6, 8),
        ("u-rmm1", "Mike Ortiz", "IT Ops", 1, 6, 5, 24),
        ("hr-201", "Bob Reyes", "Finance", 3, 8, 4, 71),
        ("hr-202", "Amy Wong", "HR", 2, 8, 6, 42),
        ("hr-203", "Tom Blake", "Sales", 4, 8, 2, 88),
        ("hr-204", "Priya Nair", "Engineering", 0, 6, 6, 11),
    ]
    _ins(db, "INSERT INTO cap_human_risk_metrics (user_id,display_name,department,phish_click_count,training_assigned,training_complete,risk_score) VALUES (?,?,?,?,?,?,?)", rows)
    return len(rows)


def _seed_yara(db):
    rows = [
        ("yara-001", "Ransomware_Generic_Note", "ransomware", "HIGH", "Detects common ransom-note artifacts", "JAKAL"),
        ("yara-002", "Webshell_PHP_Eval", "webshell", "HIGH", "PHP eval/base64_decode webshell pattern", "JAKAL"),
        ("yara-003", "Cobalt_Strike_Beacon", "c2", "CRITICAL", "CS beacon config + sleep mask heuristics", "JAKAL"),
        ("yara-004", "LOLBin_Rundll32_Abuse", "lolbin", "MEDIUM", "Suspicious rundll32 command lines", "JAKAL"),
        ("yara-005", "Mimikatz_Signatures", "credential-theft", "CRITICAL", "Mimikatz strings + sekurlsa", "JAKAL"),
    ]
    _ins(db, "INSERT INTO cap_yara_rules (rule_id,name,category,severity,description,author) VALUES (?,?,?,?,?,?)", rows)
    return len(rows)


def _seed_guardrails(db):
    rows = [
        ("gr-001", r"rm\s+-rf\s+/", "CRITICAL", "BLOCK", "Destructive recursive delete"),
        ("gr-002", r"DROP\s+DATABASE", "CRITICAL", "BLOCK", "Database destruction"),
        ("gr-003", r"iptables\s+-F", "HIGH", "BLOCK", "Firewall flush"),
        ("gr-004", r"ignore\s+previous\s+instructions", "HIGH", "FLAG", "Prompt injection"),
        ("gr-005", r"(AKIA[0-9A-Z]{16})", "HIGH", "REDACT", "AWS access key in payload"),
        ("gr-006", r":\(\)\{\s*:\|:&\s*\};:", "CRITICAL", "BLOCK", "Fork-bomb"),
    ]
    _ins(db, "INSERT INTO cap_guardrail_rules (rule_id,regex_pattern,severity,action_on_match,description) VALUES (?,?,?,?,?)", rows)
    return len(rows)


def _seed_script_logs(db):
    now = _now()
    rows = [
        ("exec-9001", "WIN-OPS-01", "powershell", "Enumerate running processes", "a1b2c3d4", 0,
         "142 processes enumerated", "", now - timedelta(minutes=12), "mike.ortiz"),
        ("exec-9002", "LNX-EDGE-04", "bash", "List listening sockets", "e5f6a7b8", 0,
         "tcp 0.0.0.0:22, tcp 0.0.0.0:443", "", now - timedelta(minutes=40), "mike.ortiz"),
        ("exec-9003", "WIN-DC-01", "powershell", "Dump failed logons", "c9d0e1f2", 0,
         "17 failed logon events (4625)", "", now - timedelta(hours=2), "sara.chen"),
    ]
    _ins(db, "INSERT INTO cap_script_execution_logs (execution_id,device_id,shell,script_title,script_hash,exit_code,stdout,stderr,executed_at,executor) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _seed_patch_jobs(db):
    now = _now()
    rows = [
        ("job-501", "WIN-OPS-01", json.dumps(["KB5034765"]), "if_required", "scheduled", now + timedelta(hours=6)),
        ("job-502", "LNX-EDGE-04", json.dumps(["xz-5.6.2", "openssh-9.8p1"]), "forced", "pending_approval", now + timedelta(hours=2)),
        ("job-503", "MAC-DEV-11", json.dumps(["libwebp-1.3.2"]), "none", "applied", now - timedelta(days=1)),
    ]
    _ins(db, "INSERT INTO cap_patch_jobs (job_id,device_id,kb_ids,reboot_policy,state,scheduled_for) VALUES (?,?,?,?,?,?)", rows)
    return len(rows)


def _seed_sessions(db):
    now = _now()
    rows = [
        ("sess-3001", "WIN-OPS-01", "mike.ortiz", "powershell", now - timedelta(minutes=4), True, "active"),
        ("sess-3002", "LNX-DB-02", "sara.chen", "bash", now - timedelta(minutes=20), True, "closed"),
    ]
    _ins(db, "INSERT INTO cap_remote_sessions (session_id,device_id,operator,shell,opened_at,recording,status) VALUES (?,?,?,?,?,?,?)", rows)
    return len(rows)



def _seed_relationships(db):
    rows = [
        ("rel-001", "WIN-DC-01", "server", "authenticates", "WIN-OPS-01", "workstation", "CRITICAL", "Primary domain controller"),
        ("rel-002", "WIN-DC-01", "server", "authenticates", "WIN-HR-07", "workstation", "CRITICAL", "Domain auth path"),
        ("rel-003", "LNX-DB-02", "database", "stores-pii-for", "Payroll App", "application", "CRITICAL", "PII at rest (AES-256)"),
        ("rel-004", "LNX-EDGE-04", "server", "fronts", "LNX-DB-02", "database", "HIGH", "Reverse proxy / TLS termination"),
        ("rel-005", "LNX-K8S-01", "cluster", "hosts", "Payroll App", "application", "HIGH", "Prod workload"),
        ("rel-006", "IOT-CAM-03", "iot", "isolated-in", "VLAN-900", "network", "MEDIUM", "Quarantine VLAN"),
        ("rel-007", "vendor-api@client.com", "credential", "grants-access-to", "LNX-K8S-01", "cluster", "CRITICAL", "Rotate on exposure"),
        ("rel-008", "MAC-DEV-11", "laptop", "connects-via", "SASE Tunnel", "network", "MEDIUM", "Zero-trust access"),
    ]
    _ins(db, "INSERT INTO cap_asset_relationships (rel_id,source_asset,source_type,relationship,target_asset,target_type,criticality,notes) VALUES (?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _seed_rotation(db):
    from datetime import date
    rows = [
        ("cr-001", "Domain Admin", "WIN-DC-01", "operator.alpha", "2026-08-10", 90, "2026-11-08", "ok", "strong"),
        ("cr-002", "Postgres root", "LNX-DB-02", "mike.ortiz", "2026-05-02", 90, "2026-07-31", "overdue", "strong"),
        ("cr-003", "Vendor API key", "LNX-K8S-01", "sara.chen", "2026-09-03", 30, "2026-10-03", "compromised", "rotate-now"),
        ("cr-004", "Backup service acct", "Backup Vault", "mike.ortiz", "2026-07-20", 180, "2027-01-16", "ok", "strong"),
        ("cr-005", "Firewall admin", "HQ-Firewall", "operator.alpha", "2026-06-15", 90, "2026-09-13", "due-soon", "medium"),
        ("cr-006", "SMTP relay", "Mail Gateway", "dana.li", "2026-03-01", 90, "2026-05-30", "overdue", "weak"),
    ]
    _ins(db, "INSERT INTO cap_credential_rotation (cred_id,label,system,owner,last_rotated,rotation_days,next_due,status,strength) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _seed_tickets(db):
    now = _now()
    rows = [
        ("tkt-1001", "Patch CVE-2024-3094 (xz backdoor) on LNX-EDGE-04", "vulnerability", "CVE-2024-3094",
         "CRITICAL", "LNX-EDGE-04", "mike.ortiz", "open", now + timedelta(hours=8)),
        ("tkt-1002", "Rotate exposed vendor API key", "dark_web", "leak-7844",
         "CRITICAL", "LNX-K8S-01", "sara.chen", "in_progress", now + timedelta(hours=4)),
        ("tkt-1003", "Investigate C2 beacon on LNX-EDGE-04", "edr_alert", "alert-8803",
         "CRITICAL", "LNX-EDGE-04", "sara.chen", "open", now + timedelta(hours=2)),
    ]
    _ins(db, "INSERT INTO cap_remediation_tickets (ticket_id,title,source,source_ref,severity,asset,assignee,status,sla_due) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _seed_drift(db):
    now = _now()
    rows = [
        ("drift-01", "WIN-HR-07", "Disk encryption enabled", "CIS-3.1", "enabled", "disabled", "HIGH", now - timedelta(hours=5), False),
        ("drift-02", "LNX-EDGE-04", "SSH root login disabled", "NIST-AC-6", "no", "yes", "CRITICAL", now - timedelta(hours=2), False),
        ("drift-03", "IOT-CAM-03", "Default credentials changed", "CIS-5.2", "changed", "default", "HIGH", now - timedelta(days=1), True),
        ("drift-04", "WIN-OPS-01", "AV real-time protection", "SOC2-CC6.8", "on", "on", "LOW", now - timedelta(hours=9), True),
    ]
    _ins(db, "INSERT INTO cap_drift_events (drift_id,asset,control,framework,expected,observed,severity,detected_at,acknowledged) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _seed_phish_failures(db):
    now = _now()
    rows = [
        ("pf-01", "hr-203", "Tom Blake", "Sales", "Q3 Invoice Lure", now - timedelta(days=2), "pending", ""),
        ("pf-02", "hr-201", "Bob Reyes", "Finance", "Q3 Invoice Lure", now - timedelta(days=2), "enrolled", "Phishing 101"),
        ("pf-03", "hr-202", "Amy Wong", "HR", "Payroll Update", now - timedelta(days=9), "pending", ""),
        ("pf-04", "hr-203", "Tom Blake", "Sales", "MFA Reset Lure", now - timedelta(days=16), "enrolled", "Credential Safety"),
    ]
    _ins(db, "INSERT INTO cap_phish_failures (fail_id,user_id,display_name,department,campaign,failed_at,action_taken,enrolled_course) VALUES (?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _seed_settings(db):
    rows = [("drift_detection_enabled", "true"), ("sso_saml_enabled", "false"),
            ("sso_oidc_enabled", "false"), ("auto_enroll_on_phish_fail", "true"),
            ("auto_ticket_on_critical", "true")]
    _ins(db, "INSERT INTO cap_settings (key,value) VALUES (?,?)", rows)
    return len(rows)

_SEEDERS = {
    "cap_security_alerts": _seed_alerts,
    "cap_nvd_vulnerabilities": _seed_vulns,
    "cap_credential_leaks": _seed_leaks,
    "cap_soar_playbooks": _seed_playbooks,
    "cap_command_repo": _seed_commands,
    "cap_rbac_roles": _seed_rbac,           # seeds roles + users together
    "cap_human_risk_metrics": _seed_human_risk,
    "cap_yara_rules": _seed_yara,
    "cap_guardrail_rules": _seed_guardrails,
    "cap_script_execution_logs": _seed_script_logs,
    "cap_patch_jobs": _seed_patch_jobs,
    "cap_remote_sessions": _seed_sessions,
    "cap_asset_relationships": _seed_relationships,
    "cap_credential_rotation": _seed_rotation,
    "cap_remediation_tickets": _seed_tickets,
    "cap_drift_events": _seed_drift,
    "cap_phish_failures": _seed_phish_failures,
    "cap_settings": _seed_settings,
}


def ensure_schema_and_seed(db) -> Dict[str, Any]:
    """Create tables + seed once. Safe to call at every startup."""
    created = 0
    for ddl in _DDL:
        try:
            db.conn.execute(ddl); created += 1
        except Exception as e:
            logger.warning("DDL failed: %s", e)
    seeded: Dict[str, int] = {}
    try:
        n = _seed_network_map(db)
        if n:
            seeded["network_map"] = n
    except Exception as e:
        logger.warning("network_map seed failed: %s", e)
    for table, fn in _SEEDERS.items():
        try:
            if _count(db, table) == 0:
                seeded[table] = fn(db)
        except Exception as e:
            logger.warning("seed %s failed: %s", table, e)
    try:
        db.conn.commit()
    except Exception:
        pass
    logger.info("capabilities seed complete: %s", seeded)
    return {"tables_ensured": created, "seeded": seeded}


# ── Read helpers (power /api/capabilities/data/*) ─────────────────────────
def _rows_as_dicts(db, sql, params=()) -> List[Dict[str, Any]]:
    res = db.conn.execute(sql, params)
    cols = [d[0] for d in (res.description or [])]
    return [dict(zip(cols, r)) for r in res.fetchall()]


def get_domain_data(db, domain: str, limit: int = 100) -> Dict[str, Any]:
    q = {
        "fleet_rmm": ("SELECT hostname, ip_address, os_fingerprint, risk_score, tags, last_seen, notes "
                      "FROM network_map ORDER BY risk_score DESC LIMIT ?", "devices"),
        "remote_access": ("SELECT * FROM cap_remote_sessions ORDER BY opened_at DESC LIMIT ?", "sessions"),
        "detect_respond": ("SELECT * FROM cap_security_alerts ORDER BY created_at DESC LIMIT ?", "alerts"),
        "soar_playbooks": ("SELECT * FROM cap_soar_playbooks ORDER BY run_count DESC LIMIT ?", "playbooks"),
        "patch_vulnerability": ("SELECT * FROM cap_nvd_vulnerabilities ORDER BY cvss_score DESC LIMIT ?", "vulnerabilities"),
        "dark_web": ("SELECT * FROM cap_credential_leaks ORDER BY discovered_date DESC LIMIT ?", "leaks"),
        "ai_safety_fabric": ("SELECT * FROM cap_guardrail_rules LIMIT ?", "guardrails"),
        "commands": ("SELECT * FROM cap_command_repo LIMIT ?", "commands"),
        "rbac": ("SELECT * FROM cap_rbac_roles LIMIT ?", "roles"),
        "human_risk": ("SELECT * FROM cap_human_risk_metrics ORDER BY risk_score DESC LIMIT ?", "users"),
        "yara": ("SELECT * FROM cap_yara_rules LIMIT ?", "rules"),
        "scripts": ("SELECT * FROM cap_script_execution_logs ORDER BY executed_at DESC LIMIT ?", "executions"),
        "patch_jobs": ("SELECT * FROM cap_patch_jobs ORDER BY created_at DESC LIMIT ?", "jobs"),
        "relationships": ("SELECT * FROM cap_asset_relationships LIMIT ?", "relationships"),
        "credential_rotation": ("SELECT * FROM cap_credential_rotation ORDER BY next_due LIMIT ?", "credentials"),
        "tickets": ("SELECT * FROM cap_remediation_tickets ORDER BY created_at DESC LIMIT ?", "tickets"),
        "drift": ("SELECT * FROM cap_drift_events ORDER BY detected_at DESC LIMIT ?", "drift_events"),
        "phish_failures": ("SELECT * FROM cap_phish_failures ORDER BY failed_at DESC LIMIT ?", "failures"),
        "settings": ("SELECT * FROM cap_settings LIMIT ?", "settings"),
    }
    if domain not in q:
        return {"error": f"unknown domain '{domain}'", "available": list(q.keys())}
    sql, key = q[domain]
    return {key: _rows_as_dicts(db, sql, (limit,))}


def inventory(db) -> Dict[str, Any]:
    def c(t):
        return _count(db, t)
    return {
        "generated_at": _iso(_now()),
        "assets": {
            "managed_devices": c("network_map"),
            "windows": _scalar(db, "SELECT COUNT(*) FROM network_map WHERE os_fingerprint LIKE 'Windows%'"),
            "linux": _scalar(db, "SELECT COUNT(*) FROM network_map WHERE os_fingerprint LIKE '%Linux%' OR os_fingerprint LIKE 'Ubuntu%' OR os_fingerprint LIKE 'Debian%' OR os_fingerprint LIKE 'Talos%'"),
            "macos": _scalar(db, "SELECT COUNT(*) FROM network_map WHERE os_fingerprint LIKE 'macOS%'"),
            "iot": _scalar(db, "SELECT COUNT(*) FROM network_map WHERE tags LIKE '%iot%'"),
        },
        "domains": {
            "detect_respond": {"open_alerts": _scalar(db, "SELECT COUNT(*) FROM cap_security_alerts WHERE resolved=false"),
                                "critical": _scalar(db, "SELECT COUNT(*) FROM cap_security_alerts WHERE severity='CRITICAL' AND resolved=false")},
            "patch_vulnerability": {"total_cves": c("cap_nvd_vulnerabilities"),
                                     "pending": _scalar(db, "SELECT COUNT(*) FROM cap_nvd_vulnerabilities WHERE patch_status='PENDING'"),
                                     "critical": _scalar(db, "SELECT COUNT(*) FROM cap_nvd_vulnerabilities WHERE severity='CRITICAL'")},
            "dark_web": {"leaks": c("cap_credential_leaks"),
                          "open": _scalar(db, "SELECT COUNT(*) FROM cap_credential_leaks WHERE reset_status='open'")},
            "soar_playbooks": {"playbooks": c("cap_soar_playbooks")},
            "fleet_rmm": {"scripts_in_repo": c("cap_command_repo"), "executions": c("cap_script_execution_logs")},
            "remote_access": {"sessions": c("cap_remote_sessions")},
            "ai_safety_fabric": {"guardrail_rules": c("cap_guardrail_rules"), "yara_rules": c("cap_yara_rules")},
        },
        "governance": {
            "rbac_roles": c("cap_rbac_roles"), "rbac_users": c("cap_rbac_users"),
            "human_risk_tracked": c("cap_human_risk_metrics"),
            "patch_jobs": c("cap_patch_jobs"),
        },
    }


def _scalar(db, sql):
    try:
        r = db.conn.execute(sql).fetchone()
        return int(r[0]) if r else 0
    except Exception:
        return 0
