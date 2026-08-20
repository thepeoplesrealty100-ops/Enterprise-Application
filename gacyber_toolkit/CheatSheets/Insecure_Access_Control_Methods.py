import requests

def check_admin_indicators(url):
    # List of common parameters that may indicate admin access
    admin_parameters = [
        'admin', 'is_admin', 'role', 'access', 'user_type'
    ]

    # List of common headers that may indicate admin access, including Referer
    admin_headers = [
        'Referer', 'X-Admin', 'X-Access-Level', 'Authorization'
    ]

    print("[*] Checking for admin indicators in HTTP request parameters and response headers...")

    try:
        # Check for admin-related request parameters
        params_found = False
        for param in admin_parameters:
            print(f"[*] Testing request parameter: {param}")
            response = requests.get(url, params={param: 'test'})

            # Acknowledge if the parameter is identified in the request
            if response.status_code == 200:
                print(f"[+] Parameter '{param}' identified as an indicator of admin access.")
                params_found = True
            else:
                print(f"[-] Parameter '{param}' not identified as an indicator of admin access.")

        if not params_found:
            print("[*] No admin access indicators found in request parameters.")

        # Check for admin-related response headers
        headers_found = False
        response = requests.get(url)

        for header in admin_headers:
            print(f"[*] Testing for response header: {header}")
            if header in response.headers:
                print(f"[+] Header '{header}' identified as an indicator of admin access.")
                headers_found = True
            else:
                print(f"[-] Header '{header}' not identified as an indicator of admin access.")

        if not headers_found:
            print("[*] No admin access indicators found in response headers.")

    except requests.exceptions.RequestException as e:
        print(f"[!] Error during request: {e}")

if __name__ == "__main__":
    # Prompt the user for the target URL
    target_url = input("Enter the target web application URL (e.g., http://example.com): ")
    check_admin_indicators(target_url)