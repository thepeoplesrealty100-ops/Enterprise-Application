#!/bin/bash

function detect_weak_encoding() {
  url="$1"

  # Use curl to fetch the webpage content
  response=$(curl -s "$url")

  # Check for common weak encoding techniques
  # 1. URL Encoding
  if [[ "$response" =~ "%" ]]; then
    echo "URL Encoding detected in $url"
  fi

  # 2. HTML Encoding
  if [[ "$response" =~ "&[a-zA-Z]+;" ]]; then
    echo "HTML Encoding detected in $url"
  fi

  # 3. Base64 Encoding (Basic check)
  if [[ "$response" =~ "[A-Za-z0-9+/=]" ]]; then
    echo "Potential Base64 Encoding detected in $url"
  fi

  # 4. Unicode Encoding (UTF-8, UTF-16, etc.)
  # Check for non-ASCII characters
  if [[ "$response" =~ [^\x00-\x7F] ]]; then
    echo "Unicode Encoding detected in $url"
  fi

  # 5. JavaScript Encoding
  # Check for common JavaScript encoding techniques like Unicode escape sequences
  if [[ "$response" =~ "\\u[0-9a-fA-F]{4}" ]]; then
    echo "JavaScript Encoding detected in $url"
  fi

  # 6. Other Encoding Techniques (e.g., ASCII85, UUencode)
  # Add more checks as needed based on specific encoding patterns

  # Advanced checks can be implemented using tools like OWASP ZAP or Burp Suite
  # to analyze the response headers, cookies, and other parameters for potential vulnerabilities.
}

# Get the target URL from the user
read -p "Enter the target URL: " target_url

# Detect weak encoding
detect_weak_encoding "$target_url"