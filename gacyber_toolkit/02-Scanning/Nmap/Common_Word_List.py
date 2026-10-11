import requests
from bs4 import BeautifulSoup
import re

def extract_words(url):
    try:
        response = requests.get(url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract all text content
        text = soup.get_text()

        # Clean the text
        words = re.findall(r'\w+', text)
        words = [word.lower() for word in words]

        # Create a set to remove duplicates
        unique_words = set(words)

        # Save the words to a file
        with open('Word_list.txt', 'w') as f:
            for word in unique_words:
                f.write(word + '\n')

        print("Word list saved to Word_list.txt")

    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL: {e}")

if __name__ == '__main__':
    url = input("Enter the target URL: ")
    extract_words(url)