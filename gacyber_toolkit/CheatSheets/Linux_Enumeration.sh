#!/bin/bash

# Output file
output="Linux_Enumeration.txt"

# Clear the output file if it exists
> $output

# Function to append a section header
append_header() {
    echo -e "\n\n===== $1 =====" >> $output
}

# User and group information
append_header "User and Group Information"
id >> $output
cat /etc/group >> $output

# Hostname
append_header "Hostname"
hostname >> $output

# OS details
append_header "OS Details"
cat /etc/os-release >> $output
uname -a >> $output

# Running processes
append_header "Running Processes"
ps aux >> $output

# Active services
append_header "Active Services"
systemctl list-units --type=service --state=running >> $output

# Networking information
append_header "IP Addresses"
ip addr show >> $output

append_header "Routes"
ip route show >> $output

append_header "Open Ports"
ss -tuln >> $output

# Firewall status
append_header "Firewall Status"
sudo ufw status >> $output

# Scheduled tasks (cron jobs)
append_header "Scheduled Tasks (Cron Jobs)"
crontab -l >> $output
ls /etc/cron.* >> $output

# Loaded device drivers
append_header "Loaded Device Drivers"
lsmod >> $output

# Kernel version
append_header "Kernel Version"
uname -r >> $output

echo "Enumeration complete. Output saved to $output."