import subprocess

def search_vulnerabilities(target):
    # Run the searchsploit command to find vulnerabilities related to the target
    result = subprocess.run(['searchsploit', target], capture_output=True, text=True)

    # Check for errors
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return

    # Save the results to a text file
    with open('Known_vulnerabilities.txt', 'w') as f:
        f.write(result.stdout)

    print("Vulnerability information has been saved to Known_vulnerabilities.txt")

if __name__ == "__main__":
    # Prompt the user for the target environment
    target = input("Enter the target environment (e.g., 'apache', 'wordpress'): ")
    search_vulnerabilities(target)
