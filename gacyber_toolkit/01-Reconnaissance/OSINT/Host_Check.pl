#!/usr/bin/env perl
use strict;
use warnings;
use Net::Ping;

# Function to get the MAC address of a host
sub get_mac_address {
    my ($ip) = @_;
    my $arp_output = `arp -n $ip 2>/dev/null`;
    if ($arp_output =~ /([0-9A-Fa-f:]{17})/) {
        return $1;  # Return the MAC address
    }
    return "MAC address not found";
}

# Convert an IP address to its numeric equivalent
sub ip_to_number {
    my ($ip) = @_;
    my @octets = split(/\./, $ip);
    return ($octets[0] << 24) + ($octets[1] << 16) + ($octets[2] << 8) + $octets[3];
}

# Convert a numeric equivalent back to an IP address
sub number_to_ip {
    my ($num) = @_;
    return join('.', ($num >> 24) & 255, ($num >> 16) & 255, ($num >> 8) & 255, $num & 255);
}

# Scan the given range of IP addresses
sub scan_range {
    my ($start_ip, $end_ip) = @_;
    my $start_num = ip_to_number($start_ip);
    my $end_num = ip_to_number($end_ip);

    print "\nScanning IP range: $start_ip - $end_ip\n";
    my $ping = Net::Ping->new();

    for my $current_num ($start_num .. $end_num) {
        my $current_ip = number_to_ip($current_num);
        if ($ping->ping($current_ip, 1)) {  # Ping with 1-second timeout
            print "[+] Host is live: $current_ip\n";
            my $mac = get_mac_address($current_ip);
            print "    MAC Address: $mac\n";
        }
    }
    $ping->close();
}

# Main script
print "Enter the starting IP address: ";
my $start_ip = <STDIN>;
chomp($start_ip);

print "Enter the ending IP address: ";
my $end_ip = <STDIN>;
chomp($end_ip);

scan_range($start_ip, $end_ip);