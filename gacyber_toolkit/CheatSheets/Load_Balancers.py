import socket
from urllib.parse import urlparse

def check_load_balancer(domain):
    try:
        # Get all IP addresses linked to the domain
        ip_addresses = socket.gethostbyname_ex(domain)[2]
        
        # Check if there are multiple IP addresses
        if len(ip_addresses) > 1:
            print(f"Load balancing detected: {len(ip_addresses)} IP addresses found.")
            print(f"IP addresses: {ip_addresses}")
        else:
            print("No load balancing detected: Only one IP address found.")

    except socket.gaierror:
        print("Invalid domain name provided.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    target_url = input("Enter the domain to check (e.g., example.com): ")
    domain = urlparse(target_url).netloc or target_url  # Extract the domain from the URL
    check_load_balancer(domain)