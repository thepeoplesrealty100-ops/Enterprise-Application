import subprocess

# Function to gather subdomains using Nmap's dns-brute script
def gather_subdomains_nmap(domain):
    output_file = f"{domain}_subdomains_nmap.txt"
    print(f"Running Nmap dns-brute script to gather subdomains for {domain}...")
    
    try:
        # Run the Nmap dns-brute script and save output to a file
        result = subprocess.run(['nmap', '--script', 'dns-brute', '-v', domain], stdout=subprocess.PIPE, check=True)
        with open(output_file, 'w') as f:
            f.write(result.stdout.decode('utf-8'))
        print(f"Nmap dns-brute results saved to {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"Error running Nmap dns-brute: {e}")
    
    return output_file

# Function to find similar or parallel domain names using URLCrazy
def find_similar_domains(domain):
    output_file = f"{domain}_similar_domains_urlcrazy.txt"
    print(f"Running URLCrazy to find typosquatting and similar domains for {domain}...")

    try:
        # Run URLCrazy and redirect output to a file without printing it to the terminal
        with open(output_file, 'w') as f:
            subprocess.run(['urlcrazy', domain], stdout=f, stderr=subprocess.DEVNULL, check=True)
        print(f"URLCrazy results saved to {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"Error running URLCrazy: {e}")

    return output_file

# Main function to execute the domain extraction process
def main():
    domain = input("Enter the target domain (e.g., example.com): ").strip()

    # Check if the required tools are installed
    required_tools = ['nmap', 'urlcrazy']
    for tool in required_tools:
        if subprocess.run(['which', tool], stdout=subprocess.PIPE).returncode != 0:
            print(f"{tool} is not installed. Please install it first.")
            return

    # Gather subdomains using Nmap's dns-brute script
    gather_subdomains_nmap(domain)

    # Find similar domains using URLCrazy
    find_similar_domains(domain)

    # Final message after task completion
    print(f"Process completed for {domain}. Check the output files for the results.")

if __name__ == "__main__":
    main()
