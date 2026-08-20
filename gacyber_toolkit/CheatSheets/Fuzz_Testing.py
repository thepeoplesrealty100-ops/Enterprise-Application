import requests
import string
import random
from urllib.parse import urljoin

def generate_random_string(length=10):
    letters = string.ascii_letters
    digits = string.digits
    special_chars = string.punctuation
    all_chars = letters + digits + special_chars
    return ''.join(random.choice(all_chars) for _ in range(length))

def is_valid_url(url):
    return url.startswith(('http://', 'https://'))

def fuzz_test(url, output_file='fuzz_testing_output.txt'):
    if not is_valid_url(url):
        print("Invalid URL. Please ensure it starts with 'http://' or 'https://'.")
        return

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"Fuzz Testing Results for URL: {url}\n\n")

        for i in range(100):  # Perform 100 fuzz tests
            random_string = generate_random_string()
            fuzzed_url = urljoin(url, random_string)  # Join base URL with random string
            f.write(f"Testing URL: {fuzzed_url}\n")

            try:
                response = requests.get(fuzzed_url)
                f.write(f"Status Code: {response.status_code}\n")
                f.write(f"Response Time: {response.elapsed.total_seconds()} seconds\n")
                f.write(f"Response Length: {len(response.text)}\n")
                f.write(f"Response Content: {response.text}\n")
                f.write('\n')
            except requests.RequestException as e:
                f.write(f"Error accessing {fuzzed_url}: {e}\n")
                f.write('\n')

if __name__ == "__main__":
    url = input("Enter the URL of the website to fuzz test: ")
    fuzz_test(url)