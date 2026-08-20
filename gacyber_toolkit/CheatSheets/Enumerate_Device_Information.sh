#!/bin/bash

# Check if an IP address is provided as an argument
if [ $# -eq 0 ]; then
  echo "Please provide an IP address as an argument."
  exit 1
fi

target_ip=$1

# Banner Grabbing using nmap --script=banner
banner_output=$(nmap -sV -p 22,23,80,443,8080 --script banner $target_ip 2>/dev/null)

# SNMP Enumeration
snmp_output=$(snmpwalk -v 2c -c public $target_ip 1.3.6.1.2.1.1.1.0 1.3.6.1.2.1.1.5.0 1.3.6.1.2.1.1.6.0 2>/dev/null)

# Save output to a text file
echo "Banner Grabbing Output:" >> Enum_Output.txt
echo "$banner_output" >> Enum_Output.txt
echo "" >> Enum_Output.txt

echo "SNMP Enumeration Output:" >> Enum_Output.txt
echo "$snmp_output" >> Enum_Output.txt

echo "Enumeration completed. Results saved to Enum_Output.txt"