# backend/tools/nmap_wrapper.py
import subprocess
import shlex
from tools.authorization import check_authorization_and_scope

def run_nmap(target: str, scan_type: str = "comprehensive", operator_id: str = "system") -> dict:
    check_authorization_and_scope(target, "nmap_scan", operator_id)
    
    # Safe, non-destructive flags only; expand under RoE
    cmd_map = {
        "comprehensive": f"nmap -sV -sC -O -T4 {shlex.quote(target)}",
        "quick": f"nmap -T4 -F {shlex.quote(target)}",
        "port_scan": f"nmap -p- -T4 {shlex.quote(target)}"
    }
    cmd = cmd_map.get(scan_type, cmd_map["quick"])
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
        return {
            "target": target,
            "scan_type": scan_type,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except Exception as e:
        return {"error": str(e)}
