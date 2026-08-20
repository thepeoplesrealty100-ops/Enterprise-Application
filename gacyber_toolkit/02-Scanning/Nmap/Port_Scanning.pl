#!/usr/bin/env perl
use strict;
use warnings;

# Function to perform a port scan using nmap and save results
sub port_scan_and_save {
    my ($ip) = @_;

    # Run nmap to perform a port scan on the host
    print "[*] Scanning $ip for open ports...\n";
    my $scan_result = `nmap -sV $ip`;

    # Save the scan results to a file named after the host's IP address
    my $filename = "$ip.txt";
    open my $fh, '>', $filename or die "Could not open file '$filename' for writing: $!";
    print $fh $scan_result;
    close $fh;

    print "[+] Scan results saved to $filename\n";
}

# Function to discover live hosts in the subnet
sub discover_live_hosts {
    my ($subnet) = @_;
    my @live_hosts;

    print "[*] Discovering live hosts in subnet: $subnet\n";

    # Use nmap to perform a ping sweep of the subnet
    my $ping_sweep_result = `nmap -sn $subnet`;
    @live_hosts = $ping_sweep_result =~ /Nmap scan report for (\d+\.\d+\.\d+\.\d+)/g;

    if (@live_hosts) {
        print "[+] Found live hosts:\n";
        print "    $_\n" for @live_hosts;
    } else {
        print "[-] No live hosts found in the subnet.\n";
    }

    return @live_hosts;
}

# Main script
print "Enter the target subnet (e.g., 192.168.1.0/24): ";
my $subnet = <STDIN>;
chomp($subnet);

# Discover live hosts in the subnet
my @live_hosts = discover_live_hosts($subnet);

# Perform port scans on each live host and save results
if (@live_hosts) {
    for my $host (@live_hosts) {
        port_scan_and_save($host);
    }
} else {
    print "No live hosts to scan.\n";
}