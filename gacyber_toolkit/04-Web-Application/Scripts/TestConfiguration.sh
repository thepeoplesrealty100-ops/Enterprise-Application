#!/bin/bash

# Prompt for target URL
read -p "Enter the target URL (e.g., http://www.luxurytreats.com): " target_url

# Create output file
output_file="WebApp_Test_Results.txt"
echo "Web Application Testing Results for: $target_url" > $output_file

echo "=====================================" >> $output_file

# Test Platform Configuration using Nikto
echo "[1] Platform Configuration Test (Nikto)" >> $output_file
nikto -h $target_url >> $output_file 2>&1

echo "=====================================" >> $output_file

# Test Handling of File Extensions for Sensitive Information using Nikto
echo "[2] File Extensions Test for Sensitive Information (Nikto)" >> $output_file
nikto -h $target_url -Tuning x 6 >> $output_file 2>&1

echo "=====================================" >> $output_file

# Discover Old Backups and Unreferenced Files using Gobuster
echo "[3] Old Backups and Unreferenced Files Discovery (Gobuster)" >> $output_file
gobuster dir -u $target_url -w /usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt >> $output_file 2>&1

echo "=====================================" >> $output_file

# Completion message
echo "Testing complete. Results saved in: $output_file"
