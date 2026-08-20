import nmap
from prettytable import PrettyTable

def discover_os_and_services(target_ip):
    """Perform OS and service version discovery on the target host."""
    nm = nmap.PortScanner()

    print(f"\n[+] Scanning target: {target_ip} for OS and service discovery...\n")
    
    try:
        # OS Discovery
        print("[*] Detecting operating system...")
        nm.scan(target_ip, arguments='-O')  # -O flag for OS detection
        if 'osmatch' in nm[target_ip]:
            print("Operating System(s) Detected:")
            for os in nm[target_ip]['osmatch']:
                print(f"  - {os['name']} (Accuracy: {os['accuracy']}%)")
        else:
            print("  No OS information detected.")

        # Service Version Discovery
        print("\n[*] Detecting service versions on open ports...")
        nm.scan(target_ip, arguments='-sV')  # -sV flag for service version detection
        table = PrettyTable()
        table.field_names = ["Port", "Protocol", "Service", "Product", "Version"]
        if nm[target_ip].all_protocols():
            for protocol in nm[target_ip].all_protocols():
                ports = nm[target_ip][protocol].keys()
                for port in sorted(ports):
                    service = nm[target_ip][protocol][port]
                    table.add_row([
                        port,
                        protocol,
                        service['name'],
                        service.get('product', 'N/A'),
                        service.get('version', 'N/A')
                    ])
            print(table)
        else:
            print("  No services detected.")

    except Exception as e:
        print(f"[-] Error: {e}")

if __name__ == "__main__":
    target_ip = input("Enter the target IP address: ").strip()
    discover_os_and_services(target_ip)