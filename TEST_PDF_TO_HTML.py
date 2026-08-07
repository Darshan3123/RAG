"""
PREREQUISITES:
This script requires both 'Ghostscript' and 'pdf2htmlEX' to be installed on your system.

Installation Instructions:

[Ubuntu / Debian]
sudo apt-get update
sudo apt-get install ghostscript
wget https://github.com/pdf2htmlEX/pdf2htmlEX/releases/download/v0.18.8.rc1/pdf2htmlEX-0.18.8.rc1-master-20200630-Ubuntu-bionic-x86_64.deb
sudo apt-get install ./pdf2htmlEX-0.18.8.rc1-master-20200630-Ubuntu-bionic-x86_64.deb

[macOS]
brew install ghostscript
brew tap pdf2htmlex/pdf2htmlex
brew install pdf2htmlex

[Windows]
Ghostscript: Download from https://ghostscript.com/releases/gsdnld.html
pdf2htmlEX: Native Windows support is limited; using Windows Subsystem for Linux (WSL) or Docker is recommended.
(Note: If running natively on Windows, you may need to change "gs" to "gswin64c" in the gs_command below).
"""

import subprocess
import os
import sys

def safe_convert_pdf_to_html(input_pdf, output_dir=None, cleanup_intermediate=True):
    """
    Preprocesses a PDF using Ghostscript to fix font/16-bit truncation errors,
    then converts the cleaned PDF to HTML using pdf2htmlEX.
    """
    if not os.path.exists(input_pdf):
        print(f"Error: The input file '{input_pdf}' does not exist.")
        return False

    # Set up file paths
    abs_input_pdf = os.path.abspath(input_pdf)
    input_dir = os.path.dirname(abs_input_pdf)
    base_name = os.path.splitext(os.path.basename(abs_input_pdf))[0]
    
    # Define intermediate clean PDF path
    clean_pdf = os.path.join(input_dir, f"{base_name}_clean.pdf")
    
    # Destination directory for HTML
    dest_dir = output_dir if output_dir else input_dir

    print(f"Step 1: Preprocessing '{input_pdf}' with Ghostscript...")
    
    # Ghostscript command to re-distill the PDF and clean corrupted font dicts
    # Note: On Windows, the command is usually 'gswin64c' instead of 'gs'
    gs_command = [
        "gs", 
        "-sDEVICE=pdfwrite", 
        "-dCompatibilityLevel=1.4", 
        "-dPDFSETTINGS=/printer", 
        "-dNOPAUSE", 
        "-dQUIET", 
        "-dBATCH", 
        f"-sOutputFile={clean_pdf}", 
        abs_input_pdf
    ]

    try:
        subprocess.run(gs_command, check=True, capture_output=True, text=True)
        print("Preprocessing successful. Cleaned PDF created.")
    except subprocess.CalledProcessError as e:
        print("Error during Ghostscript preprocessing:")
        print(e.stderr)
        return False
    except FileNotFoundError:
        print("Error: Ghostscript ('gs') is not installed or not in your system's PATH.")
        return False

    print(f"Step 2: Converting cleaned PDF to HTML using pdf2htmlEX...")
    
    pdf2html_command = [
        "pdf2htmlEX",
        "--dest-dir", dest_dir,
        clean_pdf
    ]

    try:
        subprocess.run(pdf2html_command, check=True, capture_output=True, text=True)
        print(f"Conversion successful! HTML saved in: {dest_dir}")
        
    except subprocess.CalledProcessError as e:
        print("Error during pdf2htmlEX conversion:")
        print(e.stderr)
        return False
    except FileNotFoundError:
        print("Error: pdf2htmlEX is not installed or not in your system's PATH.")
        return False
        
    # Optional: Delete the intermediate cleaned PDF to save space
    if cleanup_intermediate and os.path.exists(clean_pdf):
        print("Cleaning up intermediate files...")
        os.remove(clean_pdf)
        
    print("Process complete.")
    return True

if __name__ == "__main__":
    # Example usage:
    # Ensure you are using the correct path to your PDF
    target_pdf = "anxnew_f65630dc-70d8-4448-99611779358242187_ESICHOPBIBPUNE@MED3 (1).pdf" 
    
    # You can specify a different output directory, e.g., output_dir="HTML_OUTPUT"
    safe_convert_pdf_to_html(target_pdf, cleanup_intermediate=True)