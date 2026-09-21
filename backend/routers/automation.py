"""
routers/automation.py — JAKAL RMM Automation & Orchestration

Centralized automation surface behind the "Automation & Orchestration" module:
  * Script Library   — raw executable scripts (PowerShell/Bash/Python/Lua),
                       organized by OS + category.
  * Playbooks        — conditional orchestration flows ("if X, run Y, notify Z").
  * Tasks            — scheduled / event-triggered jobs that push scripts/playbooks.
  * Template Gallery — read-only blueprint content packages to copy & customize.

Seeded with real, runnable starter content on first call (idempotent).
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/automation", tags=["Automation & Orchestration"])


def _db():
    from database import get_db_manager
    return get_db_manager()

def _now(): return datetime.now(timezone.utc)

def _rows(db, sql, p=()):
    r = db.conn.execute(sql, p); cols = [d[0] for d in (r.description or [])]
    return [dict(zip(cols, x)) for x in r.fetchall()]


_SCRIPTS = [
    ("scr_win_cache", "Clear-WindowsCache.ps1", "windows", "powershell", "maintenance",
     "Clear Windows temp + update cache", "Get-ChildItem 'C:\\Windows\\Temp' -Recurse | Remove-Item -Force -ErrorAction SilentlyContinue\nWrite-Output 'Windows cache cleared.'"),
    ("scr_win_defender", "Run-DefenderQuickScan.ps1", "windows", "powershell", "security",
     "Trigger a Defender quick scan", "Start-MpScan -ScanType QuickScan\nGet-MpThreatDetection | Format-Table"),
    ("scr_win_patch", "Install-WindowsUpdates.ps1", "windows", "powershell", "patch",
     "Install pending Windows updates", "Install-Module PSWindowsUpdate -Force\nGet-WindowsUpdate -Install -AcceptAll -AutoReboot:$false"),
    ("scr_nix_update", "apt-security-updates.sh", "linux", "bash", "patch",
     "Apply security updates (Debian/Ubuntu)", "#!/usr/bin/env bash\nsudo apt-get update -y\nsudo apt-get upgrade -y --only-upgrade\necho 'Security updates applied.'"),
    ("scr_nix_hardening", "cis-quickcheck.sh", "linux", "bash", "compliance",
     "CIS quick hardening check", "#!/usr/bin/env bash\necho 'SSH root login:'; grep -i permitrootlogin /etc/ssh/sshd_config\necho 'World-writable files:'; find / -xdev -type f -perm -0002 2>/dev/null | head"),
    ("scr_nix_isolate", "net-isolate.sh", "linux", "bash", "response",
     "Isolate host (preserve mgmt channel)", "#!/usr/bin/env bash\nsudo iptables -I INPUT ! -s 10.0.0.0/8 -j DROP\nsudo iptables -I OUTPUT ! -d 10.0.0.0/8 -j DROP\necho 'Host isolated; mgmt subnet preserved.'"),
    ("scr_mac_inventory", "mac-software-inventory.sh", "macos", "bash", "inventory",
     "Collect installed app inventory (macOS)", "#!/usr/bin/env bash\nsystem_profiler SPApplicationsDataType -json"),
    ("scr_x_prockill", "kill-process-tree.py", "cross", "python", "response",
     "Kill a process tree by PID", "import sys,os,signal\npid=int(sys.argv[1])\nos.kill(pid, signal.SIGTERM)\nprint(f'Terminated {pid}')"),
]
_PLAYBOOKS = [
    ("pb_c2", "Malicious IP → Contain", "threat_intel.verdict==malicious",
     ["enrich (threat-intel)", "if malicious: isolate host (approval)", "open ticket", "notify #soc"], "high"),
    ("pb_ransom", "Ransomware Detected → Response", "edr.signal==ransomware",
     ["kill process tree", "isolate host", "snapshot forensic bundle", "page on-call"], "critical"),
    ("pb_patch", "Critical CVE → Emergency Patch", "vuln.cvss>=9.0",
     ["scan CVE (OSV/NVD)", "stage patch (approval)", "deploy in maintenance window", "verify"], "high"),
    ("pb_phish", "Phishing Failure → Enroll", "awareness.sim_failed==true",
     ["auto-enroll training", "force password reset", "notify manager"], "medium"),
]
_TASKS = [
    ("tsk_nightly_patch", "Nightly Security Patch", "cron: 0 2 * * *", "scr_nix_update", "linux servers", "enabled"),
    ("tsk_daily_defender", "Daily Defender Scan", "cron: 0 6 * * *", "scr_win_defender", "windows fleet", "enabled"),
    ("tsk_drift", "Continuous Drift Check", "event: config_change", "scr_nix_hardening", "all", "enabled"),
    ("tsk_weekly_inv", "Weekly Inventory Sweep", "cron: 0 3 * * 0", "scr_mac_inventory", "macos fleet", "paused"),
]
_TEMPLATES = [
    ("tpl_win_baseline", "Windows Secure Baseline", "windows", "Defender + Firewall + BitLocker + update policy blueprint"),
    ("tpl_nix_cis", "Linux CIS Level 1", "linux", "CIS Level 1 hardening content package"),
    ("tpl_msp_onboard", "MSP Client Onboarding", "cross", "New-tenant kit: agents, scopes, RBAC, backup, monitoring"),
    ("tpl_ir", "Incident Response Kit", "cross", "IR playbooks + isolation + forensic collection blueprints"),
]


def _ensure_seed(db):
    c = db.conn
    c.execute("""CREATE TABLE IF NOT EXISTS auto_scripts (id TEXT PRIMARY KEY, name TEXT, os TEXT, lang TEXT, category TEXT, description TEXT, body TEXT, updated_at TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS auto_playbooks (id TEXT PRIMARY KEY, name TEXT, trigger TEXT, steps TEXT, risk TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS auto_tasks (id TEXT PRIMARY KEY, name TEXT, schedule TEXT, script_id TEXT, targets TEXT, status TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS auto_templates (id TEXT PRIMARY KEY, name TEXT, os TEXT, description TEXT)""")
    if not _rows(db, "SELECT id FROM auto_scripts LIMIT 1"):
        for s in _SCRIPTS:
            c.execute("INSERT INTO auto_scripts VALUES (?,?,?,?,?,?,?,?)", (*s, _now()))
        for p in _PLAYBOOKS:
            c.execute("INSERT INTO auto_playbooks VALUES (?,?,?,?,?)", (p[0], p[1], p[2], json.dumps(p[3]), p[4]))
        for t in _TASKS:
            c.execute("INSERT INTO auto_tasks VALUES (?,?,?,?,?,?)", t)
        for t in _TEMPLATES:
            c.execute("INSERT INTO auto_templates VALUES (?,?,?,?)", t)
        c.commit()


def get_script_body(db, script_id: str):
    _ensure_seed(db)
    r = _rows(db, "SELECT name,lang,body FROM auto_scripts WHERE id=?", (script_id,))
    if r:
        return {"name": r[0]["name"], "shell": r[0]["lang"], "body": r[0]["body"]}
    return None


@router.get("/scripts")
async def scripts(os: Optional[str] = None, category: Optional[str] = None):
    db = _db(); _ensure_seed(db)
    q = "SELECT id,name,os,lang,category,description FROM auto_scripts"; w = []; p = []
    if os: w.append("os=?"); p.append(os)
    if category: w.append("category=?"); p.append(category)
    if w: q += " WHERE " + " AND ".join(w)
    return {"scripts": _rows(db, q + " ORDER BY os,name", tuple(p))}


@router.get("/scripts/{sid}")
async def script_detail(sid: str):
    db = _db(); _ensure_seed(db)
    r = _rows(db, "SELECT * FROM auto_scripts WHERE id=?", (sid,))
    return r[0] if r else {"error": "not found"}


@router.get("/playbooks")
async def playbooks():
    db = _db(); _ensure_seed(db)
    rows = _rows(db, "SELECT * FROM auto_playbooks")
    for r in rows:
        try: r["steps"] = json.loads(r.get("steps") or "[]")
        except Exception: r["steps"] = []
    return {"playbooks": rows}


@router.get("/tasks")
async def tasks():
    db = _db(); _ensure_seed(db)
    return {"tasks": _rows(db, "SELECT * FROM auto_tasks")}


class TaskToggle(BaseModel):
    status: str

@router.post("/tasks/{tid}/toggle")
async def toggle_task(tid: str, req: TaskToggle):
    db = _db(); _ensure_seed(db)
    db.conn.execute("UPDATE auto_tasks SET status=? WHERE id=?", (req.status, tid)); db.conn.commit()
    return {"ok": True, "id": tid, "status": req.status}


@router.get("/templates")
async def templates():
    db = _db(); _ensure_seed(db)
    return {"templates": _rows(db, "SELECT * FROM auto_templates")}
