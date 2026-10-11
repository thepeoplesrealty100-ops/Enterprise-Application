#!/usr/bin/env ruby
require 'terminal-table'

def os_and_service_discovery(target_ip)
  puts "\n[+] Performing OS and Service Version Discovery on #{target_ip}...\n"

  # OS Discovery
  puts "[*] Detecting Operating System..."
  os_command = "nmap -O #{target_ip}" # Command to detect OS
  os_result = `#{os_command}`

  os_details = "Not Available"
  if os_result.include?("OS details")
    os_details = os_result.match(/OS details: (.+)/)[1] rescue "Not Available"
    puts "  OS Detected: #{os_details}"
  else
    puts "  No OS information detected."
  end

  # Service Version Discovery
  puts "\n[*] Detecting Service Versions on Open Ports..."
  service_command = "nmap -sV #{target_ip}" # Command to detect service versions
  service_result = `#{service_command}`

  # Parse the nmap output for open ports and services
  open_ports = service_result.scan(/^(\d+\/\w+)\s+open\s+([\w-]+)\s+(.+)/)

  if open_ports.any?
    # Prepare data for the table
    rows = open_ports.map do |port, service, version|
      [port, service, version.strip]
    end

    # Display the table
    table = Terminal::Table.new(
      title: "Service Version Information",
      headings: ['Port', 'Service', 'Version'],
      rows: rows
    )
    puts table
  else
    puts "  No services detected on open ports."
  end
end

# Main Entry Point
if ARGV.empty?
  puts "Usage: ruby os_service_discovery.rb <target_ip>"
  exit
end

target_ip = ARGV[0]
os_and_service_discovery(target_ip)