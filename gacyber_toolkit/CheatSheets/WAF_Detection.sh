#!/bin/bash

# Prompt the user to enter the target URL
echo "Enter the target URL (e.g., http://example.com):"
read target_url

# Send a request and store the headers in a variable
response_headers=$(curl -s -I "$target_url")

# Define common WAF-related headers and keywords to look for
waf_indicators=("Server" "X-Cache" "X-CDN" "X-Security" "X-WAF" "X-Protection" "X-Powered-By")

# Check for the presence of WAF-related headers and display details if detected
echo "Checking for Web Application Firewall (WAF) protection..."

waf_detected=false

for header in "${waf_indicators[@]}"; do
    if echo "$response_headers" | grep -i "$header" > /dev/null; then
        echo "[Detected] $header: $(echo "$response_headers" | grep -i "$header")"
        waf_detected=true
    fi
done

if [ "$waf_detected" = true ]; then
    echo -e "\nWAF protection detected on the target website."
else
    echo "No WAF detected based on response headers."
fi
