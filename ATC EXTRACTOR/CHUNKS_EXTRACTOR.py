import sys
import subprocess
import os

# Auto-install dependency if missing
try:
    from bs4 import BeautifulSoup
except ImportError:
    print("beautifulsoup4 is missing. Installing it now...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "beautifulsoup4"])
    from bs4 import BeautifulSoup
    print("Installation complete.\n")


def extract_table_value(filepath, search_key):
    """
    Reads an HTML/Markdown file, parses tables, and returns the key-value pair.
    """
    # Check if the file exists to avoid errors
    if not os.path.exists(filepath):
        return f"Error: The file '{filepath}' was not found.\n"

    # Read the markdown/HTML file
    with open(filepath, 'r', encoding='utf-8') as file:
        content = file.read()

    # Parse the content
    soup = BeautifulSoup(content, 'html.parser')
    
    # Find all table rows
    rows = soup.find_all('tr')
    
    # Iterate through rows to find the specific key
    for row in rows:
        cols = row.find_all('td')
        if len(cols) == 2:  # Ensure it's a key-value pair row
            key = cols[0].text.strip()
            # Check if our target key is in the first column (case-insensitive for robustness)
            if search_key.lower() in key.lower():
                value = cols[1].text.strip()
                # Return in the format: searched key : its value
                return f"{key} : {value}"
                
    return f"'{search_key}' not found in the document."


def extract_text_chunk(filepath, start_marker, end_marker):
    """
    Reads a file and extracts the text between a start_marker and an end_marker.
    """
    # Check if the file exists
    if not os.path.exists(filepath):
        return f"Error: The file '{filepath}' was not found.\n"

    # Read the markdown file
    with open(filepath, 'r', encoding='utf-8') as file:
        content = file.read()

    # Find the starting position
    start_idx = content.find(start_marker)
    if start_idx == -1:
        return f"Error: Start marker '{start_marker}' not found in the document."

    # Move the index to the end of the start_marker so we don't include the marker itself
    content_start_idx = start_idx + len(start_marker)

    # Find the ending position, searching only after the start_idx
    end_idx = content.find(end_marker, content_start_idx)
    if end_idx == -1:
        return f"Error: End marker '{end_marker}' not found after the start marker."

    # Extract the chunk and strip leading/trailing whitespace and newlines
    extracted_chunk = content[content_start_idx:end_idx].strip()
    
    return extracted_chunk


if __name__ == "__main__":
    # Define directories and markers
    input_folder = "TEST_MARKDOWNS"
    output_dir = "OUTPUT_EXTRACTED_CHUNKS_TXT"
    key_to_search = "Document required from seller" 
    start_text = "Buyer Added Bid Specific Terms and Conditions"
    end_text = "अस्वीकरण/Disclaimer"
    
    # Create the output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Find all markdown files in the input folder and its subfolders
    md_files = []
    for root, dirs, files in os.walk(input_folder):
        for file in files:
            if file.endswith(".md"):
                md_files.append(os.path.join(root, file))
                
    if not md_files:
        print(f"No Markdown (.md) files found in the '{input_folder}' directory.")
    else:
        print(f"Found {len(md_files)} Markdown files. Starting extraction...\n")
        print("="*50)

    # Loop through each found markdown file
    for filepath in md_files:
        print(f"Processing: {filepath}")
        
        # --- Task 1: Extract Table Value ---
        table_result = extract_table_value(filepath, key_to_search)
        
        # --- Task 2: Extract Text Chunk ---
        chunk_result = extract_text_chunk(filepath, start_text, end_text)
        
        # --- Task 3: Save results to the Output Folder ---
        # Extract the base name without the extension
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        
        # Format the new output filename and join it with the directory path
        output_filename = f"{base_name}_EXTRACTED_CHUNK.txt"
        output_filepath = os.path.join(output_dir, output_filename)
        
        # Write to file
        with open(output_filepath, 'w', encoding='utf-8') as out_file:
            out_file.write(f"--- {key_to_search} ---\n")
            out_file.write(table_result + "\n\n")
            out_file.write("="*50 + "\n\n")
            out_file.write(f"--- {start_text} ---\n")
            out_file.write(chunk_result + "\n")
            
        print(f"Saved chunk to: {output_filepath}\n")
        
    print("="*50)
    print("SUCCESS: Batch extraction complete!")
