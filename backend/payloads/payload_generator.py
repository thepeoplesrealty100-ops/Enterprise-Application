"""
backend/payloads/payload_generator.py
Pre-populated command payload generator for JAKAL.

Generates structured, parameterized command sets for each phase of an
authorized penetration test. Every payload is:
  - Pre-validated against the authorized target before generation
  - Parameterized (target / port / wordlist are variables, not hardcoded)
  - Annotated with MITRE ATT&CK technique IDs
  - Grouped by PTES / CPENT phase

Usage:
    gen = PayloadGenerator()
    payloads = gen.generate_phase("recon", target="192.168.1.0/24")

IMPORTANT: These payloads are for use ONLY against authorized targets
within a signed scope/ROE agreement. The generation functions do not
execute commands — they produce structured command strings for operator
review before execution via the VM Orchestrator or a terminal session.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Target sanitization (must pass before any payload is generated)
# ---------------------------------------------------------------------------

_SAFE_TARGET = re.compile(r'^[a-zA-Z0-9.\-_:/\[\]/]+$')


def _validate_target(target: str) -> str:
    target = target.strip()
    if not _SAFE_TARGET.match(target):
        raise ValueError(f"Unsafe target: {target!r}")
    return target


# ---------------------------------------------------------------------------
# Payload dataclass
# ---------------------------------------------------------------------------

class Payload:
    """A single executable command with metadata."""

    def __init__(
        self,
        command: str,
        description: str,
        phase: str,
        technique_id: str = "",
        risk: str = "LOW",
        requires_root: bool = False,
        tool: str = "",
    ):
        self.command       = command
        self.description   = description
        self.phase         = phase
        self.technique_id  = technique_id   # MITRE ATT&CK T-number
        self.risk          = risk            # LOW / MEDIUM / HIGH
        self.requires_root = requires_root
        self.tool          = tool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command":       self.command,
            "description":   self.description,
            "phase":         self.phase,
            "technique_id":  self.technique_id,
            "risk":          self.risk,
            "requires_root": self.requires_root,
            "tool":          self.tool,
        }


# ---------------------------------------------------------------------------
# Phase generators
# ---------------------------------------------------------------------------

class PayloadGenerator:
    """
    Generates pre-populated, parameterized command sets for each pentest phase.
    All methods return List[Payload].
    """

    # ------------------------------------------------------------------
    # Phase 1: Reconnaissance (Passive + Active)
    # ------------------------------------------------------------------

    def recon_passive(self, target: str, domain: str = "") -> List[Payload]:
        """OSINT and passive recon — no packets sent to target."""
        t = _validate_target(target)
        d = domain or t
        return [
            Payload(f"whois {d}", "WHOIS domain registration info", "recon_passive", "T1590.001", "LOW", tool="whois"),
            Payload(f"dig ANY {d} +noall +answer", "Full DNS record dump", "recon_passive", "T1590.002", "LOW", tool="dig"),
            Payload(f"dig axfr {d} @{d}", "Attempt DNS zone transfer (often blocked)", "recon_passive", "T1590.002", "LOW", tool="dig"),
            Payload(f"nslookup -type=mx {d}", "Mail server (MX) enumeration", "recon_passive", "T1590.002", "LOW", tool="nslookup"),
            Payload(f"curl -s https://crt.sh/?q=%25.{d}&output=json | python3 -m json.tool | grep name_value | sort -u",
                    "Certificate Transparency log subdomain harvest", "recon_passive", "T1590.001", "LOW", tool="curl+crt.sh"),
            Payload(f"shodan host {t}", "Shodan host intelligence (requires API key)", "recon_passive", "T1596.005", "LOW", tool="shodan-cli"),
            Payload(f"theHarvester -d {d} -b google,bing,duckduckgo -l 200",
                    "Email/subdomain harvest from search engines", "recon_passive", "T1589", "LOW", tool="theHarvester"),
            Payload(f"subfinder -d {d} -silent", "Passive subdomain enumeration", "recon_passive", "T1590.001", "LOW", tool="subfinder"),
            Payload(f"amass enum -passive -d {d}", "AMASS passive enumeration", "recon_passive", "T1590", "LOW", tool="amass"),
        ]

    def recon_active(self, target: str, ports: str = "1-1000") -> List[Payload]:
        """Active network reconnaissance — sends packets to target."""
        t = _validate_target(target)
        return [
            Payload(f"nmap -sn {t}", "Ping sweep / host discovery", "recon_active", "T1595.001", "LOW", tool="nmap"),
            Payload(f"nmap -sV -sC -p {ports} {t} -oA scan_{t.replace('/','_')}",
                    "Service version + default script scan", "recon_active", "T1595.001", "MEDIUM", requires_root=True, tool="nmap"),
            Payload(f"nmap -sS -T4 -p- {t} -oA fullscan_{t.replace('/','_')}",
                    "Full port SYN scan (all 65535)", "recon_active", "T1595.001", "MEDIUM", requires_root=True, tool="nmap"),
            Payload(f"nmap -sU --top-ports 100 {t}",
                    "Top 100 UDP ports scan", "recon_active", "T1595.001", "MEDIUM", requires_root=True, tool="nmap"),
            Payload(f"nmap -sV --script=banner {t}",
                    "Service banner grab", "recon_active", "T1592.002", "LOW", tool="nmap"),
            Payload(f"nmap --script=http-title,http-headers -p80,443,8080,8443 {t}",
                    "HTTP title and header enumeration", "recon_active", "T1592.002", "LOW", tool="nmap"),
            Payload(f"masscan -p1-65535 {t} --rate=1000 -oJ masscan_{t.replace('/','_')}.json",
                    "High-speed port scan with masscan", "recon_active", "T1595.001", "MEDIUM", requires_root=True, tool="masscan"),
        ]

    # ------------------------------------------------------------------
    # Phase 2: Enumeration / Scanning
    # ------------------------------------------------------------------

    def enumeration(self, target: str, ports: Optional[List[int]] = None) -> List[Payload]:
        """Service-specific enumeration after open ports identified."""
        t = _validate_target(target)
        open_ports = ports or [21, 22, 80, 443, 445, 3389]
        payloads = []

        # SMB
        if 445 in open_ports or 139 in open_ports:
            payloads += [
                Payload(f"nmap --script smb-enum-shares,smb-enum-users -p445 {t}", "SMB share and user enumeration", "enumeration", "T1135", "MEDIUM", tool="nmap"),
                Payload(f"enum4linux -a {t}", "Full SMB/NetBIOS enumeration (Linux)", "enumeration", "T1018", "MEDIUM", tool="enum4linux"),
                Payload(f"smbclient -L //{t} -N", "List SMB shares (anonymous)", "enumeration", "T1135", "MEDIUM", tool="smbclient"),
                Payload(f"crackmapexec smb {t} --shares -u '' -p ''", "SMB share enum via CrackMapExec", "enumeration", "T1135", "MEDIUM", tool="crackmapexec"),
            ]

        # SSH
        if 22 in open_ports:
            payloads += [
                Payload(f"nmap --script ssh-auth-methods -p22 {t}", "SSH auth method enumeration", "enumeration", "T1110", "LOW", tool="nmap"),
                Payload(f"nmap --script ssh2-enum-algos -p22 {t}", "SSH cipher/algorithm audit", "enumeration", "T1590.005", "LOW", tool="nmap"),
            ]

        # FTP
        if 21 in open_ports:
            payloads += [
                Payload(f"nmap --script ftp-anon,ftp-bounce -p21 {t}", "FTP anonymous login + bounce check", "enumeration", "T1078", "MEDIUM", tool="nmap"),
                Payload(f"ftp -n {t} <<< $'user anonymous\\npass test@test.com\\nls\\nquit'", "Manual FTP anonymous login", "enumeration", "T1078", "LOW", tool="ftp"),
            ]

        # SNMP
        payloads += [
            Payload(f"nmap -sU --script snmp-info,snmp-sysdescr -p161 {t}", "SNMP info enumeration", "enumeration", "T1602.001", "LOW", tool="nmap"),
            Payload(f"snmpwalk -v2c -c public {t}", "SNMP walk with default community string", "enumeration", "T1602.001", "MEDIUM", tool="snmpwalk"),
        ]

        # LDAP
        payloads += [
            Payload(f"nmap --script ldap-rootdse -p389 {t}", "LDAP root DSE info", "enumeration", "T1087.002", "LOW", tool="nmap"),
            Payload(f"ldapsearch -x -H ldap://{t} -b '' -s base", "LDAP anonymous bind enumeration", "enumeration", "T1087.002", "MEDIUM", tool="ldapsearch"),
        ]

        return payloads

    # ------------------------------------------------------------------
    # Phase 3: Web Application Testing
    # ------------------------------------------------------------------

    def web_application(self, target: str, port: int = 80, protocol: str = "http") -> List[Payload]:
        """Web application security testing payloads."""
        t = _validate_target(target)
        base_url = f"{protocol}://{t}" if not t.startswith("http") else t
        return [
            # Discovery
            Payload(f"nikto -h {base_url}:{port} -o nikto_{t}.html -Format htm",
                    "Comprehensive web vulnerability scan", "web", "T1190", "MEDIUM", tool="nikto"),
            Payload(f"gobuster dir -u {base_url}:{port} -w /usr/share/wordlists/dirb/common.txt -t 50 -o gobuster_{t}.txt",
                    "Directory brute-force with common wordlist", "web", "T1083", "MEDIUM", tool="gobuster"),
            Payload(f"gobuster dir -u {base_url}:{port} -w /usr/share/seclists/Discovery/Web-Content/raft-medium-directories.txt -x php,html,js,txt,bak -t 50",
                    "Extended directory scan with file extensions", "web", "T1083", "MEDIUM", tool="gobuster"),
            Payload(f"ffuf -w /usr/share/seclists/Discovery/Web-Content/raft-medium-words.txt -u {base_url}:{port}/FUZZ -mc 200,301,302,403 -o ffuf_{t}.json -of json",
                    "Fast web fuzzer (FFUF) directory discovery", "web", "T1083", "MEDIUM", tool="ffuf"),

            # Headers / SSL
            Payload(f"curl -I -s {base_url}:{port}/ | head -30",
                    "HTTP response header inspection", "web", "T1592.002", "LOW", tool="curl"),
            Payload(f"nmap --script http-security-headers -p{port} {t}",
                    "HTTP security headers audit", "web", "T1590.005", "LOW", tool="nmap"),
            Payload(f"nmap --script ssl-cert,ssl-enum-ciphers -p443 {t}",
                    "SSL/TLS certificate and cipher audit", "web", "T1590.005", "LOW", tool="nmap"),
            Payload(f"sslyze --regular {t}:{port}",
                    "SSL/TLS configuration analysis", "web", "T1590.005", "LOW", tool="sslyze"),

            # Injection
            Payload(f"sqlmap -u '{base_url}:{port}/' --forms --batch --random-agent --level=3 --risk=2",
                    "Automated SQL injection discovery via forms", "web", "T1190", "MEDIUM", tool="sqlmap"),
            Payload(f"nuclei -u {base_url}:{port} -t cves/ -t exposures/ -t vulnerabilities/ -o nuclei_{t}.json -json",
                    "Nuclei template-based CVE + exposure scan", "web", "T1190", "MEDIUM", tool="nuclei"),

            # CMS
            Payload(f"wpscan --url {base_url}:{port} --enumerate u,p,t --api-token $WPSCAN_API_TOKEN",
                    "WordPress vulnerability and user enumeration", "web", "T1595", "MEDIUM", tool="wpscan"),
            Payload(f"droopescan scan drupal -u {base_url}:{port}",
                    "Drupal version and vulnerability scan", "web", "T1595", "MEDIUM", tool="droopescan"),
        ]

    # ------------------------------------------------------------------
    # Phase 4: Vulnerability Analysis
    # ------------------------------------------------------------------

    def vulnerability_analysis(self, target: str, cve_list: Optional[List[str]] = None) -> List[Payload]:
        """Targeted vulnerability analysis and CVE validation."""
        t = _validate_target(target)
        payloads = [
            Payload(f"nuclei -t cves/ -u {t} -json -o vuln_cves_{t}.json",
                    "CVE template scan via Nuclei", "vuln_analysis", "T1203", "HIGH", tool="nuclei"),
            Payload(f"nuclei -t network/ -u {t} -json", "Network-level vulnerability templates", "vuln_analysis", "T1203", "MEDIUM", tool="nuclei"),
            Payload(f"nmap --script vuln -p- {t} -oN vuln_scan_{t}.txt",
                    "NSE vulnerability script suite", "vuln_analysis", "T1203", "HIGH", tool="nmap"),
            Payload(f"nmap --script exploit -p- {t}",
                    "NSE exploit check scripts (safe)", "vuln_analysis", "T1203", "HIGH", tool="nmap"),
            Payload(f"searchsploit --nmap nmap_output.xml",
                    "Match nmap output against ExploitDB", "vuln_analysis", "T1203", "LOW", tool="searchsploit"),
        ]
        if cve_list:
            for cve in cve_list:
                payloads.append(
                    Payload(f"nuclei -t cves/{cve.lower()}.yaml -u {t}",
                            f"Validate specific CVE {cve}", "vuln_analysis", "T1203", "HIGH", tool="nuclei")
                )
        return payloads

    # ------------------------------------------------------------------
    # Phase 5: Post-Exploitation (authorized post-compromise assessment)
    # ------------------------------------------------------------------

    def post_exploitation_assessment(self, target: str, shell_type: str = "linux") -> List[Payload]:
        """
        Post-compromise assessment commands for authorized red team exercises.
        These simulate adversary behavior to validate detection capabilities.
        REQUIRES: active authorized session / shell on target.
        """
        t = _validate_target(target)
        if shell_type == "linux":
            return [
                Payload("id && whoami && hostname", "Current user / host context", "post_exploit", "T1033", "LOW", tool="shell"),
                Payload("cat /etc/passwd | grep -v nologin", "Local user enumeration", "post_exploit", "T1087.001", "LOW", tool="shell"),
                Payload("sudo -l 2>/dev/null", "Check sudo privileges", "post_exploit", "T1548.003", "LOW", tool="shell"),
                Payload("find / -perm -4000 -type f 2>/dev/null", "SUID binary discovery", "post_exploit", "T1548.001", "MEDIUM", tool="shell"),
                Payload("ss -tlnp || netstat -tlnp", "Active listening ports", "post_exploit", "T1049", "LOW", tool="shell"),
                Payload("ps aux --forest", "Running process tree", "post_exploit", "T1057", "LOW", tool="shell"),
                Payload("cat /proc/net/arp && arp -n", "ARP table / adjacent hosts", "post_exploit", "T1018", "LOW", tool="shell"),
                Payload("crontab -l; ls -la /etc/cron*", "Scheduled task enumeration", "post_exploit", "T1053.003", "LOW", tool="shell"),
                Payload("env | grep -i pass; cat ~/.bash_history | grep -i pass",
                        "Credential discovery in env/history", "post_exploit", "T1552.003", "MEDIUM", tool="shell"),
                Payload("find /home /root -name '*.key' -o -name '*.pem' -o -name 'id_rsa' 2>/dev/null",
                        "SSH key discovery", "post_exploit", "T1552.004", "MEDIUM", tool="shell"),
            ]
        else:  # windows
            return [
                Payload("whoami /all", "Current user + privileges + SID", "post_exploit", "T1033", "LOW", tool="powershell"),
                Payload("net user && net localgroup administrators", "Local users and admin group", "post_exploit", "T1087.001", "LOW", tool="cmd"),
                Payload("systeminfo", "System info / patch level", "post_exploit", "T1082", "LOW", tool="cmd"),
                Payload("ipconfig /all && route print", "Network configuration", "post_exploit", "T1016", "LOW", tool="cmd"),
                Payload("netstat -ano", "Active connections + PID", "post_exploit", "T1049", "LOW", tool="cmd"),
                Payload("tasklist /v", "Running processes verbose", "post_exploit", "T1057", "LOW", tool="cmd"),
                Payload("schtasks /query /fo LIST /v", "Scheduled tasks enumeration", "post_exploit", "T1053.005", "LOW", tool="cmd"),
                Payload("reg query HKLM\\SYSTEM\\CurrentControlSet\\Services | findstr /i start",
                        "Auto-start services registry", "post_exploit", "T1547.001", "MEDIUM", tool="cmd"),
                Payload("wmic product get name,version", "Installed software", "post_exploit", "T1518", "LOW", tool="wmic"),
                Payload("dir /s /b *pass* *cred* *secret* C:\\Users 2>nul",
                        "Credential file discovery", "post_exploit", "T1552.001", "MEDIUM", tool="cmd"),
            ]

    # ------------------------------------------------------------------
    # Phase 6: Encryption & Crypto Analysis
    # ------------------------------------------------------------------

    def encryption_analysis(self, target: str, port: int = 443) -> List[Payload]:
        """TLS/SSL and cryptographic configuration assessment."""
        t = _validate_target(target)
        return [
            Payload(f"testssl.sh --full {t}:{port} | tee testssl_{t}.txt",
                    "Full TLS configuration audit (testssl.sh)", "crypto_analysis", "T1590.005", "LOW", tool="testssl.sh"),
            Payload(f"nmap --script ssl-cert,ssl-dh-params,ssl-poodle,ssl-heartbleed,ssl-ccs-injection -p{port} {t}",
                    "NSE TLS vulnerability checks (POODLE, Heartbleed, CCS)", "crypto_analysis", "T1190", "MEDIUM", tool="nmap"),
            Payload(f"sslyze --regular --json_out sslyze_{t}.json {t}:{port}",
                    "SSLyze cipher / cert analysis", "crypto_analysis", "T1590.005", "LOW", tool="sslyze"),
            Payload(f"openssl s_client -connect {t}:{port} -showcerts 2>/dev/null | openssl x509 -text -noout",
                    "Certificate chain inspection", "crypto_analysis", "T1590.005", "LOW", tool="openssl"),
            Payload(f"openssl s_client -connect {t}:{port} 2>/dev/null | grep 'Cipher'",
                    "Active cipher negotiation check", "crypto_analysis", "T1590.005", "LOW", tool="openssl"),
            Payload(f"nmap --script tls-ticketbleed -p{port} {t}",
                    "TLS Ticketbleed vulnerability (F5 BIG-IP)", "crypto_analysis", "T1190", "MEDIUM", tool="nmap"),
        ]

    # ------------------------------------------------------------------
    # Phase: Wireless Assessment (802.11 Wi-Fi + WPS)
    #
    # MITRE ATT&CK technique IDs used below are real, current Enterprise
    # ATT&CK technique/sub-technique IDs (verified against attack.mitre.org,
    # 2026):
    #   T1669       Wi-Fi Networks (discovery/access via nearby wireless nets)
    #   T1040       Network Sniffing (passive capture, incl. handshakes)
    #   T1557       Adversary-in-the-Middle (parent technique)
    #   T1557.004   AiTM: Evil Twin (rogue AP impersonating a legitimate SSID)
    #   T1110       Brute Force (parent technique, covers WPS PIN attacks)
    #   T1110.002   Brute Force: Password Cracking (offline handshake/PMKID crack)
    #   T1595       Active Scanning (parent, covers Bluetooth/BLE discovery)
    # `target` here is the BSSID (AP MAC) or SSID under test, `interface`
    # is the wireless NIC in monitor mode.
    # ------------------------------------------------------------------

    def wireless(
        self,
        target: str,
        interface: str = "wlan0",
        channel: Optional[int] = None,
        wordlist: str = "/usr/share/wordlists/rockyou.txt",
    ) -> List[Payload]:
        """802.11 Wi-Fi + WPS assessment payloads for an authorized wireless engagement."""
        t = _validate_target(target)
        mon = f"{interface}mon" if not interface.endswith("mon") else interface
        chan = f"-c {channel} " if channel else ""
        return [
            # --- Discovery / recon (passive-to-low-risk) ---
            Payload(f"airmon-ng start {interface}",
                    "Put wireless NIC into monitor mode", "wireless", "T1669", "LOW",
                    requires_root=True, tool="aircrack-ng-suite"),
            Payload(f"airodump-ng {mon}",
                    "Survey nearby APs and associated clients", "wireless", "T1669", "LOW",
                    requires_root=True, tool="airodump-ng"),
            Payload(f"kismet -c {mon}",
                    "Passive wireless survey / rogue-AP and IDS-style detection", "wireless", "T1669", "LOW",
                    requires_root=True, tool="kismet"),
            Payload(f"wash -i {mon}",
                    "Identify WPS-enabled access points in range", "wireless", "T1595", "LOW",
                    requires_root=True, tool="wash (reaver-suite)"),
            Payload(f"bluetoothctl scan on",
                    "Nearby Bluetooth/BLE device discovery", "wireless", "T1595", "LOW", tool="bluetoothctl"),

            # --- Targeted capture (medium risk — sends packets) ---
            Payload(f"airodump-ng --bssid {t} {chan}-w wireless_capture {mon}",
                    "Targeted capture on one AP — collects WPA/WPA2 4-way handshakes", "wireless", "T1040", "MEDIUM",
                    requires_root=True, tool="airodump-ng"),
            Payload(f"hcxdumptool -i {mon} -o wireless_capture.pcapng --enable_status=1",
                    "PMKID + handshake capture (no client deauth required)", "wireless", "T1040", "MEDIUM",
                    requires_root=True, tool="hcxdumptool"),
            Payload(f"aireplay-ng --deauth 10 -a {t} {mon}",
                    "Deauthenticate connected clients to force a fresh handshake capture", "wireless", "T1557.004", "HIGH",
                    requires_root=True, tool="aireplay-ng"),
            Payload(f"hostapd /etc/jakal/wireless_evil_twin.conf",
                    "Stand up an authorized rogue AP (evil twin) to validate client/EDR detection", "wireless", "T1557.004", "HIGH",
                    requires_root=True, tool="hostapd"),
            Payload(f"bettercap -iface {interface} -eval 'wifi.recon on'",
                    "Wireless recon + AiTM framework against in-scope clients", "wireless", "T1557", "MEDIUM",
                    requires_root=True, tool="bettercap"),

            # --- Credential attack (post-capture, offline unless noted) ---
            Payload(f"reaver -i {mon} -b {t} -vv",
                    "WPS PIN brute-force attack against target AP", "wireless", "T1110", "HIGH",
                    requires_root=True, tool="reaver"),
            Payload(f"bully -b {t} {chan}{mon}",
                    "Alternate WPS PIN brute-force implementation", "wireless", "T1110", "HIGH",
                    requires_root=True, tool="bully"),
            Payload(f"aircrack-ng -w {wordlist} -b {t} wireless_capture-01.cap",
                    "Offline dictionary crack of captured WPA/WPA2 handshake", "wireless", "T1110.002", "MEDIUM",
                    tool="aircrack-ng"),
            Payload(f"hcxpcapngtool -o wireless_hashes.22000 wireless_capture.pcapng",
                    "Convert captured PMKID/handshake to hashcat format", "wireless", "T1040", "LOW",
                    tool="hcxtools"),
            Payload(f"hashcat -m 22000 wireless_hashes.22000 {wordlist}",
                    "GPU-accelerated crack of converted PMKID/handshake hash", "wireless", "T1110.002", "MEDIUM",
                    tool="hashcat"),
        ]

    # ------------------------------------------------------------------
    # Phase 7: Cleanup / Evidence Collection
    # ------------------------------------------------------------------

    def cleanup_and_evidence(self, target: str) -> List[Payload]:
        """Post-assessment cleanup verification and evidence collection."""
        t = _validate_target(target)
        return [
            Payload(f"ls -la /tmp | grep -E 'jakal|pentest|scan'",
                    "Verify no scanner artifacts left in /tmp", "cleanup", "", "LOW", tool="shell"),
            Payload(f"find /var/log -newer /tmp/scan_start_marker -name '*.log' | head -20",
                    "Log entries created during assessment window", "cleanup", "", "LOW", tool="shell"),
            Payload(f"diff <(sort /etc/passwd) <(sort /tmp/baseline_passwd)",
                    "User account diff vs baseline", "cleanup", "", "LOW", tool="shell"),
            Payload(f"ss -tlnp | diff - /tmp/baseline_ports",
                    "Port state diff vs pre-assessment baseline", "cleanup", "", "LOW", tool="shell"),
            Payload(f"sha256sum /tmp/evidence/* > /tmp/evidence.sha256",
                    "SHA-256 hash all evidence files for chain of custody", "cleanup", "", "LOW", tool="shell"),
            Payload(f"tar -czf evidence_{t}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.tar.gz /tmp/evidence/",
                    "Package evidence archive", "cleanup", "", "LOW", tool="tar"),
        ]

    # ------------------------------------------------------------------
    # Master: generate all phases for a target
    # ------------------------------------------------------------------

    def generate_phase(self, phase: str, target: str, **kwargs) -> List[Dict[str, Any]]:
        """
        Generate payloads for a specific phase.

        Args:
            phase: one of recon_passive, recon_active, enumeration,
                   web, vuln_analysis, post_exploit, crypto_analysis, cleanup
            target: validated target IP / hostname / CIDR
            **kwargs: passed to the phase-specific generator

        Returns:
            List of payload dicts.
        """
        phase_map = {
            "recon_passive":  self.recon_passive,
            "recon_active":   self.recon_active,
            "enumeration":    self.enumeration,
            "web":            self.web_application,
            "web_application": self.web_application,     # alias — cheatsheet/AIP phase vocabulary
            "vuln_analysis":  self.vulnerability_analysis,
            "vulnerability_analysis": self.vulnerability_analysis,  # alias
            "post_exploit":   self.post_exploitation_assessment,
            "post_exploitation_assessment": self.post_exploitation_assessment,  # alias
            "crypto_analysis": self.encryption_analysis,
            "encryption_analysis": self.encryption_analysis,  # alias
            "wireless":       self.wireless,
            "cleanup":        self.cleanup_and_evidence,
        }
        # NOTE: the aliases above fix a real bug — AIPPayloadGenerator.generate_engagement()
        # (backend/payloads/aip_payload_generator.py) iterates phases named
        # "web_application" / "vulnerability_analysis" / "post_exploitation_assessment" /
        # "encryption_analysis" (the cheatsheet-ontology vocabulary), but this map
        # previously only recognized the short forms ("web", "vuln_analysis", ...).
        # Every engagement plan for those four phases was silently falling back to
        # mitre=[] (caught by the try/except in AIPPayloadGenerator.generate()) and
        # serving cheatsheet-only results — the exact "cheatsheet-only fallback"
        # problem reported for the wireless phase was already happening on 4 of the
        # 7 default engagement phases before this fix.
        fn = phase_map.get(phase)
        if fn is None:
            raise ValueError(f"Unknown phase '{phase}'. Valid: {list(phase_map)}")
        return [p.to_dict() for p in fn(target, **kwargs)]

    def generate_full_engagement(self, target: str, domain: str = "", open_ports: Optional[List[int]] = None) -> Dict[str, Any]:
        """
        Generate a complete engagement payload set for an authorized target.
        Returns a structured dict grouped by phase.
        """
        t = _validate_target(target)
        return {
            "target":       t,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "phases": {
                "recon_passive":   [p.to_dict() for p in self.recon_passive(t, domain=domain)],
                "recon_active":    [p.to_dict() for p in self.recon_active(t)],
                "enumeration":     [p.to_dict() for p in self.enumeration(t, ports=open_ports)],
                "web":             [p.to_dict() for p in self.web_application(t)],
                "vuln_analysis":   [p.to_dict() for p in self.vulnerability_analysis(t)],
                "crypto_analysis": [p.to_dict() for p in self.encryption_analysis(t)],
                "cleanup":         [p.to_dict() for p in self.cleanup_and_evidence(t)],
            },
            "total_payloads": sum(
                len([p.to_dict() for p in fn(t)])
                for fn in [self.recon_passive, self.recon_active, self.enumeration,
                           self.web_application, self.vulnerability_analysis,
                           self.encryption_analysis, self.cleanup_and_evidence]
            )
        }
