#!/bin/bash

# Prompt for the target website
read -p "Enter the target website: " target

# Create a directory to store the results
mkdir -p DNS_Interrogation_Results

# Perform whois lookup using nmap script
echo "Performing whois lookup..."
nmap -sn --script whois-* $target > DNS_Interrogation_Results/whois.txt

# Collect DNS records using dnsenum
echo "Collecting DNS records..."
dnsrecon -d $target > DNS_Interrogation_Results/dns_records.txt

echo "All tasks completed. Results are saved in the DNS_Interrogation_Results' directory."

