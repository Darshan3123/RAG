# =========================================================================
# benchmark_pipeline_usage.py
# Real-Time CPU & RAM Telemetry Benchmark for GeMBridge Distributed Workers
# Measures per-worker RSS memory, peak CPU %, and end-to-end latency
# =========================================================================
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import psutil

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import BASE_DIR, DOWNLOAD_DIR
from tasks.celery_app import app
from storage.postgres_db import PostgresBidDatabase

def get_system_memory_info():
    mem = psutil.virtual_memory()
    return {
        "total_mb": round(mem.total / (1024 * 1024), 1),
        "available_mb": round(mem.available / (1024 * 1024), 1),
        "used_mb": round(mem.used / (1024 * 1024), 1),
        "percent": mem.percent,
    }

class WorkerProcessMonitor:
    def __init__(self, name: str, queue: str, worker_tag: str):
        self.name = name
        self.queue = queue
        self.worker_tag = worker_tag
        self.process: Optional[subprocess.Popen] = None
        self.ps_proc: Optional[psutil.Process] = None
        self.peak_rss_mb = 0.0
        self.peak_cpu_percent = 0.0
        self.cpu_samples: List[float] = []
        self.rss_samples: List[float] = []

    def start(self, celery_bin: str):
        cmd = [
            celery_bin,
            "-A", "tasks.celery_app",
            "worker",
            "-Q", self.queue,
            "-n", f"{self.worker_tag}@local",
            "-P", "solo",
            "--loglevel=INFO",
        ]
        self.process = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.ps_proc = psutil.Process(self.process.pid)

    def sample(self):
        if not self.ps_proc or not self.ps_proc.is_running():
            return
        try:
            # Include child processes (e.g. Playwright / Chromium spawned by worker)
            total_rss = self.ps_proc.memory_info().rss
            total_cpu = self.ps_proc.cpu_percent(interval=None)
            
            for child in self.ps_proc.children(recursive=True):
                try:
                    total_rss += child.memory_info().rss
                    total_cpu += child.cpu_percent(interval=None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            rss_mb = round(total_rss / (1024 * 1024), 2)
            self.rss_samples.append(rss_mb)
            self.cpu_samples.append(total_cpu)

            if rss_mb > self.peak_rss_mb:
                self.peak_rss_mb = rss_mb
            if total_cpu > self.peak_cpu_percent:
                self.peak_cpu_percent = total_cpu
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def stop(self):
        if self.process:
            try:
                # Terminate children first
                if self.ps_proc and self.ps_proc.is_running():
                    for child in self.ps_proc.children(recursive=True):
                        try:
                            child.kill()
                        except Exception:
                            pass
                    self.ps_proc.kill()
            except Exception:
                pass
            self.process.kill()


def main():
    print("=" * 75)
    print(" GeMBridge Pipeline Hardware Footprint & Usage Benchmark")
    print(f" CPU: {psutil.cpu_count(logical=False)} Cores / {psutil.cpu_count(logical=True)} Threads")
    baseline_mem = get_system_memory_info()
    print(f" System Memory: {baseline_mem['total_mb']} MB Total | {baseline_mem['available_mb']} MB Free ({baseline_mem['percent']}% Used)")
    print("=" * 75)

    venv_celery = BASE_DIR / "venv" / "Scripts" / "celery.exe"
    if venv_celery.exists():
        celery_bin = str(venv_celery)
    else:
        which_celery = shutil.which("celery")
        celery_bin = which_celery if which_celery else "celery"

    # Initialize monitors for all 3 tiers
    workers = [
        WorkerProcessMonitor("Tier 1: Scraper", "scraping_queue", "bench_scraper"),
        WorkerProcessMonitor("Tier 2: Document/OCR", "document_queue", "bench_document"),
        WorkerProcessMonitor("Tier 3: ATC/RAG", "atc_rag_queue", "bench_atc"),
    ]

    print("\n[1/4] Spawning 3 Celery worker processes on dedicated queues...")
    for w in workers:
        w.start(celery_bin)
        print(f"  -> Started {w.name} (PID: {w.process.pid})")

    # Give workers 4 seconds to register with Redis broker
    time.sleep(4)

    # Telemetry sampling loop in background thread
    stop_sampling = threading.Event()

    def sampling_loop():
        # Initialize CPU measurement
        for w in workers:
            w.sample()
        while not stop_sampling.is_set():
            for w in workers:
                w.sample()
            time.sleep(0.5)

    sampler_thread = threading.Thread(target=sampling_loop, daemon=True)
    sampler_thread.start()

    print("\n[2/4] Dispatching End-to-End Pipeline Tasks...")
    t_start = time.time()

    # Step A: Load real sample tender to feed into Tier 2 & Tier 3
    sample_bid_no = "GEM_2025_B_6726924"
    sample_json_path = os.path.join(DOWNLOAD_DIR, sample_bid_no, f"{sample_bid_no}.json")
    sample_pdf_path = os.path.join(DOWNLOAD_DIR, sample_bid_no, f"{sample_bid_no}.pdf")

    if not os.path.exists(sample_json_path):
        print(f"Error: Sample tender {sample_bid_no} not found.")
        return

    with open(sample_json_path, "r", encoding="utf-8") as f:
        bid_data = json.load(f)

    card_data = {
        "bid": bid_data.get("bid", {}),
        "card": bid_data.get("card", {}),
    }
    hyperlinks = bid_data.get("hyperlinks", [])

    print(f"  -> Submitting Tier 2 Document Task for: {sample_bid_no}")
    from tasks.tier2_document import process_document
    task_doc = process_document.delay(
        safe_bid_no=sample_bid_no,
        card_data=card_data,
        pdf_path=sample_pdf_path,
        bid_hyperlinks=hyperlinks,
        card_html=None,
    )
    print(f"  -> Tier 2 Task ID: {task_doc.id}")

    # Step B: Wait for Tier 2 and Tier 3 execution while monitoring resources
    print("\n[3/4] Monitoring Live CPU & RAM Footprint across workers...")
    timeout = 90
    completed = False
    
    # We will poll task status from Redis
    r = app.backend
    while (time.time() - t_start) < timeout:
        elapsed = time.time() - t_start
        status_doc = task_doc.status
        sys.stdout.write(f"\r  Elapsed: {elapsed:5.1f}s | Tier 2 Task Status: {status_doc:10s} ")
        sys.stdout.flush()

        if status_doc == "SUCCESS":
            completed = True
            # Let Tier 3 finish processing
            print("\n  -> Tier 2 finished! Waiting for Tier 3 ATC & RAG indexing...")
            time.sleep(8)
            break
        elif status_doc == "FAILURE":
            print(f"\n  -> Tier 2 Task failed: {task_doc.result}")
            break
        time.sleep(1)

    t_end = time.time()
    stop_sampling.set()
    sampler_thread.join(timeout=2)

    # Stop all worker processes
    print("\n[4/4] Shutting down benchmark workers...")
    for w in workers:
        w.stop()

    # Calculate and display results
    print("\n" + "=" * 75)
    print(" HARDWARE USAGE & BENCHMARK REPORT (LOCAL WINDOWS)")
    print("=" * 75)
    print(f" Total Pipeline Runtime: {t_end - t_start:.2f} seconds")
    print(f" Baseline System Free RAM: {baseline_mem['available_mb']} MB")
    
    post_mem = get_system_memory_info()
    print(f" Post-Test System Free RAM: {post_mem['available_mb']} MB")
    print("-" * 75)
    print(f"{'Worker Service':<26} | {'Peak RAM (MB)':<14} | {'Avg RAM (MB)':<14} | {'Peak CPU %':<10}")
    print("-" * 75)

    total_peak_ram = 0.0
    for w in workers:
        avg_rss = round(sum(w.rss_samples) / len(w.rss_samples), 1) if w.rss_samples else 0.0
        total_peak_ram += w.peak_rss_mb
        print(f"{w.name:<26} | {w.peak_rss_mb:<14.1f} | {avg_rss:<14.1f} | {w.peak_cpu_percent:<10.1f}%")

    print("-" * 75)
    print(f"{'TOTAL WORKERS COMBINED':<26} | {total_peak_ram:<14.1f} MB (Only ~{total_peak_ram / 1024:.2f} GB RAM!)")
    print("=" * 75)

    # Verify S3 and DB artifacts
    print("\nVerifying Storage Artifacts Produced During Run:")
    from utils.s3_storage import list_objects
    objs = list_objects(f"bids/{sample_bid_no}")
    print(f"  MinIO S3 Objects for {sample_bid_no}:")
    for o in objs:
        print(f"    * s3://gem-tenders/{o}")

    db = PostgresBidDatabase()
    bid = db.get_bid_by_no(sample_bid_no)
    if bid:
        print(f"  PostgreSQL Tender Record: {bid.get('bid_no')} ({bid.get('organisation_name')})")
        print(f"    - Items: {len(bid.get('items', []))}")
        print(f"    - Consignees: {len(bid.get('consignees', []))}")
        print(f"    - ATC Clauses in DB: {sum(len(v) for v in bid.get('atc_checklist', {}).values())}")

if __name__ == "__main__":
    main()
