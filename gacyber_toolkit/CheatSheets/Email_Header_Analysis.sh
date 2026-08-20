#!/bin/bash

# Prompt user for input file containing email header
echo "Enter the path to the email header text file:"
read input_file

# Check if the file exists
if [[ ! -f "$input_file" ]]; then
    echo "File not found. Please provide a valid file path."
    exit 1
fi

# Output file to save extracted information
output_file="email_header_analysis_output.txt"

# Clear output file if it exists
> "$output_file"

# Extract essential information
echo "Extracting information from the email header..."

# Add header to output file
echo "Email Header Analysis Results" > "$output_file"
echo "=============================" >> "$output_file"

# Extract sender's email
echo "Sender:" >> "$output_file"
grep -i "^From: " "$input_file" >> "$output_file" || echo "Not found" >> "$output_file"

# Extract recipient's email
echo -e "\nRecipient:" >> "$output_file"
grep -i "^To: " "$input_file" >> "$output_file" || echo "Not found" >> "$output_file"

# Extract return path
echo -e "\nReturn-Path:" >> "$output_file"
grep -i "^Return-Path: " "$input_file" >> "$output_file" || echo "Not found" >> "$output_file"

# Extract subject
echo -e "\nSubject:" >> "$output_file"
grep -i "^Subject: " "$input_file" >> "$output_file" || echo "Not found" >> "$output_file"

# Extract date
echo -e "\nDate:" >> "$output_file"
grep -i "^Date: " "$input_file" >> "$output_file" || echo "Not found" >> "$output_file"

# Extract Message-ID
echo -e "\nMessage-ID:" >> "$output_file"
grep -i "^Message-ID: " "$input_file" >> "$output_file" || echo "Not found" >> "$output_file"

# Extract MIME version
echo -e "\nMIME-Version:" >> "$output_file"
grep -i "^MIME-Version: " "$input_file" >> "$output_file" || echo "Not found" >> "$output_file"

# Extract content type
echo -e "\nContent-Type:" >> "$output_file"
grep -i "^Content-Type: " "$input_file" >> "$output_file" || echo "Not found" >> "$output_file"

# Extract X-Mailer information (email client)
echo -e "\nX-Mailer:" >> "$output_file"
grep -i "^X-Mailer: " "$input_file" >> "$output_file" || echo "Not found" >> "$output_file"

# Extract DKIM signature
echo -e "\nDKIM-Signature:" >> "$output_file"
grep -i "^DKIM-Signature: " "$input_file" >> "$output_file" || echo "Not found" >> "$output_file"

# Extract SPF results
echo -e "\nSPF Authentication Results:" >> "$output_file"
grep -i "spf=" "$input_file" >> "$output_file" || echo "Not found" >> "$output_file"

# Extract IP addresses from Received headers
echo -e "\nIP Addresses (from 'Received' headers):" >> "$output_file"
grep -i "^Received: " "$input_file" | grep -oE '(\b[0-9]{1,3}\.){3}[0-9]{1,3}\b' | sort -u >> "$output_file" || echo "Not found" >> "$output_file"

# Completion message
echo "Email header analysis completed. Results saved to $output_file."
