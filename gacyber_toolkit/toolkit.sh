#!/bin/bash
# GACyber Tool Kit — Bash Launcher (Kali / WSL)
# Requires: nmap, hydra, whois in PATH
# Usage: bash toolkit.sh

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECTS_ROOT="$HOME/Documents/Pentest_Projects"

# Project init
read -p "Target Name   : " TARGET
read -p "Target IP/CIDR: " TARGET_IP
DATE_STR=$(date +%Y%m%d)
PROJ_ROOT="$PROJECTS_ROOT/${DATE_STR}_${TARGET}"

mkdir -p "$PROJ_ROOT"/{01-Reconnaissance/{OSINT,Shodan,DNS},02-Scanning/{Nmap,Hping3,Sn1per},03-Enumeration/Web,04-Web-Application/Findings,05-Wireless,06-Exploitation,07-Post-Exploitation/{Linux,Windows,IoT},08-Reporting,Resources/{Wordlists,Targets},CheatSheets}

# Seed google dork file
cat > "$PROJ_ROOT/01-Reconnaissance/OSINT/google_dorks.txt" << GDORK
site:$TARGET intitle:"index of" FTP
site:$TARGET ext:xml | ext:conf | ext:env | ext:bak
site:$TARGET inurl:login | inurl:admin | inurl:dashboard
intext:"@$TARGET" filetype:xls | filetype:csv
GDORK

echo -e "\n[+] Project created: $PROJ_ROOT\n"

tool_menu() {
    echo -e "\n══════════════════════════════════════════════"
    echo "   GACyber Tool Kit — $TARGET ($TARGET_IP)"
    echo "══════════════════════════════════════════════"
    PS3="Select Phase: "
    options=(
        "01 Reconnaissance (WHOIS/DNS/OSINT)"
        "02 Scanning (Nmap/Hping3)"
        "03 Enumeration (Nikto/Gobuster)"
        "04 Web Application"
        "05 Wireless"
        "06 Exploitation (SQLMap/Hydra)"
        "07 Post-Exploitation"
        "08 Generate Report"
        "Exit"
    )
    select opt in "${options[@]}"; do
        case $opt in
            "01 Reconnaissance (WHOIS/DNS/Shodan)")
                whois $TARGET_IP > "$PROJ_ROOT/01-Reconnaissance/OSINT/whois.txt"
                echo "[+] WHOIS saved."
                bash "$BASE_DIR/01-Reconnaissance/DNS/DNS_Interrogation.sh" ;;
            "02 Scanning (Nmap/Hping3)")
                nmap -T4 -A -oA "$PROJ_ROOT/02-Scanning/Nmap/aggressive" $TARGET_IP
                echo "[+] Scan saved to $PROJ_ROOT/02-Scanning/Nmap/" ;;
            "03 Enumeration (Nikto/Gobuster)")
                nikto -h $TARGET | tee "$PROJ_ROOT/03-Enumeration/Web/nikto.txt"
                gobuster dir -u "http://$TARGET" -w "$BASE_DIR/Resources/Wordlists/directories.txt" | tee "$PROJ_ROOT/03-Enumeration/Web/gobuster.txt" ;;
            "04 Web Application")
                python3 "$BASE_DIR/04-Web-Application/Scripts/Website_Footprinting.py"
                python3 "$BASE_DIR/04-Web-Application/Scripts/Web_Vulnerability_Scanning.py" ;;
            "05 Wireless")
                echo "See: $BASE_DIR/CheatSheets/aircrack_ng_ref.txt"
                cat "$BASE_DIR/CheatSheets/aircrack_ng_ref.txt" | head -30 ;;
            "06 Exploitation (SQLMap/Hydra)")
                read -p "  URL for SQLMap: " URL
                sqlmap -u "$URL" --batch --output-dir="$PROJ_ROOT/06-Exploitation/"
                ;;
            "07 Post-Exploitation")
                bash "$BASE_DIR/07-Post-Exploitation/Linux/Linux_Enumeration.sh" ;;
            "08 Generate Report")
                REPORT="$PROJ_ROOT/08-Reporting/${DATE_STR}_${TARGET}_report.md"
                cat > "$REPORT" << REOF
# Penetration Test Report — $TARGET
Date: $(date)
Tester:
Client:
RoE Reference:

## Executive Summary

## Scope
In-scope: $TARGET_IP

## Findings
### Critical
### High
### Medium
### Low

## Remediation

## Appendix
REOF
                echo "[+] Report template: $REPORT" ;;
            "Exit") exit ;;
        esac
    done
}

tool_menu
