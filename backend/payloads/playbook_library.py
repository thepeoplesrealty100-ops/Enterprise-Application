"""
backend/payloads/playbook_library.py
Pre-populated cybersecurity playbook library for JAKAL.

Each playbook is a structured response procedure for a specific scenario:
  - Threat Hunt playbooks: proactive threat detection workflows
  - Incident Response playbooks: step-by-step containment / eradication
  - Red Team playbooks: authorized attack simulation procedures
  - Compliance Check playbooks: NIST / ISO / CIS control validation
  - Quantum Security playbooks: PQC migration and crypto assessment

Playbooks include:
  - Ordered steps with description and expected outcome
  - Required tools per step
  - MITRE ATT&CK technique alignment
  - Decision gates (if/then branching conditions)
  - Evidence collection checkpoints
"""

from __future__ import annotations

from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Playbook definitions
# ---------------------------------------------------------------------------

PLAYBOOKS: Dict[str, Dict[str, Any]] = {

    # ================================================================
    # THREAT HUNT PLAYBOOKS
    # ================================================================

    "hunt_lateral_movement": {
        "key":      "hunt_lateral_movement",
        "name":     "Threat Hunt: Lateral Movement Detection",
        "category": "threat_hunt",
        "phase":    "detection",
        "mitre_tactics": ["TA0008"],
        "description": "Proactive hunt for adversary lateral movement using SIEM logs, netflow, and endpoint telemetry.",
        "estimated_hours": 4,
        "steps": [
            {
                "index": 1,
                "title": "Establish Baseline",
                "description": "Collect 30-day baseline of normal SMB/WMI/RDP connections between hosts.",
                "tools": ["SIEM", "network flow data"],
                "commands": [
                    "Get-WinEvent -LogName Security -FilterXPath '*[System[EventID=4624 or EventID=4625]]' | Export-Csv auth_baseline.csv",
                    "Get-WinEvent -LogName Security -FilterXPath '*[System[EventID=4648]]' | Export-Csv explicit_logons.csv",
                ],
                "expected_outcome": "Baseline CSV of normal authentication patterns",
                "technique": "T1078",
                "gate": None,
            },
            {
                "index": 2,
                "title": "Anomalous Authentication Hunt",
                "description": "Identify accounts authenticating to unusual numbers of hosts within short time windows.",
                "tools": ["SIEM", "PowerShell"],
                "commands": [
                    "# SIEM query: accounts with >10 unique dest hosts in 1 hour",
                    "index=security sourcetype=WinEventLog EventID=4624 | stats dc(dest_host) as unique_dest by user, _time span=1h | where unique_dest > 10",
                    "# Check for Pass-the-Hash indicators (Type 3 logon from non-interactive source)",
                    "Get-WinEvent | Where-Object {$_.Id -eq 4624 -and $_.Properties[8].Value -eq 3}",
                ],
                "expected_outcome": "List of accounts with anomalous lateral auth patterns",
                "technique": "T1550.002",
                "gate": "If >0 anomalous accounts found → escalate to IR playbook",
            },
            {
                "index": 3,
                "title": "SMB Lateral Movement Detection",
                "description": "Look for PsExec, SC.exe, and remote service creation artifacts.",
                "tools": ["Sysmon", "SIEM"],
                "commands": [
                    "# Sysmon Event ID 3 (network connection) to port 445 from non-system processes",
                    "Get-WinEvent -LogName 'Microsoft-Windows-Sysmon/Operational' | Where-Object {$_.Id -eq 3 -and $_.Message -match ':445'}",
                    "# Remote service creation (Event 7045 on remote host)",
                    "Get-WinEvent -ComputerName <target> -LogName System -FilterXPath '*[System[EventID=7045]]'",
                ],
                "expected_outcome": "Identified PsExec/remote service artifacts",
                "technique": "T1021.002",
                "gate": None,
            },
            {
                "index": 4,
                "title": "WMI Lateral Movement",
                "description": "Detect WMI-based remote execution patterns.",
                "tools": ["Sysmon", "WMI logs"],
                "commands": [
                    "Get-WinEvent -LogName 'Microsoft-Windows-WMI-Activity/Operational' | Where-Object {$_.Id -eq 5857 -or $_.Id -eq 5861}",
                    "# Correlate with process creation from WmiPrvSE.exe",
                    "Get-WinEvent -LogName 'Microsoft-Windows-Sysmon/Operational' | Where-Object {$_.Id -eq 1 -and $_.Message -match 'WmiPrvSE'}",
                ],
                "expected_outcome": "WMI remote execution timeline",
                "technique": "T1047",
                "gate": None,
            },
            {
                "index": 5,
                "title": "Document and Report Findings",
                "description": "Compile hunt findings into a structured threat report.",
                "tools": ["Report template"],
                "commands": [
                    "# Generate hunt report via JAKAL: POST /api/reports/aggregate",
                    "curl -X POST http://localhost:8000/api/reports/aggregate -H 'Content-Type: application/json' -d @hunt_results.json",
                ],
                "expected_outcome": "Signed hunt report with indicators of compromise",
                "technique": "",
                "gate": None,
            },
        ],
    },

    "hunt_persistence": {
        "key":      "hunt_persistence",
        "name":     "Threat Hunt: Persistence Mechanisms",
        "category": "threat_hunt",
        "phase":    "detection",
        "mitre_tactics": ["TA0003"],
        "description": "Hunt for malicious persistence across registry, scheduled tasks, services, and startup locations.",
        "estimated_hours": 3,
        "steps": [
            {
                "index": 1, "title": "Registry Run Key Hunt",
                "description": "Enumerate all run keys and compare to known-good baseline.",
                "tools": ["PowerShell", "Autoruns"],
                "commands": [
                    "reg query HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
                    "reg query HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
                    "# Autoruns export",
                    "autorunsc.exe -accepteula -a * -user * -c > autoruns_output.csv",
                ],
                "expected_outcome": "CSV of all run-key entries vs baseline",
                "technique": "T1547.001",
                "gate": None,
            },
            {
                "index": 2, "title": "Scheduled Task Analysis",
                "description": "Review all scheduled tasks for unsigned binaries or suspicious paths.",
                "tools": ["schtasks", "PowerShell"],
                "commands": [
                    "schtasks /query /fo CSV /v > all_tasks.csv",
                    "Get-ScheduledTask | Where-Object {$_.TaskPath -notlike '\\Microsoft\\*'} | Export-Csv custom_tasks.csv",
                    "# Check for tasks running from temp/appdata",
                    "schtasks /query /fo LIST /v | findstr /i 'Task To Run' | findstr /i 'appdata temp'",
                ],
                "expected_outcome": "List of non-Microsoft scheduled tasks with binary paths",
                "technique": "T1053.005",
                "gate": None,
            },
            {
                "index": 3, "title": "WMI Subscription Hunt",
                "description": "Enumerate persistent WMI event subscriptions (common fileless persistence method).",
                "tools": ["PowerShell", "WMI"],
                "commands": [
                    "Get-WMIObject -Namespace root/subscription -Class __EventFilter",
                    "Get-WMIObject -Namespace root/subscription -Class __EventConsumer",
                    "Get-WMIObject -Namespace root/subscription -Class __FilterToConsumerBinding",
                ],
                "expected_outcome": "Any WMI subscriptions not part of known software",
                "technique": "T1546.003",
                "gate": "If subscriptions found outside AV/EDR → high priority IOC",
            },
        ],
    },

    # ================================================================
    # INCIDENT RESPONSE PLAYBOOKS
    # ================================================================

    "ir_ransomware": {
        "key":      "ir_ransomware",
        "name":     "IR: Ransomware Response",
        "category": "incident_response",
        "phase":    "containment",
        "mitre_tactics": ["TA0040", "TA0010"],
        "description": "End-to-end ransomware incident response: detection, containment, eradication, recovery.",
        "estimated_hours": 24,
        "steps": [
            {
                "index": 1, "title": "IMMEDIATE: Network Isolation",
                "description": "Isolate affected hosts from network to stop lateral spread. Critical — do this within minutes.",
                "tools": ["EDR console", "firewall", "VLAN management"],
                "commands": [
                    "# Windows — disable NIC (run as admin on affected host)",
                    "netsh interface set interface 'Ethernet' admin=disabled",
                    "# Linux — bring down interface",
                    "ip link set eth0 down",
                    "# Firewall — block affected subnet (Palo Alto example)",
                    "# set security policy-rule 'Block-Ransomware' action deny source <affected-subnet>",
                ],
                "expected_outcome": "Affected host(s) isolated from network — lateral spread halted",
                "technique": "",
                "gate": "Confirm isolation before proceeding to step 2",
            },
            {
                "index": 2, "title": "Preserve Evidence (Memory + Disk)",
                "description": "Capture volatile memory and disk images before any remediation.",
                "tools": ["WinPmem", "FTK Imager", "dc3dd"],
                "commands": [
                    "# Windows memory capture",
                    "winpmem_mini_x64.exe memdump.raw",
                    "# Disk image",
                    "dc3dd if=\\\\.\\PhysicalDrive0 of=disk_image.dd hash=sha256 log=dc3dd.log",
                    "# Linux memory",
                    "sudo avml /tmp/memory.lime",
                    "sudo dc3dd if=/dev/sda of=/mnt/evidence/disk.dd hash=sha256",
                ],
                "expected_outcome": "SHA-256 verified memory + disk images in evidence folder",
                "technique": "",
                "gate": None,
            },
            {
                "index": 3, "title": "Identify Patient Zero and IOCs",
                "description": "Determine initial infection vector and extract IOCs.",
                "tools": ["SIEM", "EDR", "Volatility"],
                "commands": [
                    "# Volatility: process list at time of infection",
                    "python3 vol.py -f memdump.raw windows.pslist | tee pslist.txt",
                    "# Network connections at time of infection",
                    "python3 vol.py -f memdump.raw windows.netstat | tee netstat.txt",
                    "# Find encryption process",
                    "python3 vol.py -f memdump.raw windows.pstree | grep -A5 -B5 <ransomware_proc>",
                    "# SIEM: first appearance of encrypted extension",
                    "index=endpoint | search '*.encrypted OR *.locked OR *RANSOM*' | sort _time | head 1",
                ],
                "expected_outcome": "Patient zero host, initial vector, IOC list (hashes, IPs, domains)",
                "technique": "T1486",
                "gate": None,
            },
            {
                "index": 4, "title": "Eradication: Remove Ransomware Artifacts",
                "description": "Remove ransomware binary, persistence mechanisms, and lateral tools.",
                "tools": ["EDR", "PowerShell"],
                "commands": [
                    "# Remove ransomware process (use EDR isolation first)",
                    "# After forensic capture: delete binary and persistence",
                    "# Scheduled tasks",
                    "schtasks /delete /tn '<malicious_task>' /f",
                    "# Registry run keys",
                    "reg delete 'HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run' /v '<malicious_entry>' /f",
                    "# Reset shadow copies check (ransomware often deletes these)",
                    "vssadmin list shadows",
                ],
                "expected_outcome": "All ransomware artifacts removed, persistence cleaned",
                "technique": "",
                "gate": "Verify with EDR scan before recovery",
            },
            {
                "index": 5, "title": "Recovery from Backup",
                "description": "Restore systems from verified clean backups.",
                "tools": ["Backup solution", "validation scripts"],
                "commands": [
                    "# Verify backup integrity before restore",
                    "sha256sum backup_<date>.tar.gz | diff - backup_<date>.sha256",
                    "# Restore (example with tar)",
                    "tar -xzf backup_<date>.tar.gz -C /restore/",
                    "# Post-restore: validate service health",
                    "curl -f http://localhost/health || echo 'HEALTH CHECK FAILED'",
                ],
                "expected_outcome": "Systems restored to clean state from verified backup",
                "technique": "",
                "gate": "Full AV/EDR scan clean before re-connecting to network",
            },
        ],
    },

    # ================================================================
    # RED TEAM PLAYBOOKS
    # ================================================================

    "redteam_initial_access": {
        "key":      "redteam_initial_access",
        "name":     "Red Team: External Initial Access Assessment",
        "category": "red_team",
        "phase":    "initial_access",
        "mitre_tactics": ["TA0001"],
        "description": "Authorized external attack simulation to test perimeter defenses. Requires signed ROE.",
        "estimated_hours": 8,
        "steps": [
            {
                "index": 1, "title": "External Attack Surface Discovery",
                "description": "Map the external attack surface: exposed services, certificates, emails.",
                "tools": ["amass", "subfinder", "shodan", "crt.sh"],
                "commands": [
                    "amass enum -active -d <target_domain> -o amass_output.txt",
                    "subfinder -d <target_domain> -all -o subfinder_output.txt",
                    "cat amass_output.txt subfinder_output.txt | sort -u > all_subdomains.txt",
                    "# Resolve live subdomains",
                    "cat all_subdomains.txt | httpx -silent -status-code -title -o live_subdomains.txt",
                    "nuclei -l live_subdomains.txt -t exposures/ -t misconfigurations/ -json -o nuclei_external.json",
                ],
                "expected_outcome": "Live subdomain list + initial vulnerability hits",
                "technique": "T1595",
                "gate": None,
            },
            {
                "index": 2, "title": "Web Application Attack Vector Testing",
                "description": "Test top-priority web applications for OWASP Top 10 vulnerabilities.",
                "tools": ["nuclei", "ffuf", "burpsuite"],
                "commands": [
                    "nuclei -u https://<target> -t cves/ -t vulnerabilities/ -t exposures/ -json -o nuclei_webapp.json",
                    "ffuf -w /usr/share/seclists/Discovery/Web-Content/raft-large-directories.txt -u https://<target>/FUZZ -mc 200,301,302,403",
                    "# Check for default credentials",
                    "nuclei -u https://<target> -t default-logins/",
                ],
                "expected_outcome": "Exploitable web vulnerabilities ranked by CVSS",
                "technique": "T1190",
                "gate": "Any critical findings → pause and notify blue team per ROE",
            },
        ],
    },

    # ================================================================
    # COMPLIANCE PLAYBOOKS
    # ================================================================

    "compliance_nist_csf": {
        "key":      "compliance_nist_csf",
        "name":     "Compliance: NIST CSF 2.0 Control Validation",
        "category": "compliance",
        "phase":    "assessment",
        "mitre_tactics": [],
        "description": "Validate NIST Cybersecurity Framework 2.0 controls across Identify, Protect, Detect, Respond, Recover, Govern.",
        "estimated_hours": 16,
        "steps": [
            {
                "index": 1, "title": "GOVERN: Policy and Governance Check",
                "description": "Verify cybersecurity policies exist and are current (< 12 months).",
                "tools": ["Document review"],
                "commands": [
                    "# Check policy document dates",
                    "find /policies -name '*.pdf' -newer /tmp/12months_ago",
                    "# Verify policy acknowledgment records",
                ],
                "expected_outcome": "Policy inventory with last-review dates",
                "technique": "",
                "gate": None,
            },
            {
                "index": 2, "title": "IDENTIFY: Asset Inventory",
                "description": "Validate complete hardware/software asset inventory.",
                "tools": ["nmap", "CMDB", "SCCM/Lansweeper"],
                "commands": [
                    "# Network sweep for undiscovered assets",
                    "nmap -sn 10.0.0.0/8 -oG - | grep 'Up' > discovered_hosts.txt",
                    "# Compare with CMDB",
                    "diff <(sort discovered_hosts.txt) <(sort cmdb_export.txt) > delta_assets.txt",
                ],
                "expected_outcome": "Asset inventory gap analysis (discovered vs recorded)",
                "technique": "",
                "gate": None,
            },
            {
                "index": 3, "title": "PROTECT: Access Control Validation",
                "description": "Test MFA enforcement, privileged access controls, and least-privilege.",
                "tools": ["AD audit tools", "Azure AD", "CyberArk"],
                "commands": [
                    "# AD: accounts with no MFA",
                    "Get-MsolUser -All | Where-Object {$_.StrongAuthenticationRequirements.Count -eq 0} | Export-Csv no_mfa.csv",
                    "# Privileged accounts audit",
                    "Get-ADGroupMember 'Domain Admins' | Get-ADUser -Properties * | Export-Csv da_accounts.csv",
                    "# Stale accounts (not logged in 90 days)",
                    "Search-ADAccount -AccountInactive -TimeSpan 90.00:00:00 | Export-Csv stale_accounts.csv",
                ],
                "expected_outcome": "MFA gaps, privileged account list, stale account report",
                "technique": "T1078",
                "gate": None,
            },
            {
                "index": 4, "title": "DETECT: SIEM and Alerting Coverage",
                "description": "Validate log sources are feeding SIEM and critical alerts are tuned.",
                "tools": ["SIEM"],
                "commands": [
                    "# Check log freshness per source",
                    "# SIEM query: sources with no events in last 24h",
                    "index=* | stats max(_time) as last_event by host | where last_event < relative_time(now(),'-24h')",
                    "# Verify critical alert rules are enabled",
                ],
                "expected_outcome": "Log source coverage map + alert rule inventory",
                "technique": "",
                "gate": None,
            },
            {
                "index": 5, "title": "RECOVER: Backup Validation",
                "description": "Test backup integrity and recovery time objective (RTO).",
                "tools": ["Backup solution", "test environment"],
                "commands": [
                    "# Verify latest backup hash matches expected",
                    "sha256sum /backups/latest.tar.gz | diff - /backups/latest.sha256",
                    "# Test restore in isolated environment",
                    "# Document actual RTO vs target RTO",
                ],
                "expected_outcome": "Backup verification report + actual vs target RTO",
                "technique": "",
                "gate": None,
            },
        ],
    },

    # ================================================================
    # QUANTUM SECURITY PLAYBOOKS
    # ================================================================

    "quantum_pqc_migration": {
        "key":      "quantum_pqc_migration",
        "name":     "Quantum Security: PQC Migration Assessment",
        "category": "quantum_security",
        "phase":    "assessment",
        "mitre_tactics": [],
        "description": "Assess and plan migration from classical to post-quantum cryptography. Addresses harvest-now-decrypt-later threat.",
        "estimated_hours": 20,
        "steps": [
            {
                "index": 1, "title": "Cryptographic Asset Inventory",
                "description": "Identify all cryptographic algorithms in use across the organization.",
                "tools": ["openssl", "nmap", "code scanning"],
                "commands": [
                    "# Find RSA/ECC cert usage across internal hosts",
                    "nmap --script ssl-cert -p443,8443,8080 10.0.0.0/24 | grep 'Public Key'",
                    "# Find hardcoded algorithm references in code",
                    "grep -rn --include='*.py' --include='*.java' --include='*.go' -E 'RSA|ECDSA|AES-128|MD5|SHA1' /src/",
                    "# Check SSH key types",
                    "for h in $(cat hosts.txt); do ssh-keyscan -t rsa,ecdsa,ed25519 $h 2>/dev/null; done | awk '{print $1,$2,$3}' | sort -u",
                ],
                "expected_outcome": "Cryptographic inventory: algorithm, location, expiry, owner",
                "technique": "",
                "gate": None,
            },
            {
                "index": 2, "title": "Quantum Risk Scoring",
                "description": "Score each cryptographic asset by quantum-vulnerability and data sensitivity.",
                "tools": ["JAKAL Quantum Risk Panel"],
                "commands": [
                    "# Run JAKAL quantum risk analysis",
                    "curl http://localhost:8000/api/quantum/risk-panel",
                    "# Run QPU diagnostics",
                    "curl http://localhost:8000/api/quantum/diagnostics",
                    "# Score by: sensitivity * years-until-quantum-threat * migration-complexity",
                ],
                "expected_outcome": "Risk-scored migration priority list",
                "technique": "",
                "gate": None,
            },
            {
                "index": 3, "title": "PQC Algorithm Selection",
                "description": "Select NIST-standardized PQC algorithms for each use case.",
                "tools": ["JAKAL PQC Manager"],
                "commands": [
                    "# Test ML-DSA-65 (Dilithium3) signature performance",
                    "curl -X POST http://localhost:8000/api/crypto/pqc/sign -d '{\"payload\":{\"test\":true},\"agent_id\":\"test\"}'",
                    "# Check current PQC status",
                    "curl http://localhost:8000/api/crypto/pqc/status",
                    "# Recommended mappings:",
                    "# Digital signatures: ML-DSA-65 (Dilithium3) — replaces RSA/ECDSA",
                    "# Key encapsulation: ML-KEM-768 (Kyber) — replaces RSA/ECDH",
                    "# General encryption: AES-256-GCM (already quantum-resistant with Grover caveat)",
                ],
                "expected_outcome": "Algorithm selection document per use-case",
                "technique": "",
                "gate": None,
            },
            {
                "index": 4, "title": "Hybrid Classical+PQC Implementation",
                "description": "Implement hybrid schemes that use both classical and PQC algorithms during transition.",
                "tools": ["OpenSSL 3.3+", "liboqs", "JAKAL EncryptionManager"],
                "commands": [
                    "# Test JAKAL hybrid encryption",
                    "curl -X POST http://localhost:8000/api/crypto/encrypt -d '{\"data\":\"sensitive report\",\"use_chacha\":false}'",
                    "# Verify the AES-256 + PQC-signed envelope",
                    "curl -X POST http://localhost:8000/api/crypto/verify-chain",
                ],
                "expected_outcome": "Hybrid encryption implemented on at least 1 production system",
                "technique": "",
                "gate": "Hybrid before dropping classical — ensures backward compat",
            },
            {
                "index": 5, "title": "Long-lived Data Re-encryption",
                "description": "Identify and re-encrypt data that must remain confidential for 10+ years.",
                "tools": ["JAKAL EncryptionManager"],
                "commands": [
                    "# Identify data with long-term sensitivity (> 10 years)",
                    "# Re-encrypt with AES-256-GCM using quantum-seeded key",
                    "curl -X POST http://localhost:8000/api/crypto/encrypt-report -d '{\"report_id\":\"<id>\"}'",
                    "# Store encryption metadata for future key rotation",
                ],
                "expected_outcome": "High-priority long-lived data re-encrypted with PQC-seeded keys",
                "technique": "",
                "gate": None,
            },
        ],
    },

    "quantum_entropy_validation": {
        "key":      "quantum_entropy_validation",
        "name":     "Quantum Security: Entropy Source Validation",
        "category": "quantum_security",
        "phase":    "assessment",
        "mitre_tactics": [],
        "description": "Validate the quality of quantum entropy used to seed cryptographic operations.",
        "estimated_hours": 2,
        "steps": [
            {
                "index": 1, "title": "Run QPU Diagnostics",
                "commands": ["curl http://localhost:8000/api/quantum/diagnostics"],
                "description": "Verify Qiskit-Aer simulator health — Bell state, QFT, entropy.",
                "tools": ["JAKAL QPU Simulator"],
                "expected_outcome": "All diagnostics pass with OK status",
                "technique": "",
                "gate": None,
            },
            {
                "index": 2, "title": "Entropy Bit Distribution Test",
                "commands": [
                    "curl 'http://localhost:8000/api/quantum/entropy?bits=1024'",
                    "# Verify ~50% ones ratio (random should be 50% ±3%)",
                ],
                "description": "Generate 1024 quantum random bits and verify uniform distribution.",
                "tools": ["JAKAL QPU Simulator"],
                "expected_outcome": "Ones ratio between 47-53% across multiple samples",
                "technique": "",
                "gate": None,
            },
            {
                "index": 3, "title": "Run 20x PQC Validation Loop",
                "commands": [
                    "curl -X POST http://localhost:8000/api/crypto/pqc/validate-20x",
                    "# Should return 20/20 passed",
                ],
                "description": "Execute the 20-iteration ML-DSA sign/verify + quantum entropy loop.",
                "tools": ["JAKAL PQC Manager", "JAKAL QPU Simulator"],
                "expected_outcome": "20/20 iterations passed with zero failures",
                "technique": "",
                "gate": "Any failure → review dilithium-py installation and entropy source",
            },
        ],
    },

}


