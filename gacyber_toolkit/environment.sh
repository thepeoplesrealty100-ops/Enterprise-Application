#!/bin/bash
# GACyber Tool Kit — Environment Health Check

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "═══════════════════════════════"
echo "   GACYBER ENVIRONMENT CHECK"
echo "═══════════════════════════════"

chk() { [ -e "$1" ] && echo "[OK] $2" || echo "[FAIL] $2 — missing: $1"; }

chk "$BASE_DIR/toolkit.py"                               "Main launcher (toolkit.py)"
chk "$BASE_DIR/toolkit.sh"                               "Bash launcher (toolkit.sh)"
chk "$BASE_DIR/01-Reconnaissance/OSINT/Attack_Surface_Mapping.py"  "Recon scripts"
chk "$BASE_DIR/04-Web-Application/Scripts/Web_Spidering.py"         "Web-App scripts"
chk "$BASE_DIR/07-Post-Exploitation/Linux/Linux_Enumeration.sh"     "Post-exploit scripts"
chk "$BASE_DIR/CheatSheets/nmap_ref.txt"                 "Nmap cheatsheet"
chk "$BASE_DIR/CheatSheets/shodan_ref.txt"               "Shodan cheatsheet"
chk "$BASE_DIR/Resources/Wordlists/directories.txt"      "Wordlist: directories"
chk "$BASE_DIR/Resources/Wordlists/subdomains.txt"       "Wordlist: subdomains"
chk "$BASE_DIR/Resources/Wordlists/common_passwords.txt" "Wordlist: passwords"
chk "$HOME/Documents/Pentest_Projects" 2>/dev/null || true

echo ""
for cmd in python3 nmap whois; do
    which $cmd &>/dev/null && echo "[OK] $cmd in PATH" || echo "[WARN] $cmd not found in PATH"
done
echo "═══════════════════════════════"
