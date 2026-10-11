"""
seed_real_machine_data.py — Populate device inventory with real machine metrics
Scanned from Windows system to seed JAKAL fleet with actual baseline data
"""
import json
import platform
import uuid
from datetime import datetime, timezone
from database import DuckDBManager

def get_machine_info():
    """Gather real machine information"""
    try:
        import psutil
    except ImportError:
        print("WARNING: psutil not installed. Using mock data.")
        return None
    
    try:
        # Get CPU info
        cpu_count = psutil.cpu_count(logical=True)
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # Get memory info
        mem = psutil.virtual_memory()
        memory_percent = mem.percent
        memory_total_gb = mem.total / (1024**3)
        memory_used_gb = mem.used / (1024**3)
        
        # Get disk info
        disk = psutil.disk_usage('C:' if platform.system() == 'Windows' else '/')
        disk_percent = disk.percent
        disk_total_gb = disk.total / (1024**3)
        disk_free_gb = disk.free / (1024**3)
        
        # Get network info
        net_if_addrs = psutil.net_if_addrs()
        ips = []
        for interface, addrs in net_if_addrs.items():
            for addr in addrs:
                if addr.family.name == 'AF_INET':
                    ips.append(addr.address)
        
        return {
            'os': platform.system(),
            'os_version': platform.release(),
            'hostname': platform.node(),
            'machine': platform.machine(),
            'processor': platform.processor(),
            'cpu_cores': cpu_count,
            'cpu_percent': cpu_percent,
            'memory_total_gb': memory_total_gb,
            'memory_used_gb': memory_used_gb,
            'memory_percent': memory_percent,
            'disk_total_gb': disk_total_gb,
            'disk_free_gb': disk_free_gb,
            'disk_percent': disk_percent,
            'ipv4_addresses': ips,
            'boot_time': datetime.fromtimestamp(psutil.boot_time()).isoformat(),
        }
    except Exception as e:
        print(f"Error gathering system info: {e}")
        return None


def seed_real_device(db: DuckDBManager):
    """Insert real machine as a device in the fleet"""
    try:
        machine_info = get_machine_info()
        if not machine_info:
            print("Could not gather machine info, using mock data")
            machine_info = {
                'os': 'Windows',
                'os_version': '10 Pro',
                'hostname': 'WORKSTATION-01',
                'machine': 'x86_64',
                'processor': 'Intel(R) Core(TM) i7-6700',
                'cpu_cores': 8,
                'cpu_percent': 15.0,
                'memory_total_gb': 16.0,
                'memory_used_gb': 12.5,
                'memory_percent': 78.1,
                'disk_total_gb': 238.0,
                'disk_free_gb': 9.0,
                'disk_percent': 96.2,
                'ipv4_addresses': ['192.168.1.100'],
                'boot_time': '2026-09-20T08:15:00Z',
            }
        
        device_id = f"DEV-REAL-{uuid.uuid4().hex[:6].upper()}"
        hostname = machine_info.get('hostname', 'UNKNOWN-HOST')
        os_name = machine_info.get('os', 'Unknown')
        os_version = machine_info.get('os_version', '')
        
        # Determine health status based on metrics
        cpu_percent = machine_info.get('cpu_percent', 0)
        mem_percent = machine_info.get('memory_percent', 0)
        disk_percent = machine_info.get('disk_percent', 0)
        
        # Calculate risk score (0-100)
        risk_score = 0
        alerts = []
        
        if disk_percent > 95:
            risk_score += 35
            alerts.append("CRITICAL: Disk space critically low (>95%)")
        elif disk_percent > 80:
            risk_score += 15
            alerts.append("WARNING: Disk space low (>80%)")
        
        if mem_percent > 90:
            risk_score += 30
            alerts.append("CRITICAL: Memory usage very high (>90%)")
        elif mem_percent > 80:
            risk_score += 15
            alerts.append("WARNING: Memory usage high (>80%)")
        
        if cpu_percent > 85:
            risk_score += 20
            alerts.append("WARNING: CPU usage elevated (>85%)")
        
        # Determine overall device status
        status = "healthy"
        if risk_score >= 50:
            status = "critical"
        elif risk_score >= 25:
            status = "warning"
        
        # Insert into devices table
        db.conn.execute("""
            INSERT OR REPLACE INTO devices (
                device_id, name, os, os_version, status, ip_address,
                risk_score, cpu_cores, memory_gb, disk_gb,
                last_seen, source, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), 'seeded_local', 1)
        """, (
            device_id, hostname, os_name, os_version, status,
            machine_info.get('ipv4_addresses', ['127.0.0.1'])[0],
            risk_score,
            machine_info.get('cpu_cores', 4),
            round(machine_info.get('memory_total_gb', 8), 2),
            round(machine_info.get('disk_total_gb', 256), 2)
        ))
        
        # Insert real-time metrics
        db.conn.execute("""
            INSERT INTO device_health_metrics (device_id, timestamp, cpu_percent, memory_percent, disk_percent)
            VALUES (?, datetime('now'), ?, ?, ?)
        """, (device_id, round(cpu_percent, 1), round(mem_percent, 1), round(disk_percent, 1)))
        
        # Create baseline alerts for critical metrics
        for i, alert_msg in enumerate(alerts):
            severity = "CRITICAL" if "CRITICAL" in alert_msg else "WARNING"
            db.conn.execute("""
                INSERT INTO device_alerts (device_id, alert_type, severity, message, created_at, acknowledged)
                VALUES (?, 'resource_utilization', ?, ?, datetime('now'), 0)
            """, (device_id, severity, alert_msg))
        
        db.conn.commit()
        
        print(f"\n✓ Seeded real device into fleet:")
        print(f"  Device ID: {device_id}")
        print(f"  Hostname: {hostname}")
        print(f"  OS: {os_name} {os_version}")
        print(f"  Status: {status.upper()}")
        print(f"  Risk Score: {risk_score}/100")
        print(f"  CPU Cores: {machine_info.get('cpu_cores', 'N/A')}")
        print(f"  Memory: {machine_info.get('memory_used_gb', 0):.1f}GB / {machine_info.get('memory_total_gb', 8):.1f}GB ({mem_percent:.1f}%)")
        print(f"  Disk: {machine_info.get('disk_free_gb', 0):.1f}GB free ({disk_percent:.1f}% used)")
        print(f"  Alerts Created: {len(alerts)}")
        for alert in alerts:
            print(f"    - {alert}")
        
        return device_id
        
    except Exception as e:
        print(f"Error seeding real device data: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    print("TIER 1.3: Seeding Real Machine Data")
    print("=" * 60)
    
    try:
        db = DuckDBManager()
        device_id = seed_real_device(db)
        if device_id:
            print(f"\n✓ Machine data seeding complete!")
            print(f"  Device available as: {device_id}")
        else:
            print("✗ Failed to seed machine data")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
