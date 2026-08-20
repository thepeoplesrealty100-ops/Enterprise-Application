import subprocess

# Ask the user for the target website URL
target_website = input("Enter the target website URL (e.g., http://www.example.com): ")

# Define the wordlist for directory brute forcing
wordlist = "/usr/share/wordlists/dirb/common.txt"

# Define the output file to save the gathered information
output_file = "Directory_bruteforce_results.txt"

# Run Gobuster command to perform directory brute forcing
command = ["gobuster", "dir", "-u", target_website, "-w", wordlist, "-o", output_file]

# Execute the command and wait for it to complete
subprocess.run(command)

print(f"Directory brute forcing scan completed. Results are saved in {output_file}.")