def get_all_playbooks() -> List[Dict[str, Any]]:
    """Return all playbooks as a list."""
    return list(PLAYBOOKS.values())


def get_playbook(key: str) -> Dict[str, Any]:
    """Return a specific playbook by key."""
    pb = PLAYBOOKS.get(key)
    if pb is None:
        raise KeyError(f"Playbook '{key}' not found. Available: {list(PLAYBOOKS)}")
    return pb


def get_playbooks_by_category(category: str) -> List[Dict[str, Any]]:
    """Return all playbooks for a given category."""
    return [pb for pb in PLAYBOOKS.values() if pb["category"] == category]


def list_categories() -> List[str]:
    return sorted(set(pb["category"] for pb in PLAYBOOKS.values()))


def seed_playbooks_to_db(db) -> Dict[str, Any]:
    """
    Seed all playbooks into the DuckDB playbooks table.
    Safe to call multiple times (skips existing keys).
    """
    inserted, skipped = 0, 0
    for key, pb in PLAYBOOKS.items():
        existing = db.get_playbook_by_key(key)
        if existing:
            skipped += 1
            continue
        db.insert_playbook(
            key=pb["key"],
            name=pb["name"],
            category=pb["category"],
            steps=pb["steps"],
        )
        inserted += 1
    return {
        "inserted": inserted,
        "skipped": skipped,
        "total": len(PLAYBOOKS),
    }
