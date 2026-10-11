#!/usr/bin/ruby
require 'socket'

# Check for valid input
if ARGV.length != 2
  puts "Usage: #{$0} <start_ip> <end_ip>"
  exit 1
end

start_ip = ARGV[0]
end_ip = ARGV[1]

# Convert IP addresses to integer for comparison
def ip_to_i(ip)
  ip.split('.').map(&:to_i).inject(0) { |sum, octet| (sum << 8) + octet }
end

def i_to_ip(i)
  [i >> 24, (i >> 16) & 255, (i >> 8) & 255, i & 255].join('.')
end

# Convert start and end IPs to integers
start_i = ip_to_i(start_ip)
end_i = ip_to_i(end_ip)

s = UDPSocket.new

(start_i..end_i).each do |i|
  next if i == 0
  ip_address = i_to_ip(i)
  s.send("test", 0, ip_address, 53)
end

f = File.open("/proc/net/arp", 'r')
data = f.read.split("\n")
up_hosts = []

data.each do |line|
  entry = line.split(/\s+/)
  next if entry[3] == "00:00:00:00:00:00"
  next if entry[0] == "IP"
  up_hosts << {:ip => entry[0], :mac => entry[3]}
end

print "Active network hosts\n"
print "%-12s\t%s\n" % ["IP Addr", "MAC Address"]
up_hosts.each do |host|
  print "%-12s\t%s\n" % [host[:ip], host[:mac]]
end