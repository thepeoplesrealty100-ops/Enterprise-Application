import subprocess

def mirror_website(url, output_dir):
    try:
        # Construct the wget command
        command = ['wget', '--mirror', '--convert-links', '--adjust-extension', '--page-requisites', '--no-parent', url]

        # Execute the command
        subprocess.run(command, check=True)
        print(f"Website mirroring completed successfully. Mirrored pages saved in {output_dir}")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while mirroring the website: {e}")

def main():
    # Ask the user to input the URL
    url = input("Enter the URL of the website to mirror: ")

    # Ask the user to input the output directory
    output_dir = input("Enter the output directory to save the mirrored pages: ")

    # Call the mirror_website function
    mirror_website(url, output_dir)

if __name__ == "__main__":
    main()