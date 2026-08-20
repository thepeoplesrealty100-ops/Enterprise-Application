#!/usr/bin/env python3
"""
GACyber Tool Kit — Launcher
Penetration testing assistant integrated with the JAKAL security platform.
All network-facing actions require a signed Rules of Engagement scope entry.
"""

import os
import sys
import subprocess
import datetime
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECTS_ROOT = os.path.join(os.path.expanduser("~"), "Documents", "Pentest_Projects")

# ─── Utilities ────────────────────────────────────────────────────────────────

def run_cmd(cmd: str) -> None:
    """Execute a shell command and stream its output."""
    print(f"\n[!] Running: {cmd}\n{'─'*60}")
    subprocess.run(cmd, shell=True)

def run_py(relative_path: str, args: str = "") -> None:
    """Run a Python script relative to this toolkit's BASE_DIR."""
    full_path = os.path.abspath(os.path.join(BASE_DIR, relative_path))
    if not os.path.exists(full_path):
        print(f"[-] Script not found: {full_path}")
        return
    run_cmd(f'"{sys.executable}" "{full_path}" {args}')

def run_sh(relative_path: str) -> None:
    """Run a shell script relative to BASE_DIR (requires bash in PATH)."""
    full_path = os.path.abspath(os.path.join(BASE_DIR, relative_path))
    if not os.path.exists(full_path):
        print(f"[-] Script not found: {full_path}")
        return
    run_cmd(f"bash \"{full_path}\"")

def make_project(target: str, target_ip: str) -> str:
    """Create a timestamped project folder for the engagement."""
    date_str = datetime.date.today().strftime("%Y%m%d")
    proj_dir = os.path.join(PROJECTS_ROOT, f"{date_str}_{target}")
    subdirs = [
        "01-Reconnaissance/OSINT", "01-Reconnaissance/Shodan", "01-Reconnaissance/DNS",
        "02-Scanning/Nmap", "02-Scanning/Hping3", "02-Scanning/Sn1per",
        "03-Enumeration/Web", "03-Enumeration/Linux",
        "04-Web-Application/Findings",
        "05-Wireless",
        "06-Exploitation",
        "07-Post-Exploitation/Linux", "07-Post-Exploitation/Windows",
        "08-Reporting",
        "Resources/Wordlists", "Resources/Targets",
        "CheatSheets",
    ]
    for d in subdirs:
        os.makedirs(os.path.join(proj_dir, d), exist_ok=True)

    # Write scope stub
    scope_file = os.path.join(proj_dir, "Resources/Targets/scope.txt")
    with open(scope_file, "w") as f:
        f.write(f"# Engagement: {target}\n")
        f.write(f"# Date: {date_str}\n")
        f.write(f"# Target IP/Range: {target_ip}\n")
        f.write("# RoE reference: <path/to/signed-roe.pdf>\n")
        f.write("# Authorized window: <start> to <end>\n")
        f.write("# Emergency contact: \n")
        f.write(f"\nIn-scope:\n  {target_ip}\n\nExcluded:\n  # list any OOB subnets\n")

    # Write google dork seeds
    dork_file = os.path.join(proj_dir, "01-Reconnaissance/OSINT/google_dorks.txt")
    with open(dork_file, "w") as f:
        f.write(f"site:{target} intitle:\"index of\" FTP\n")
        f.write(f"site:{target} ext:xml | ext:conf | ext:env | ext:bak\n")
        f.write(f"site:{target} inurl:login | inurl:admin | inurl:dashboard\n")
        f.write(f"site:{target} \"powered by\" | \"Version\" | \"Copyright\"\n")
        f.write(f"intext:\"@{target}\" filetype:xls | filetype:csv\n")

    print(f"\n[+] Project created: {proj_dir}")
    return proj_dir

def header(title: str) -> None:
    print(f"\n{'═'*60}\n   {title}\n{'═'*60}")

# ─── Phase Menus ──────────────────────────────────────────────────────────────

def phase_recon(proj: str, target: str, ip: str) -> None:
    header("01 · RECONNAISSANCE & OSINT")
    print("  1. DNS Interrogation (dnsrecon + hostcheck)")
    print("  2. WHOIS + Google Dork Seeds")
    print("  3. Similar Domain Discovery")
    print("  4. theHarvester (email/subdomain harvest)")
    print("  5. Attack Surface Mapping")
    print("  6. Shodan Dorks (view reference)")
    print("  B. Back")
    c = input("\nSelect > ").strip().lower()
    out = os.path.join(proj, "01-Reconnaissance")
    if c == "1":
        run_sh("01-Reconnaissance/DNS/DNS_Interrogation.sh")
    elif c == "2":
        run_cmd(f"whois {ip} | tee \"{out}/OSINT/whois_{ip}.txt\"")
    elif c == "3":
        run_py("01-Reconnaissance/OSINT/Domains_SimilarDomainNames.py")
    elif c == "4":
        run_cmd(f"theHarvester -d {target} -l 500 -b all | tee \"{out}/OSINT/harvester_{target}.txt\"")
    elif c == "5":
        run_py("01-Reconnaissance/OSINT/Attack_Surface_Mapping.py")
    elif c == "6":
        print(open(os.path.join(BASE_DIR, "01-Reconnaissance/Shodan/shodan_dorks.txt")).read())

