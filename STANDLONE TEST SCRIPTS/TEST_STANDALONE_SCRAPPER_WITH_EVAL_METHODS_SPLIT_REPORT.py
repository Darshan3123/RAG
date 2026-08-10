"""
Two-Phase High-Speed GeM Scraper and Evaluation Method Categorization Pipeline.

Phase 1: High-speed RAM Scraper using Playwright for session extraction and ThreadPoolExecutor for downloading
PDF files directly into an in-memory buffer before flushing to disk.
Phase 2: PyMuPDF batch text extraction, detecting digital text layers, searching for evaluation method keywords 
(Item-Wise, Total-Wise, Group-Wise), sorting documents into category folders, and generating an evaluation summary report.
"""

import os
import sys
import threading
import requests
import re
import time
import subprocess
import json
import shutil
import datetime
from concurrent.futures import ThreadPoolExecutor

# -------------------------------------------------------------------------
# AUTO-INSTALL DEPENDENCIES (PyMuPDF & TQDM)
# -------------------------------------------------------------------------
REQUIRED_PACKAGES = ["pymupdf", "tqdm"]

def install_dependencies():
    """Verify presence of required packages (PyMuPDF, TQDM) and automatically install via pip if missing."""
    for package in REQUIRED_PACKAGES:
        try:
            if package == "pymupdf":
                import pymupdf
            elif package == "tqdm":
                from tqdm import tqdm
        except ImportError:
            print(f"📦 Dependency '{package}' missing. Installing via pip...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
                print(f"✅ Successfully installed {package}")
            except Exception as e:
                print(f"❌ Failed to install {package}: {e}")
                sys.exit(1)

install_dependencies()
import pymupdf
from tqdm import tqdm

# Ensure the script can find local modules for Playwright
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import GemBrowser

# ==========================================
# CONFIGURATION
# ==========================================
OUTPUT_DIR_PDF = os.path.join("Scrape_Data", "PDFs")
OUTPUT_DIR_TXT = os.path.join("Scrape_Data", "Texts")
CATEGORIES = ["Item_Wise", "Total_Wise", "Group_Wise", "Other"]

# Create root directories and category subdirectories
for directory in [OUTPUT_DIR_PDF, OUTPUT_DIR_TXT]:
    os.makedirs(directory, exist_ok=True)
    for cat in CATEGORIES:
        os.makedirs(os.path.join(directory, cat), exist_ok=True)

START_PAGE = 1
END_PAGE = 15
MAX_WORKERS = 32 
MAX_BUFFER_ITEMS = 2000 

# Global In-Memory Buffer and Lock
memory_buffer = []
buffer_lock = threading.Lock()

# ==========================================
# PHASE 1: HIGH-SPEED RAM SCRAPING
# ==========================================
def flush_buffer_to_disk():
    """Concurrently write all PDF file bytes currently held in RAM memory buffer onto disk storage."""
    global memory_buffer
    
    with buffer_lock:
        if not memory_buffer:
            return
        
        print(f"\n[!] Flushing {len(memory_buffer)} PDF files to disk...")
        
        def write_file(item):
            filepath, file_bytes = item
            with open(filepath, 'wb') as f:
                f.write(file_bytes)

        with ThreadPoolExecutor(max_workers=16) as disk_pool:
            disk_pool.map(write_file, memory_buffer)
            
        print(f"[+] Successfully wrote {len(memory_buffer)} files to {OUTPUT_DIR_PDF}.")
        memory_buffer.clear()

def download_to_memory(session, url, filepath):
    """
    Download a document via HTTP GET request directly into RAM buffer.
    
    Args:
        session (requests.Session): Authenticated HTTP requests session object.
        url (str): Target document PDF download URL.
        filepath (str): Target destination file path on disk when flushed.
    """
    global memory_buffer
    
    try:
        response = session.get(url, timeout=30)
        if response.status_code == 200:
            file_bytes = response.content
            
            with buffer_lock:
                memory_buffer.append((filepath, file_bytes))
                current_size = len(memory_buffer)
                
            print(f"[~] Buffered in RAM: {os.path.basename(filepath)} (Buffer: {current_size}/{MAX_BUFFER_ITEMS})")
            
            if current_size >= MAX_BUFFER_ITEMS:
                flush_buffer_to_disk()
        else:
            print(f"[-] Failed HTTP {response.status_code} for {url}")
    except Exception as e:
        print(f"[-] Error fetching {url}: {e}")

def scrape_bids_in_memory():
    """
    Execute Phase 1: High-Speed multi-threaded RAM PDF scraper across target page range.
    Uses Playwright to extract bid links and cookie session, submitting downloads to thread pool.
    """
    
    page_mapping = {} # Dictionary to store bid_no -> page_number
    
    with GemBrowser() as browser:
        browser.open_gem()
        
        bid_type_name = "Product Bid/RAs"
        browser.reset_filters()
        browser.select_bid_type(bid_type_name)
        browser.select_ongoing_bids()
        
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        for c in browser._context.cookies():
            session.cookies.set(c['name'], c['value'], domain=c['domain'])

        current_page = 1
        
        if START_PAGE > 1:
            print(f"Fast-forwarding to page {START_PAGE}...")
            while current_page < START_PAGE:
                browser.wait_for_cards()
                if not browser.go_next_page():
                    print("Reached the end of pagination before hitting the start page.")
                    return
                current_page += 1
                time.sleep(0.5)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as download_pool:
            try:
                while current_page <= END_PAGE:
                    print(f"\n--- Scraping Page {current_page} ---")
                    browser.wait_for_cards()
                    cards = browser.get_cards()
                    card_count = cards.count()
                    
                    if card_count == 0:
                        break
                        
                    for i in range(card_count):
                        card = cards.nth(i)
                        text = card.inner_text()
                        
                        # --- Time Constraint Check ---
                        date_match = re.search(r"End Date:\s*(\d{2}-\d{2}-\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)", text, re.IGNORECASE)
                        if date_match:
                            end_date_str = date_match.group(1)
                            try:
                                # Parse the scraped date
                                end_date = datetime.datetime.strptime(end_date_str, "%d-%m-%Y %I:%M %p")
                                
                                # Calculate current IST time (UTC + 5:30) to match the GeM portal
                                now_utc = datetime.datetime.now(datetime.timezone.utc)
                                now_ist_naive = (now_utc + datetime.timedelta(hours=5, minutes=30)).replace(tzinfo=None)
                                
                                # Calculate the difference in minutes
                                time_left_mins = (end_date - now_ist_naive).total_seconds() / 60
                                
                                if time_left_mins <= 20:
                                    print(f"[-] Skipping bid (Ends in {time_left_mins:.1f} mins - Less than 20 mins remaining).")
                                    continue
                            except ValueError:
                                pass # Proceed normally if date parsing fails
                        # -----------------------------
                        
                        m = re.search(r"GEM/\d{4}/B/\d+", text)
                        bid_no = m.group().replace('/', '_') if m else f"UNKNOWN_BID_P{current_page}_C{i}"
                        
                        # Save the mapping of this bid to the current page
                        page_mapping[bid_no] = current_page
                        
                        doc_url, ra_url, _ = browser.extract_card_links(card)
                        
                        if doc_url:
                            pdf_path = os.path.join(OUTPUT_DIR_PDF, f"{bid_no}.pdf")
                            if not os.path.exists(pdf_path):
                                download_pool.submit(download_to_memory, session, doc_url, pdf_path)
                        
                        if ra_url:
                            ra_path = os.path.join(OUTPUT_DIR_PDF, f"{bid_no}_RA.pdf")
                            if not os.path.exists(ra_path):
                                download_pool.submit(download_to_memory, session, ra_url, ra_path)
                    
                    if current_page < END_PAGE:
                        if not browser.go_next_page():
                            break
                    current_page += 1

            except KeyboardInterrupt:
                print("\n[!] Stop signal received from user.")
            finally:
                print("\nWaiting for pending background downloads to finish...")
        
        flush_buffer_to_disk()
        
        # Save the page mapping to a JSON file so Phase 2 can read it
        mapping_path = os.path.join("Scrape_Data", "page_mapping.json")
        with open(mapping_path, "w") as f:
            json.dump(page_mapping, f)
            
        print("Scraping Phase Completed.")

# ==========================================
# PHASE 2: PYMUPDF BATCH TEXT EXTRACTION & CATEGORIZATION
# ==========================================
def has_digital_layer(file_path, threshold=50):
    """
    Check the first page of a PDF document to verify if it contains embedded digital text.
    
    Args:
        file_path (str): Absolute or relative path to PDF document.
        threshold (int): Minimum extracted character count required to consider text digital.
        
    Returns:
        tuple[bool, int]: (is_digital_flag, total_page_count).
    """
    try:
        doc = pymupdf.open(file_path)
        num_pages = len(doc)
        
        if num_pages == 0:
            doc.close()
            return False, 0
            
        page_text = doc[0].get_text("text").strip()
        doc.close()
        
        return len(page_text) > threshold, num_pages
    except Exception:
        return False, 0

def extract_all_texts():
    """
    Execute Phase 2: Batch text extraction using PyMuPDF for downloaded PDFs.
    Categorize bids by Evaluation Method (Item_Wise, Total_Wise, Group_Wise, Other),
    move PDF files into corresponding category subdirectories, and compile a text report.
    """
    # Only get root PDF files (ignore those already categorized into subfolders)
    pdf_files = [f for f in os.listdir(OUTPUT_DIR_PDF) 
                 if f.lower().endswith('.pdf') 
                 and not f.endswith('_RA.pdf') 
                 and os.path.isfile(os.path.join(OUTPUT_DIR_PDF, f))]
    
    if not pdf_files:
        print("No unclassified PDF files found in root directory to extract.")
        return

    # Load the page mapping created in Phase 1
    mapping_path = os.path.join("Scrape_Data", "page_mapping.json")
    page_mapping = {}
    if os.path.exists(mapping_path):
        with open(mapping_path, "r") as f:
            page_mapping = json.load(f)

    infer_times = []
    total_pages_processed = 0
    skipped_files = 0
    results_to_save = []
    
    # Dictionary to hold categorized tuples of (Bid Number, Page Number)
    categorized_bids = {
        "Item_Wise": [],
        "Total_Wise": [],
        "Group_Wise": [],
        "Other": []
    }
    
    print(f"\nStarting PyMuPDF batch extraction & categorization for {len(pdf_files)} PDFs...\n")
    
    for file_name in tqdm(pdf_files, desc="Extracting & Sorting", mininterval=0):
        file_path = os.path.join(OUTPUT_DIR_PDF, file_name)
        base_name = os.path.splitext(file_name)[0]
        
        is_digital, num_pages = has_digital_layer(file_path)
        
        if not is_digital:
            skipped_files += 1
            # Move skipped files to "Other" folder to clean up root
            shutil.move(file_path, os.path.join(OUTPUT_DIR_PDF, "Other", file_name))
            continue
            
        start_time = time.time()
        try:
            doc = pymupdf.open(file_path)
            page_texts = []
            for page in doc:
                page_texts.append(page.get_text())
                
            raw_text = "\n\n---PAGE BREAK---\n\n".join(page_texts)
            doc.close()
        except Exception as e:
            tqdm.write(f"\n⚠️ Failed to extract {file_name}: {e}")
            continue
            
        end_time = time.time()
        infer_duration = end_time - start_time
        
        infer_times.append(infer_duration)
        total_pages_processed += num_pages
        
        # --- Check for Evaluation Method ---
        eval_category = "Other"
        
        if re.search(r"Item\s*wise\s*evaluation", raw_text, re.IGNORECASE):
            eval_category = "Item_Wise"
        elif re.search(r"(Total\s*value\s*wise\s*evaluation|Total\s*wise\s*evaluation)", raw_text, re.IGNORECASE):
            eval_category = "Total_Wise"
        elif re.search(r"Group\s*wise\s*evaluation", raw_text, re.IGNORECASE):
            eval_category = "Group_Wise"

        # Record the mapping for the report
        page_num = page_mapping.get(base_name, "Unknown")
        original_bid_no = base_name.replace('_', '/') if base_name.startswith('GEM_') else base_name
        categorized_bids[eval_category].append((original_bid_no, page_num))
        
        # --- Move the PDF to its respective category folder ---
        new_pdf_path = os.path.join(OUTPUT_DIR_PDF, eval_category, file_name)
        shutil.move(file_path, new_pdf_path)
        
        # Check if an RA PDF exists and move it too
        ra_file_name = f"{base_name}_RA.pdf"
        ra_file_path = os.path.join(OUTPUT_DIR_PDF, ra_file_name)
        if os.path.exists(ra_file_path):
            new_ra_path = os.path.join(OUTPUT_DIR_PDF, eval_category, ra_file_name)
            shutil.move(ra_file_path, new_ra_path)

        # --- Queue the Text file for its respective category folder ---
        output_file_name = f"{base_name}.txt"
        output_file_path = os.path.join(OUTPUT_DIR_TXT, eval_category, output_file_name)
        results_to_save.append((output_file_path, raw_text))

    print("\n" + "="*50)
    print("📊 EXTRACTION & CATEGORIZATION SUMMARY")
    print("="*50)
    
    if infer_times:
        total_infer_time = sum(infer_times)
        pages_per_sec = total_pages_processed / total_infer_time if total_infer_time > 0 else 0
        print(f"Total PDFs Processed : {len(infer_times)}")
        print(f"Total PDFs Skipped   : {skipped_files}")
        print(f"Total Pages Extracted: {total_pages_processed}")
        print("-" * 30)
        print(f"📦 Item-Wise Bids    : {len(categorized_bids['Item_Wise'])}")
        print(f"📦 Total-Wise Bids   : {len(categorized_bids['Total_Wise'])}")
        print(f"📦 Group-Wise Bids   : {len(categorized_bids['Group_Wise'])}")
        print(f"📦 Other Bids        : {len(categorized_bids['Other'])}")
        print("-" * 50)
        print(f"🚀 Overall Speed     : {pages_per_sec:.2f} pages / sec")
        print("="*50)

    if results_to_save:
        print(f"\n💾 Saving {len(results_to_save)} Text files into categorized folders...")
        for output_file_path, raw_text in tqdm(results_to_save, desc="Writing Files"):
            with open(output_file_path, "w", encoding="utf-8-sig", errors="replace") as f:
                f.write(raw_text)
                
    # --- PRINT TO CONSOLE AND SAVE REPORT ---
    report_path = os.path.join("Scrape_Data", "Evaluation_Method_Report.txt")
    
    with open(report_path, "w", encoding="utf-8") as report_file:
        report_file.write("=== BID EVALUATION METHOD REPORT ===\n\n")
        
        for category in ["Item_Wise", "Total_Wise", "Group_Wise"]:
            bids = categorized_bids[category]
            
            # Print to Console
            print("\n" + "="*60)
            print(f"📜 {category.upper().replace('_', ' ')} EVALUATION BIDS ({len(bids)}):")
            print("="*60)
            
            # Write Header to File
            report_file.write("="*60 + "\n")
            report_file.write(f"{category.upper().replace('_', ' ')} EVALUATION BIDS:\n")
            report_file.write("="*60 + "\n")
            
            if not bids:
                print("No bids found in this category.")
                report_file.write("No bids found in this category.\n\n")
            else:
                for bid, page in bids:
                    line = f"Page: {str(page).ljust(4)} | Bid: {bid}"
                    print(line)
                    report_file.write(line + "\n")
                report_file.write("\n")
                
            print("="*60)
            
    print(f"\n✅ Saved detailed evaluation report to {report_path}")
    print("✅ All processing completed.")

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    # Phase 1
    scrape_bids_in_memory()
    
    # Phase 2
    extract_all_texts()
