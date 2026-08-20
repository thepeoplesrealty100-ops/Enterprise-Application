#!/bin/bash 
host=$1

function pingcheck {
  # Send a single ping to the host and count the number of lines with "bytes" in the response
  ping_count=$(ping -c 1 $host | grep "bytes from" | wc -l) 
  
  # Check if the ping count is greater than 0
  if [ "$ping_count" -gt 0 ]; then
    echo "$host is up"
  else
    echo "$host is down. Quitting."
    exit
  fi
}

pingcheck