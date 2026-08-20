import nmap
import os

def scan_subnet(subnet_range):
    """
    Perform a port scan on a target subnet and save the results for each live host in a separate file, including services.

    Args:
        subnet_range (str): The subnet to scan (e.g., "192.168.1.0/24").
    """
    # Initialize the Nmap scanner
    nm = nmap.PortScanner()

    print(f"Scanning subnet: {subnet_range}")
    
    # Scan the subnet for live hosts
    nm.scan(hosts=subnet_range, arguments='-sn')
    live_hosts = [host for host in nm.all_hosts() if nm[host].state() == 'up']

    print(f"Found {len(live_hosts)} live hosts.")
    
    # Perform port scans on each live host
    for host in live_hosts:
        print(f"Scanning ports for host: {host}")
        nm.scan(host, arguments='-sS -sV')  # -sV for service version detection

        # Save the results in a file named after the host's IP address
        file_name = f"{host}.txt"
        with open(file_name, 'w') as file:
            file.write(f"Scan results for {host}:\n")
            file.write("-" * 40 + "\n")
            for proto in nm[host].all_protocols():
                ports = nm[host][proto].keys()
                for port in sorted(ports):
                    state = nm[host][proto][port]['state']
                    service = nm[host][proto][port].get('name', 'unknown')
                    file.write(f"Port {port}/{proto} is {state} (Service: {service})\n")
        
        print(f"Results saved to {file_name}")

if __name__ == "__main__":
    # Specify the subnet range to scan
    subnet_range = input("Enter the subnet range (e.g., 192.168.1.0/24): ")
    scan_subnet(subnet_range)