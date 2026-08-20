#!/usr/bin/env perl
use strict;
use warnings;

# Main function
sub main {
    print "Enter the target IP address: ";
    my $target_ip = <STDIN>;
    chomp($target_ip);

    print "\n[+] Running Nmap to identify OS and service versions...\n";

    # Run the nmap command and capture the output
    my $nmap_output = `nmap -O -sV $target_ip 2>&1`;

    # Check if nmap ran successfully
    if ($? != 0) {
        die "[-] Error executing Nmap: $nmap_output\n";
    }

    # Filter and display OS information
    print "\n[*] OS Detection:\n";
    if ($nmap_output =~ /OS details:\s+(.*)/) {
        print "  OS: $1\n";
    } else {
        print "  No OS information detected.\n";
    }

    # Filter and display service information
    print "\n[*] Service Versions:\n";
    while ($nmap_output =~ /^(\d+)\/tcp\s+open\s+(\S+)\s+(.*)/gm) {
        print "  Port: $1/tcp\n";
        print "    Service: $2\n";
        print "    Version: $3\n";
    }
}

# Execute the script
main();