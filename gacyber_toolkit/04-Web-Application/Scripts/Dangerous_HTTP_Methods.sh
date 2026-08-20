#!/bin/bash

# Function to check for dangerous HTTP methods
check_dangerous_http_methods() {
    echo "Checking for dangerous HTTP methods..."
    methods=("OPTIONS" "GET" "HEAD" "POST" "PUT" "DELETE" "TRACE" "CONNECT")
    detected_methods=()

    for method in "${methods[@]}"; do
        response=$(curl -s -o /dev/null -w "%{http_code}" -X $method "$TARGET")
        if [ "$response" -eq 200 ] || [ "$response" -eq 204 ]; then
            detected_methods+=("$method")
        fi
    done

    if [ ${#detected_methods[@]} -eq 0 ]; then
        echo "No dangerous HTTP methods detected."
    else
        echo "Warning: The following dangerous HTTP methods are allowed:"
        for method in "${detected_methods[@]}"; do
            echo "- $method"
        done
    fi
}

# Main function to run all checks
main() {
    echo "Enter the URL of the target web application (e.g., http://example.com):"
    read TARGET

    # Ensure the URL starts with http:// or https://
    if [[ ! $TARGET =~ ^https?:// ]]; then
        echo "Error: Please enter a valid URL starting with http:// or https://"
        exit 1
    fi

    check_dangerous_http_methods
}

# Execute the main function
main