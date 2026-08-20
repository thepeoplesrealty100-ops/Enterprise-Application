#!/bin/bash

# Prompt for target URL
read -p "Enter the target URL (e.g., http://www.luxurytreats.com): " target_url

# Extract domain name (remove protocol)
domain=$(echo "$target_url" | sed -E 's#https?://##')

# Output file
output_file="Transport_Layer_Security_Results.txt"
echo "Transport Layer Security Testing Results for: $domain" > $output_file
echo "=====================================" >> $output_file

# Install necessary tools if not installed
if ! command -v openssl &> /dev/null; then
    echo "openssl not found. Installing..."
    sudo apt update && sudo apt install -y openssl
fi

if ! command -v nmap &> /dev/null; then
    echo "nmap not found. Installing..."
    sudo apt update && sudo apt install -y nmap
fi

if ! command -v curl &> /dev/null; then
    echo "curl not found. Installing..."
    sudo apt update && sudo apt install -y curl
fi

# Test for Insufficient Transport Layer Security
echo "[1] Testing for Insufficient Transport Layer Security" >> $output_file
nmap --script ssl-enum-ciphers -p 443 "$domain" >> $output_file 2>&1 || echo "Nmap failed or no SSL support detected." >> $output_file

echo "=====================================" >> $output_file

# Test for Weak SSL Ciphers
echo "[2] Testing for Weak SSL Ciphers" >> $output_file
openssl s_client -connect "$domain":443 </dev/null 2>/dev/null | openssl x509 -noout -text >> $output_file 2>&1 || echo "OpenSSL failed or no SSL support detected." >> $output_file

echo "=====================================" >> $output_file

# Test for Weak Encoding Techniques
echo "[3] Testing for Weak Encoding Techniques" >> $output_file
response_headers=$(curl -s -I "$target_url")
echo "$response_headers" | grep -i "content-encoding" >> $output_file
if echo "$response_headers" | grep -iq "gzip\|deflate\|br"; then
    echo "Secure Encoding Detected" >> $output_file
else
    echo "Weak or No Encoding Detected" >> $output_file
fi

echo "=====================================" >> $output_file

# Completion message
echo "Transport Layer Security testing complete. Results saved in: $output_file"
