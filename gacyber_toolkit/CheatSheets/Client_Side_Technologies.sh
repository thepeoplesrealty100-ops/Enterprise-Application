#!/bin/bash

# Prompt user for the URL of the web application
read -p "Enter the URL of the web application: " url

# Output file to store results
output_file="Client_side_technologies.txt"
> "$output_file"  # Clear file contents before starting

echo "Analyzing $url for client-side technologies..." | tee -a "$output_file"

# Fetch HTTP headers and content from the URL
headers=$(curl -sI "$url")
content=$(curl -s "$url")

# Function to log technology with version info if available
log_technology() {
  local tech_name="$1"
  local version_info="$2"
  echo "$tech_name: Detected" >> "$output_file"
  if [[ -n "$version_info" ]]; then
    echo "Version: $version_info" >> "$output_file"
  fi
  echo "" >> "$output_file"
}

# Check for HTML5 by looking for <!DOCTYPE html>
if echo "$content" | grep -iq "<!DOCTYPE html>"; then
  log_technology "HTML5" ""
fi

# Check for JavaScript by looking for <script> tags and attempt to detect version via common libraries like jQuery
if echo "$content" | grep -iq "<script"; then
  js_version=$(echo "$content" | grep -oE 'jquery-[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 | sed 's/jquery-//')
  log_technology "JavaScript" "$js_version"
fi

# Check for AJAX by looking for XMLHttpRequest or Fetch API
if echo "$content" | grep -Eq "XMLHttpRequest|fetch\("; then
  log_technology "AJAX" ""
fi

# Check for JSON by looking for application/json in headers or content
if echo "$headers" | grep -iq "application/json" || echo "$content" | grep -iq "application/json"; then
  log_technology "JSON" ""
fi

# Check for Java Applets by looking for <applet> tags and extract version if present
if echo "$content" | grep -iq "<applet"; then
  java_applet_version=$(echo "$content" | grep -oE 'java_version=[0-9]+\.[0-9]+' | head -n 1 | sed 's/java_version=//')
  log_technology "Java Applets" "$java_applet_version"
fi

# Check for Cookies by looking for Set-Cookie in headers and capture version if available
if echo "$headers" | grep -iq "Set-Cookie"; then
  cookie_version=$(echo "$headers" | grep -oE 'version=[0-9]+' | head -n 1 | sed 's/version=//')
  log_technology "Cookies" "$cookie_version"
fi

# Check for URL extensions that indicate certain technologies (e.g., .js, .json)
# Check for JavaScript files (.js)
if echo "$content" | grep -qE "\.js"; then
  log_technology "JavaScript File" ""
fi

# Check for JSON files (.json)
if echo "$content" | grep -qE "\.json"; then
  log_technology "JSON File" ""
fi

echo "Client-side technology detection completed. Results saved to $output_file."