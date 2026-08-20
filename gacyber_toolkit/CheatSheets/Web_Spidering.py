import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

def spider(url, output_file='Web_spider.txt'):
    visited = set()
    to_visit = [url]

    with open(output_file, 'w', encoding='utf-8') as f:
        while to_visit:
            current_url = to_visit.pop(0)
            if current_url in visited:
                continue

            print(f"Visiting: {current_url}")
            try:
                response = requests.get(current_url)
                response.raise_for_status()

                # Check if the content type is HTML
                content_type = response.headers.get('Content-Type', '')
                if 'text/html' not in content_type:
                    f.write(f"Skipped non-HTML content: {current_url}\n")
                    continue

                f.write(f"URL: {current_url}\n")
                f.write(f"Status Code: {response.status_code}\n")
                f.write(f"Content-Type: {content_type}\n")
                f.write('\n')

                # Extract and write links
                soup = BeautifulSoup(response.text, 'html.parser')
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    absolute_url = urljoin(current_url, href)
                    f.write(f"Found Link: {absolute_url}\n")
                    if absolute_url not in visited:
                        to_visit.append(absolute_url)

            except requests.RequestException as e:
                f.write(f"Error accessing {current_url}: {e}\n")
                continue

            visited.add(current_url)

if __name__ == "__main__":
    url = input("Enter the URL of the website to spider: ")
    spider(url)