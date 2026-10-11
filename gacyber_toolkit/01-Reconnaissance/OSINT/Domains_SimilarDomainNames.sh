#!/bin/bash

# Function to check if the required tools are installed
function check_tools_installed() {
    for tool in nmap urlcrazy; do
        if ! command -v $tool &> /dev/null
        then
            echo "$tool is not installed. Please install it first."
            exit 1
        fi
    done
    echo "All required tools are installed."
}

# Function to gather subdomains using Nmap's dns-brute script
function gather_subdomains_nmap() {
    domain=$1
    output_file="${domain}_subdomains_nmap.txt"
    echo "Running Nmap dns-brute script to gather subdomains for $domain..."

    # Run the Nmap dns-brute script and save the results to a file
    nmap --script dns-brute -v $domain > $output_file

    echo "Subdomains saved to $output_file"
}

# Function to find similar or parallel domain names using URLCrazy
function find_similar_domains_urlcrazy() {
    domain=$1
    output_file="${domain}_similar_domains_urlcrazy.txt"
    echo "Running URLCrazy to find typosquatting and similar domains for $domain..."

    # Run URLCrazy and save the results to a file
    urlcrazy $domain > $output_file 2>/dev/null

    echo "Similar domains saved to $output_file"
}

# Main function to perform the extraction process
function main() {
    echo "Enter the target domain (e.g., example.com):"
    read domain

    # Check if the required tools are installed
    check_tools_installed

    # Perform subdomain extraction using Nmap
    gather_subdomains_nmap $domain

    # Perform similar domain extraction using URLCrazy
    find_similar_domains_urlcrazy $domain

    echo "Process completed for $domain. Check the output files for the results."
}

# Execute the main function
main