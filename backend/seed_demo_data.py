#!/usr/bin/env python3
"""
backend/seed_demo_data.py
==========================
Populate a fresh JAKAL database with realistic demo/showcase data so the
platform is immediately explorable — no engagement has to be run first to
see what a populated instance looks like.

Usage:
    cd backend
    python3 seed_demo_data.py                 # seeds ./jakal.duckdb
    python3 seed_demo_data.py --db demo.duckdb # seeds a specific file
    python3 seed_demo_data.py --reset          # wipes an existing sample first

This is idempotent-ish: re-running it will add duplicate rows for
non-unique-keyed tables (findings, attack_mappings, threat_intel, fabric
events) but safely upsert/skip for naturally-keyed tables (scopes are not
natural-keyed either, so re-running does add a second demo scope — use
--reset for a truly clean seed).

Nothing here touches secrets: the demo scope, insurance policy, and
operators are fictional placeholder data, not real credentials.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import DuckDBManager  # noqa: E402


def seed(db: DuckDBManager) -> None:
    now = datetime.now(timezone.utc)

    print("→ Operators")
    db.upsert_operator({"operator_id": "demo-admin", "email": "admin@example-msp.test",
                         "display_name": "Demo Admin", "role": "admin"})
    db.upsert_operator({"operator_id": "demo-lead", "email": "lead@example-msp.test",
                         "display_name": "Demo Team Lead", "role": "lead"})
    db.upsert_operator({"operator_id": "demo-operator", "email": "operator@example-msp.test",
                         "display_name": "Demo Operator", "role": "operator"})

    print("→ Scope + insurance (required for the authorization gate to pass)")
    scope_id = db.add_scope(
        client_name="ACME Demo Corp",
        scope_definition="10.10.0.0/16, demo.acme-corp.example, wifi-hq-office",
        start_date=now - timedelta(days=1),
        end_date=now + timedelta(days=90),
        roe_document_path="docs/demo-roe.pdf",
    )
    db.add_insurance_policy(
        policy_number="DEMO-POL-0001", provider="Lloyd's of London (demo)",
        coverage_amount=2_000_000, expiry=now + timedelta(days=365),
    )

    print("→ Pentest run")
    pentest_id = db.insert_pentest({
        "target": "demo.acme-corp.example", "scan_type": "comprehensive",
        "status": "completed",
    })

    print("→ Findings")
    findings = [
        {"pentest_id": pentest_id, "severity": "CRITICAL", "title": "Unauthenticated RCE on legacy admin panel",
         "description": "Public-facing /admin-legacy endpoint accepts unauthenticated file upload leading to RCE.",
         "attack_technique": "T1190", "remediation": "Decommission legacy panel or place behind VPN + auth."},
        {"pentest_id": pentest_id, "severity": "HIGH", "title": "WEP-encrypted guest Wi-Fi network",
         "description": "SSID 'ACME-Guest-Old' still broadcasts using WEP, crackable in minutes.",
         "attack_technique": "T1110.002", "remediation": "Decommission WEP network; migrate to WPA3-Enterprise."},
        {"pentest_id": pentest_id, "severity": "MEDIUM", "title": "SMB anonymous share enumeration",
         "description": "File server allows anonymous listing of 4 shares including 'IT-Backups'.",
         "attack_technique": "T1135", "remediation": "Disable anonymous/null-session SMB access."},
        {"pentest_id": pentest_id, "severity": "MEDIUM", "title": "Missing HSTS + CSP on customer portal",
         "description": "customer.acme-corp.example serves no Strict-Transport-Security or Content-Security-Policy header.",
         "attack_technique": "T1190", "remediation": "Add security headers at the reverse proxy layer."},
        {"pentest_id": pentest_id, "severity": "LOW", "title": "SNMP public community string readable",
         "description": "Core switch responds to SNMPv2c 'public' with full sysDescr disclosure.",
         "attack_technique": "T1602.001", "remediation": "Disable SNMPv1/v2c or restrict community strings + ACL."},
    ]
    finding_ids = []
    for f in findings:
        row = db.conn.execute(
            "INSERT INTO findings (pentest_id, severity, title, description, attack_technique, remediation) "
            "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (f["pentest_id"], f["severity"], f["title"], f["description"], f["attack_technique"], f["remediation"]),
        ).fetchone()
        db.conn.commit()
        finding_ids.append(row[0])

    print("→ MITRE ATT&CK mappings")
    mapping_specs = [
        ("Initial Access", "T1190", "Exploit Public-Facing Application", None),
        ("Credential Access", "T1110", "Brute Force", "T1110.002"),
        ("Discovery", "T1135", "Network Share Discovery", None),
        ("Discovery", "T1669", "Wi-Fi Networks", None),
        ("Credential Access", "T1557", "Adversary-in-the-Middle", "T1557.004"),
        ("Discovery", "T1602", "Data from Configuration Repository", "T1602.001"),
    ]
    for i, (tactic, tid, tname, sub) in enumerate(mapping_specs):
        db.insert_attack_mapping({
            "pentest_id": pentest_id,
            "finding_id": finding_ids[i % len(finding_ids)],
            "tactic": tactic, "technique_id": tid, "technique_name": tname,
            "sub_technique_id": sub, "confidence": 0.9,
        })

    print("→ Vulnerability DB entries")
    db.upsert_vuln({"vuln_id": "CVE-2024-3400", "title": "Palo Alto GlobalProtect command injection",
                     "description": "Demo CVE entry for showcase — arbitrary file creation leading to RCE.",
                     "severity": "CRITICAL", "cvss_score": 10.0, "mitre_technique": "T1190",
                     "patch_available": True, "source": "nvd"})
    db.upsert_vuln({"vuln_id": "JAKAL-CUSTOM-0001", "title": "WEP wireless network in production",
                     "description": "Custom finding — legacy WEP SSID broadcasting on the guest VLAN.",
                     "severity": "HIGH", "cvss_score": 7.5, "mitre_technique": "T1110.002",
                     "patch_available": False, "source": "custom"})

    print("→ Threat intel")
    db.ingest_threat_intel({"feed_source": "CISA_KEV", "intel_type": "TTP", "indicator": "T1190",
                             "indicator_type": "technique", "confidence": 90, "severity": "HIGH",
                             "tags": ["kev", "exploited-in-the-wild"]})
    db.ingest_threat_intel({"feed_source": "manual", "intel_type": "IOC", "indicator": "185.220.101.0/24",
                             "indicator_type": "ip", "confidence": 60, "severity": "MEDIUM",
                             "tags": ["tor-exit-range"]})

    print("→ Network map")
    db.upsert_network_host({"pentest_id": pentest_id, "ip_address": "10.10.4.12", "hostname": "fs01.acme.internal",
                             "open_ports": [{"port": 445, "proto": "tcp", "service": "smb"}],
                             "tags": ["file-server"], "risk_score": 6.5})
    db.upsert_network_host({"pentest_id": pentest_id, "ip_address": "10.10.4.20", "hostname": "core-switch.acme.internal",
                             "open_ports": [{"port": 161, "proto": "udp", "service": "snmp"}],
                             "tags": ["network-device"], "risk_score": 3.0})

    print("→ Unified Security Fabric (seeded automatically by UnifiedSecurityFabric.seed_defaults(), triggering here)")
    from security_agents.unified_fabric import UnifiedSecurityFabric
    fabric = UnifiedSecurityFabric(db=db)
    fabric.set_maturity("mdr", "Advanced", "demo-admin")
    fabric.set_maturity("zero_trust", "Advanced", "demo-admin")
    fabric.record_posture_snapshot("demo-admin")

    print("→ RFP response (sales/showcase boilerplate)")
    db.insert_rfp_response({
        "client_name": "ACME Demo Corp",
        "methodology": "PTES + CPENT-aligned 8-phase engagement: recon, enumeration, wireless, "
                        "web application, vulnerability analysis, post-exploitation assessment, "
                        "encryption analysis, reporting — every action authorization-gated and "
                        "ML-DSA-65 (PQC) audit-signed.",
        "tools_list": ["nmap", "nuclei", "aircrack-ng suite", "sqlmap", "testssl.sh", "JAKAL AIP engine"],
        "timeline": "10 business days: 2 recon/enum, 2 wireless, 3 web/vuln, 1 post-exploit assessment, 2 reporting",
        "pricing": "Contact for scoped quote — priced per asset count + wireless site count",
        "insurance_statement": "Covered under Lloyd's of London Technology E&O + Cyber, $2M aggregate (demo).",
    })

    print("→ Human Approval Gate — one pending demo request")
    from security_agents.exploit_agent import ExploitAgent
    gate = ExploitAgent(db_manager=db)
    gate.stage_payloads(
        attack_mappings=[{"technique_id": "T1110", "service": "wifi-wps", "phase": "wireless"}],
        target="wifi-hq-office", operator_id="demo-operator",
    )

    print("→ Compliance checkpoint (hash-chained authorization trail)")
    db.insert_compliance_checkpoint({
        "action_type": "aip_payload_generation", "operator_id": "demo-operator",
        "target": "demo.acme-corp.example", "authorization_result": "granted",
        "scope_status": "in_scope", "insurance_status": "active", "allowed_to_proceed": True,
    })

    print(f"\n✅ Seed complete. pentest_id={pentest_id}, scope_id={scope_id}")
    print("   Table row counts:")
    for table, count in sorted(db.table_stats().items()):
        print(f"     {table:28s} {count}")


def main():
    parser = argparse.ArgumentParser(description="Seed JAKAL with demo/showcase data.")
    parser.add_argument("--db", default="jakal.duckdb", help="DuckDB file to seed (default: ./jakal.duckdb)")
    parser.add_argument("--reset", action="store_true", help="Delete the db file first for a clean seed")
    args = parser.parse_args()

    if args.reset and os.path.exists(args.db):
        os.remove(args.db)
        print(f"Removed existing {args.db}")

    db = DuckDBManager(db_path=args.db)
    seed(db)
    db.close()


if __name__ == "__main__":
    main()
