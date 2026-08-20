import subprocess

def run_nmap_scan(target, scan_type):
    result = subprocess.run(['nmap', scan_type, target], capture_output=True, text=True)
    return result.stdout

def main():
    target = input("Enter the target URL or IP address: ")

    # Host Discovery
    icmp_ping_scan = run_nmap_scan(target, '-sn')
    arp_ping_scan = run_nmap_scan(target, '-PR')
    udp_ping_scan = run_nmap_scan(target, '-PU')
    tcp_ping_scan = run_nmap_scan(target, '-PS')

    # Port Scanning
    tcp_connect_scan = run_nmap_scan(target, '-sT')
    udp_scan = run_nmap_scan(target, '-sU')
    half_open_scan = run_nmap_scan(target, '-sS')
    xmas_scan = run_nmap_scan(target, '-sX')
    sctp_init_scan = run_nmap_scan(target, '-sY')

    # Service Version Discovery
    service_version_discovery = run_nmap_scan(target, '-sV')

    # Save results to a file
    with open('Scan_Results.txt', 'w') as f:
        f.write("Host Discovery:\n")
        f.write("ICMP Ping Scan:\n" + icmp_ping_scan + "\n")
        f.write("ARP Ping Scan:\n" + arp_ping_scan + "\n")
        f.write("UDP Ping Scan:\n" + udp_ping_scan + "\n")
        f.write("TCP Ping Scan:\n" + tcp_ping_scan + "\n")
        
        f.write("\nPort Scanning:\n")
        f.write("TCP Connect Scan:\n" + tcp_connect_scan + "\n")
        f.write("UDP Scan:\n" + udp_scan + "\n")
        f.write("Half-Open Scan:\n" + half_open_scan + "\n")
        f.write("Xmas Scan:\n" + xmas_scan + "\n")
        f.write("SCTP INIT Scan:\n" + sctp_init_scan + "\n")
        
        f.write("\nService Version Discovery:\n" + service_version_discovery + "\n")

if __name__ == "__main__":
    main()