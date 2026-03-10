import os

def read_file_safely(filepath):
    """
    Attempts to read a file, handling FileNotFoundError if the file does not exist.
    """
    try:
        with open(filepath, 'r') as f:
            content = f.read()
            print(f"File content:\n{content}")
    except FileNotFoundError:
        print(f"Error: The file '{filepath}' was not found.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    nonexistent_file = "./nonexistent_file_abc123.py"
    read_file_safely(nonexistent_file)