def phase_scan(proj: str, ip: str) -> None:
    header("02 · SCANNING")
    print("  1. Nmap Aggressive Full Scan")
    print("  2. Nmap Quick Port Scan")
    print("  3. Nmap Service/Version + OS Detection")
    print("  4. Discover Live Hosts (ICMP sweep)")
    print("  5. Port Scan (Python/socket)")
    print("  6. Hping3 SYN scan")
    print("  B. Back")
    c = input("\nSelect > ").strip().lower()
    out = os.path.join(proj, "02-Scanning/Nmap")
    if c == "1":
        run_cmd(f"nmap -T4 -A -v -oA \"{out}/aggressive_{ip}\" {ip}")
    elif c == "2":
        run_cmd(f"nmap -T4 --open -oA \"{out}/quick_{ip}\" {ip}")
    elif c == "3":
        run_py("02-Scanning/Nmap/OS_and_Service_Version_Discovery.py")
    elif c == "4":
        run_py("01-Reconnaissance/OSINT/Discover_Live_Hosts.py")
    elif c == "5":
        run_py("02-Scanning/Nmap/Port_Scanning.py")
    elif c == "6":
        run_cmd(f"hping3 -S --scan 1-65535 {ip}")

def phase_enum(proj: str, target: str) -> None:
    header("03 · ENUMERATION")
    print("  1. Web Spidering")
    print("  2. Directory Bruteforce (Gobuster)")
    print("  3. Server-Side Technology Fingerprint")
    print("  4. Load Balancer Detection")
    print("  5. Known Vulnerabilities Lookup")
    print("  6. Web Vulnerability Scan (Nikto)")
    print("  B. Back")
    c = input("\nSelect > ").strip().lower()
    wl = os.path.join(BASE_DIR, "Resources/Wordlists/directories.txt")
    if c == "1":
        run_py("04-Web-Application/Scripts/Web_Spidering.py")
    elif c == "2":
        run_cmd(f"gobuster dir -u https://{target} -w \"{wl}\" -t 50")
    elif c == "3":
        run_py("04-Web-Application/Scripts/server_side_technologies.py")
    elif c == "4":
        run_py("04-Web-Application/Scripts/Load_Balancers.py")
    elif c == "5":
        run_py("03-Enumeration/Web/Known_Vulnerbilites.py")
    elif c == "6":
        run_cmd(f"nikto -h {target}")

def phase_webapp(proj: str, target: str) -> None:
    header("04 · WEB APPLICATION PENETRATION")
    print("  1. Website Footprinting")
    print("  2. WAF Detection")
    print("  3. Web Server Banner Grab")
    print("  4. CRLF Injection Test")
    print("  5. Fuzz Testing")
    print("  6. Insecure Access Control Methods")
    print("  7. Reverse Tabnabbing Test")
    print("  8. Metadata & Hidden Content Scan")
    print("  9. SQLMap (automated SQLi)")
    print("  A. THC Hydra (brute force)")
    print("  B. Back")
    c = input("\nSelect > ").strip().lower()
    out = os.path.join(proj, "04-Web-Application/Findings")
    wl  = os.path.join(BASE_DIR, "Resources/Wordlists/common_passwords.txt")
    if c == "1":
        run_py("04-Web-Application/Scripts/Website_Footprinting.py")
    elif c == "2":
        run_sh("04-Web-Application/Scripts/WAF_Detection.sh")
    elif c == "3":
        run_sh("04-Web-Application/Scripts/Web_Server_Banner_Grabbing.sh")
    elif c == "4":
        run_py("04-Web-Application/Scripts/CRLF_Injection_Test.py")
    elif c == "5":
        run_py("04-Web-Application/Scripts/Fuzz_Testing.py")
    elif c == "6":
        run_py("04-Web-Application/Scripts/Insecure_Access_Control_Methods.py")
    elif c == "7":
        run_py("04-Web-Application/Scripts/Reverse_Tabnabbing_Test.py")
    elif c == "8":
        run_py("04-Web-Application/Scripts/Metadata_HiddenContent.py")
    elif c == "9":
        url = input("  Target URL: ")
        run_cmd(f"sqlmap -u \"{url}\" --batch --output-dir=\"{out}\"")
    elif c == "a":
        ip   = input("  Target IP: ")
        user = input("  Username: ")
        svc  = input("  Service (ssh/ftp/http): ")
        run_cmd(f"hydra -l {user} -P \"{wl}\" {ip} {svc}")

