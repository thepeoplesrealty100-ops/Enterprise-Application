import requests
from bs4 import BeautifulSoup

def check_reverse_tabnabbing(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching the URL: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    links = soup.find_all('a', target='_blank')

    vulnerable_links = []
    for link in links:
        if 'rel' not in link.attrs or 'noopener' not in link['rel']:
            vulnerable_links.append(link)

    if vulnerable_links:
        print(f"Found {len(vulnerable_links)} potentially vulnerable links:")
        for link in vulnerable_links:
            print(f"Link: {link.get('href')}")
    else:
        print("No vulnerable links found.")

if __name__ == "__main__":
    target_url = input("Enter the URL of the web application: ")
    check_reverse_tabnabbing(target_url)