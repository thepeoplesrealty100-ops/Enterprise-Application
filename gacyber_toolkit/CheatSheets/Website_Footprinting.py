import os
import requests
from bs4 import BeautifulSoup

# Install required libraries
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    os.system('pip install requests beautifulsoup4')

# Function to gather information
def gather_information(url):
    results = []
    headers = {'User-Agent': 'Mozilla/5.0'}  # User-Agent header to mimic browser

    try:
        # Task 1: Perform website footprinting
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # Raise error for HTTP issues

        soup = BeautifulSoup(response.text, 'html.parser')

        # Collect website features
        results.append("[1] Website Footprinting")
        links = []
        for link in soup.find_all('a', href=True):
            links.append(link['href'])
        results.append("Links Found:")
        results.extend(links)

        # Task 2: Perform website enumeration
        results.append("\n[2] Website Enumeration")
        forms = soup.find_all('form')
        results.append(f"Forms Found: {len(forms)}")

        # Task 3: Analyze HTML source code
        results.append("\n[3] HTML Source Code Analysis")
        results.append(soup.prettify()[:500])  # Limiting output for brevity

        # Task 4: Check HTTP/HTML processing by the browser
        results.append("\n[4] HTTP Headers")
        results.append(str(response.headers))

        # Task 5: Identify server-side technologies
        results.append("\n[5] Server-Side Technologies")
        server = response.headers.get('Server', 'Not Found')
        results.append(f"Server: {server}")

        # Task 6: Mirror and crawl the website to identify files, directories, and folders
        results.append("\n[6] Mirroring and Crawling")
        robots_txt_url = url + '/robots.txt'
        robots_response = requests.get(robots_txt_url, headers=headers, timeout=10)
        if robots_response.status_code == 200:
            results.append("robots.txt found:")
            results.append(robots_response.text)
        else:
            results.append("robots.txt not found.")

        # Task 7: Identify the sitemap
        results.append("\n[7] Sitemap Identification")
        sitemap_url = url + '/sitemap.xml'
        sitemap_response = requests.get(sitemap_url, headers=headers, timeout=10)
        if sitemap_response.status_code == 200:
            results.append("Sitemap found:")
            results.append(sitemap_response.text)
        else:
            results.append("Sitemap not found.")

        # Task 8: Extract a common word list
        results.append("\n[8] Common Word List")
        words = soup.get_text().split()
        common_words = set(words)
        results.append("Common Words: " + ', '.join(list(common_words)[:20]))

        # Task 9: Extract metadata and hidden information
        results.append("\n[9] Metadata and Hidden Information")
        results.append(str(soup.find_all('meta')))

        # Task 10: Test WAF protection
        results.append("\n[10] WAF Protection")
        waf_headers = ['X-WAF', 'Server', 'X-CDN', 'Via']
        for header in waf_headers:
            if header in response.headers:
                results.append(f"{header}: {response.headers[header]}")
            else:
                results.append(f"{header}: Not Detected")

        # Task 11: Test Load Balancer protection
        results.append("\n[11] Load Balancer Protection")
        load_balancer_headers = ['X-Cache', 'X-Proxy', 'X-Powered-By']
        for header in load_balancer_headers:
            if header in response.headers:
                results.append(f"{header}: {response.headers[header]}")
            else:
                results.append(f"{header}: Not Detected")

        # Task 12: Perform HTTP service discovery and banner grabbing
        results.append("\n[12] HTTP Service Discovery and Banner Grabbing")
        results.append(str(response.headers))

        # Task 13: Enumerate web server directories
        results.append("\n[13] Enumerate Web Server Directories")
        directories = ['/admin', '/login', '/config', '/test', '/backup']
        for directory in directories:
            dir_url = url + directory
            dir_response = requests.get(dir_url, headers=headers, timeout=10)
            results.append(f"{dir_url} - Status: {dir_response.status_code}")

        # Task 14: Test proxy functionality
        results.append("\n[14] Proxy Testing")
        proxy_headers = ['Via', 'X-Forwarded-For']
        for header in proxy_headers:
            if header in response.headers:
                results.append(f"{header}: {response.headers[header]}")
            else:
                results.append(f"{header}: Not Detected")

    except requests.exceptions.ConnectionError:
        results.append("Error: Connection refused. The server may be down or unreachable.")
    except requests.exceptions.Timeout:
        results.append("Error: Request timed out. Please check your network.")
    except requests.exceptions.HTTPError as err:
        results.append(f"HTTP Error: {err}")
    except Exception as e:
        results.append(f"Unexpected Error: {str(e)}")

    # Save results to file
    with open('Information_Gathered.txt', 'w') as file:
        for line in results:
            file.write(line + '\n')

    print("Information gathering complete. Results saved to 'Information_Gathered.txt'.")

# Prompt for input URL
if __name__ == "__main__":
    target_url = input("Enter the target URL (e.g., https://example.com): ").strip()
    gather_information(target_url)