def phase_wireless(proj: str) -> None:
    header("05 · WIRELESS")
    print("  1. Aircrack-ng cheat sheet")
    print("  2. Reaver/Pixiewps WPS attack reference")
    print("  3. Wifiphisher reference")
    print("  4. Wireshark filter reference")
    print("  B. Back")
    c = input("\nSelect > ").strip().lower()
    sheets = os.path.join(BASE_DIR, "CheatSheets")
    if c == "1":
        print(open(os.path.join(sheets, "aircrack_ng_ref.txt")).read())
    elif c == "2":
        print(open(os.path.join(sheets, "reaver_ref.txt")).read())
    elif c == "3":
        print(open(os.path.join(sheets, "wifiphisher_ref.txt")).read())
    elif c == "4":
        print(open(os.path.join(sheets, "wireshark_filters.txt")).read())

def phase_post(proj: str, target_ip: str) -> None:
    header("07 · POST-EXPLOITATION")
    print("  1. Linux Enumeration")
    print("  2. Gain Access & Enumerate (Linux)")
    print("  3. Privilege Escalation (Linux)")
    print("  4. IoT Device Enumeration")
    print("  5. Windows Persistence Generator (SharPersist)")
    print("  6. DumpsterDiver reference")
    print("  B. Back")
    c = input("\nSelect > ").strip().lower()
    if c == "1":
        run_sh("07-Post-Exploitation/Linux/Linux_Enumeration.sh")
    elif c == "2":
        run_sh("07-Post-Exploitation/Linux/GainAccess_Enumerate.sh")
    elif c == "3":
        run_sh("07-Post-Exploitation/Linux/Privilege_Escalate.sh")
    elif c == "4":
        run_sh("07-Post-Exploitation/IoT/Enumerate_Device_Information.sh")
    elif c == "5":
        payload = input("  Payload path on target (e.g. C:\\Users\\Public\\shell.exe): ")
        name    = input("  Task/value name: ")
        print("\n  Persistence methods:")
        print("    1. Registry HKCU Run")
        print("    2. Scheduled Task (daily)")
        print("    3. Startup Folder LNK")
        m = input("  Select > ")
        cmds = {
            "1": f'SharPersist -t reg -c "{payload}" -k "hkcurun" -v "{name}" -m add',
            "2": f'SharPersist -t schtask -c "{payload}" -n "{name}" -m add -o daily',
            "3": f'SharPersist -t startupfolder -c "{payload}" -f "{name}.lnk" -m add',
        }
        if m in cmds:
            print(f"\n[!] Run on target Windows machine:\n{cmds[m]}")

def phase_report(proj: str, target: str) -> None:
    header("08 · REPORTING")
    date_str = datetime.date.today().strftime("%Y%m%d")
    report_path = os.path.join(proj, f"08-Reporting/{date_str}_{target}_pentest_report.md")
    with open(report_path, "w") as f:
        f.write(f"# Penetration Test Report — {target}\n\n")
        f.write(f"**Date:** {datetime.date.today()}\n")
        f.write("**Tester:**\n**Client:**\n**RoE Reference:**\n\n")
        f.write("## Executive Summary\n\n_High-level findings for non-technical stakeholders._\n\n")
        f.write("## Scope\n\n_In-scope assets tested. Reference signed RoE._\n\n")
        f.write("## Methodology\n\nPhases: Reconnaissance → Scanning → Enumeration → Exploitation → Post-Exploitation.\n\n")
        f.write("## Findings\n\n### Critical\n\n### High\n\n### Medium\n\n### Low\n\n### Informational\n\n")
        f.write("## Remediation Recommendations\n\n")
        f.write("## Appendix — Evidence\n\n_Attach screenshots, tool output logs._\n")
    print(f"\n[+] Report template created: {report_path}")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n" + "═"*60)
    print("   GACyber Tool Kit · Python", sys.version.split()[0])
    print("   Authorized use only — ensure signed RoE before testing")
    print("═"*60)

    target    = input("\nTarget Domain/Name : ").strip()
    target_ip = input("Target IP / Range  : ").strip()
    proj      = make_project(target, target_ip)

    PHASES = {
        "1": ("Reconnaissance & OSINT",    lambda: phase_recon(proj, target, target_ip)),
        "2": ("Scanning",                  lambda: phase_scan(proj, target_ip)),
        "3": ("Enumeration",               lambda: phase_enum(proj, target)),
        "4": ("Web Application Pentest",   lambda: phase_webapp(proj, target)),
        "5": ("Wireless",                  lambda: phase_wireless(proj)),
        "6": ("Post-Exploitation",         lambda: phase_post(proj, target_ip)),
        "7": ("Generate Report Template",  lambda: phase_report(proj, target)),
        "Q": ("Quit", None),
    }

    while True:
        header("MAIN MENU")
        for k, (label, _) in PHASES.items():
            print(f"  {k}. {label}")
        choice = input("\nSelect Phase > ").strip().upper()
        if choice == "Q":
            print("\n[*] Session closed. Output saved to:", proj)
            break
        elif choice in PHASES:
            _, fn = PHASES[choice]
            if fn:
                fn()
        else:
            print("[-] Invalid selection.")

if __name__ == "__main__":
    main()
