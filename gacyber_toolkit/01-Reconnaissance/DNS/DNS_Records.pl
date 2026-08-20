#!/usr/bin/perl
use strict;
use warnings;
print "Enter domain name for DNS lookup: ";
chomp(my $domain = <STDIN>);
my @record_types = ("A", "MX", "NS", "TXT");
foreach my $type (@record_types) {
    print "\n$type Records:\n";
    print `dig +short $domain $type` || "No $type records found.\n";
}
print "\nDNS lookup completed.\n";
