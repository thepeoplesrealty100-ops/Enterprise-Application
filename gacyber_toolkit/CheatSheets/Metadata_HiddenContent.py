import requests
from bs4 import BeautifulSoup

# Function to scrape metadata from the URL
def scrape_metadata(url):
    # Send a GET request to fetch the webpage content
    response = requests.get(url)

    # Check if the request was successful
    if response.status_code == 200:
        # Parse the content with BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')

        # Extract metadata
        metadata = {}

        # Extract title
        metadata['title'] = soup.title.string if soup.title else "No title found"

        # Extract meta description, keywords, viewport, robots
        description = soup.find("meta", attrs={"name": "description"})
        keywords = soup.find("meta", attrs={"name": "keywords"})
        viewport = soup.find("meta", attrs={"name": "viewport"})
        robots = soup.find("meta", attrs={"name": "robots"})

        metadata['description'] = description['content'] if description else "No description found"
        metadata['keywords'] = keywords['content'] if keywords else "No keywords found"
        metadata['viewport'] = viewport['content'] if viewport else "No viewport meta tag found"
        metadata['robots'] = robots['content'] if robots else "No robots meta tag found"

        return metadata
    else:
        print("Failed to retrieve the webpage. Please check the URL.")
        return None

# Function to scrape hidden inputs from forms
def scrape_hidden_inputs(url):
    # Send a GET request to fetch the webpage content
    response = requests.get(url)

    # Check if the request was successful
    if response.status_code == 200:
        # Parse the content with BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')

        # Find all hidden input fields
        hidden_inputs = soup.find_all("input", type="hidden")
        hidden_data = []

        for input_field in hidden_inputs:
            name = input_field.get('name', 'No name attribute')
            value = input_field.get('value', 'No value attribute')
            hidden_data.append(f"Name: {name}, Value: {value}")

        return hidden_data
    else:
        print("Failed to retrieve the webpage. Please check the URL.")
        return None

# Main function
if __name__ == "__main__":
    # Ask for the URL
    url = input("Enter the URL of the webpage to scrape: ")

    # Scrape metadata
    metadata = scrape_metadata(url)
    if metadata:
        # Save metadata to a text file
        with open("metadata.txt", "w") as f:
            f.write("Metadata:\n")
            for key, value in metadata.items():
                f.write(f"{key.capitalize()}: {value}\n")
        print("Metadata saved to 'metadata.txt'")

    # Scrape hidden inputs
    hidden_inputs = scrape_hidden_inputs(url)
    if hidden_inputs:
        # Save hidden inputs to a text file
        with open("hidden_inputs.txt", "w") as f:
            f.write("Hidden Inputs:\n")
            for hidden_input in hidden_inputs:
                f.write(f"{hidden_input}\n")
        print("Hidden inputs saved to 'hidden_inputs.txt'")
