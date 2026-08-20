from scapy.all import ARP, Ether, srp
import sys

def discover_live_hosts(subnet):
    """
    Discover live hosts in a given subnet using ARP requests.

    Args:
        subnet (str): The subnet to scan (e.g., "192.168.1.0/24").
    """
    print(f"Scanning subnet: {subnet}")

    # Create an ARP request for the subnet
    arp_request = ARP(pdst=subnet)
    broadcast = Ether(dst="ff:ff:ff:ff:ff:ff")
    arp_request_broadcast = broadcast / arp_request

    # Send the ARP request and collect responses
    answered, unanswered = srp(arp_request_broadcast, timeout=2, verbose=False)

    print("\nLive Hosts:")
    print("IP Address\t\tMAC Address")
    print("-" * 40)

    # Parse the responses and display results
    for sent, received in answered:
        print(f"{received.psrc}\t\t{received.hwsrc}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 live_hosts_discovery.py <subnet>")
        print("Example: python3 live_hosts_discovery.py 192.168.1.0/24")
        sys.exit(1)

    subnet_to_scan = sys.argv[1]
    discover_live_hosts(subnet_to_scan)