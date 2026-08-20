import subprocess
import sys

# Function to install required packages
def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# Install the required packages
install('builtwith')
install('requests')

import builtwith
import requests

# Ask the user to input the URL
url = input("Enter the URL of the target website: ")

# Identify the technologies used by the website
technologies = builtwith.parse(url)

# Make a request to the website to get headers and cookies
response = requests.get(url)

# Extract headers and cookies
headers = response.headers
cookies = response.cookies

# Save the output in a separate text file
with open('server_side_technologies.txt', 'w') as f:
    f.write("Technologies:\n")
    for tech, details in technologies.items():
        f.write(f"{tech}: {', '.join(details)}\n")
    
    f.write("\nHTTP Response Headers:\n")
    for header, value in headers.items():
        f.write(f"{header}: {value}\n")
    
    f.write("\nCookies:\n")
    for cookie in cookies:
        f.write(f"{cookie.name}: {cookie.value}\n")

print("The server-side technologies, HTTP response headers, and cookies have been saved to server_side_technologies.txt file.")