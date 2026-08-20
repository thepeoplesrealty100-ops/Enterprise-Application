#!/usr/bin/perl
use strict;
use warnings;
print "Enter the IP address for Whois lookup: ";
chomp(my $ip_address = <STDIN>);
unless ($ip_address =~ /^(\d{1,3}\.){3}\d{1,3}$/) {
    die "Invalid IP address format. Please enter a valid IP address.\n";
}
my @whois_info = `whois $ip_address`;
if (@whois_info) {
    print "\nWhois Information for IP $ip_address:\n";
    print "-------------------------------------\n";
    print @whois_info;
} else {
    print "No Whois information found for IP $ip_address.\n";
}
