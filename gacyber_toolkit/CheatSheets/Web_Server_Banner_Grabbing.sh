#!/bin/bash

# Prompt user for the target URL
read -p "Enter the target URL (e.g., https://example.com): " TARGET_URL

# Validate the URL format
if ! [[ $TARGET_URL =~ ^https?:// ]]; then
  echo "Invalid URL format. Please include 'http://' or 'https://'."
  exit 1
fi

# Use curl to fetch the headers
response=$(curl -s -I "$TARGET_URL")

# Check if curl command was successful
if [ $? -ne 0 ]; then
  echo "Failed to retrieve headers from $TARGET_URL"
  exit 1
fi

# Output the response headers
echo "Response Headers:"
echo "$response"

# Extract the Server header to identify web server details
server_info=$(echo "$response" | grep -i "^Server:")

if [ -z "$server_info" ]; then
  echo "No Server information found in the response."
else
  echo "Web Server Information: $server_info"
fi

# Optionally, extract other useful headers like X-Powered-By
powered_by_info=$(echo "$response" | grep -i "^X-Powered-By:")

if [ ! -z "$powered_by_info" ]; then
  echo "Powered By Information: $powered_by_info"
fi