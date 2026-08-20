#!/bin/bash

# Define variables
TARGET_IP="192.168.0.51"
USERNAME="ubuntu"
PASSWORD="toor"
OUTPUT_FILE="file_permissions_report.txt"

# Install required dependencies
sudo apt update && sudo apt install -y sshpass

# Connect to the target machine and retrieve file information
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no $USERNAME@$TARGET_IP bash << 'EOF' > $OUTPUT_FILE

echo "===== SUID FILES ====="
find / -perm /4000 2>/dev/null

echo "\n===== SGID FILES ====="
find / -perm /2000 2>/dev/null

echo "\n===== WORLD-WRITABLE FILES ====="
find / -type f -perm -o+w 2>/dev/null

echo "\n===== WORLD-WRITABLE DIRECTORIES ====="
find / -type d -perm -o+w 2>/dev/null

EOF

# Notify user
echo "File permissions report generated. Results saved in $OUTPUT_FILE."
