#!/usr/bin/env python3
# ==============================================================================
# benchmark_workers.py — Live Server Concurrency & Worker Load Stress Tester
# Designed for Hostinger KVM 4 (4 vCPU / 16 GB RAM) and Linux/Ubuntu Deployments
# ==============================================================================
"""
Benchmark tool to determine optimal worker concurrency for the GeM Scraper & RAG pipeline.

Tests:
1. System Memory & CPU Headroom Inspection
2. Playwright Headless Chromium Health Check
3. Incremental Worker Concurrency Load Test (1, 2, 4, 6, 8 workers)
4. Real-time RAM/CPU tracking per concurrent browser session
5. Identification of OOM danger zones and Hostinger KVM 4 configuration advice

Usage:
    python benchmark_workers.py                # Auto-detects and runs full benchmark
    python benchmark_workers.py --max-workers 6 # Test up to 6 workers
    python benchmark_workers.py --quick        # Fast 30-second benchmark (1, 2, 4 workers)
"""

import os
import sys
import time
import argparse
import subprocess
import threading
from typing import Dict, List, Optional, Tuple, Any

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def get_system_memory() -> Dict[str, float]:
    """
    Read memory metrics in MB.
    Works natively on Linux (/proc/meminfo) with psutil fallback if available.
    """
    total_mb = 0.0
    avail_mb = 0.0
    swap_total_mb = 0.0
    swap_free_mb = 0.0

    if os.path.exists("/proc/meminfo"):
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val_kb = float(parts[1].strip().split()[0])
                        if key == "MemTotal":
                            total_mb = val_kb / 1024.0
                        elif key == "MemAvailable":
                            avail_mb = val_kb / 1024.0
                        elif key == "SwapTotal":
                            swap_total_mb = val_kb / 1024.0
                        elif key == "SwapFree":
                            swap_free_mb = val_kb / 1024.0
            used_mb = total_mb - avail_mb
            swap_used_mb = swap_total_mb - swap_free_mb
            return {
                "total_mb": round(total_mb, 1),
                "used_mb": round(used_mb, 1),
                "avail_mb": round(avail_mb, 1),
                "used_pct": round((used_mb / total_mb * 100) if total_mb else 0, 1),
                "swap_total_mb": round(swap_total_mb, 1),
                "swap_used_mb": round(swap_used_mb, 1),
            }
        except Exception:
            pass

    # Fallback to psutil if installed
    try:
        import psutil
        v = psutil.virtual_memory()
        s = psutil.swap_memory()
        return {
            "total_mb": round(v.total / (1024 * 1024), 1),
            "used_mb": round(v.used / (1024 * 1024), 1),
            "avail_mb": round(v.available / (1024 * 1024), 1),
            "used_pct": round(v.percent, 1),
            "swap_total_mb": round(s.total / (1024 * 1024), 1),
            "swap_used_mb": round(s.used / (1024 * 1024), 1),
        }
    except ImportError:
        pass

    return {"total_mb": 16384.0, "used_mb": 4096.0, "avail_mb": 12288.0, "used_pct": 25.0, "swap_total_mb": 0.0, "swap_used_mb": 0.0}


def get_cpu_info() -> Dict[str, Any]:
    """Retrieve CPU core count and current load averages."""
    core_count = os.cpu_count() or 4
    load_1m, load_5m, load_15m = 0.0, 0.0, 0.0

    if hasattr(os, "getloadavg"):
        try:
            load_1m, load_5m, load_15m = os.getloadavg()
        except Exception:
            pass

    return {
        "cores": core_count,
        "load_1m": round(load_1m, 2),
        "load_5m": round(load_5m, 2),
        "load_15m": round(load_15m, 2),
    }


def check_playwright_ready() -> Tuple[bool, str]:
    """Verify if Playwright and Chromium are functioning in headless mode."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            # Server headless flags
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]
            )
            page = browser.new_page()
            page.set_content("<html><body><h1>GeMBridge Server Test</h1></body></html>")
            title = page.title()
            browser.close()
            return True, "Playwright Chromium launched successfully in headless mode."
    except ImportError:
        return False, "Playwright Python package is not installed. Run: pip install playwright"
    except Exception as e:
        err_msg = str(e)
        if "Host system is missing dependencies" in err_msg or "error while loading shared libraries" in err_msg:
            return False, f"Missing Ubuntu shared libraries for Chromium! Run: playwright install --with-deps chromium"
        if "Executable doesn't exist" in err_msg:
            return False, "Chromium browser binary is missing! Run: playwright install chromium"
        return False, f"Playwright launch failed: {err_msg}"


def simulate_single_worker(worker_id: int, results_dict: dict, duration_secs: int = 6):
    """Simulate a single Playwright worker loading and parsing a dynamic web DOM."""
    from playwright.sync_api import sync_playwright

    start_t = time.time()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]
            )
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # Simulate DOM parsing with complex DOM elements
            html_payload = """
            <!DOCTYPE html>
            <html>
            <head><title>GeM Bid Mock</title></head>
            <body>
                <div class="card">
                    <h2>Bid No: GEM/2026/B/7853146</h2>
                    <div class="items">Item: Medical Diagnostic Reagents - Qty: 500</div>
                    <div class="dept">Ministry of Health & Family Welfare</div>
                </div>
                <script>
                    for(let i=0; i<1000; i++) {
                        let d = document.createElement('div');
                        d.innerText = 'Tender Specification clause ' + i;
                        document.body.appendChild(d);
                    }
                </script>
            </body>
            </html>
            """
            page.set_content(html_payload)
            page.wait_for_selector("div.card", timeout=5000)
            
            # Keep browser alive for measurement period
            elapsed = time.time() - start_t
            remaining = max(0, duration_secs - elapsed)
            time.sleep(remaining)
            
            browser.close()
            results_dict[worker_id] = {
                "success": True,
                "latency_s": round(time.time() - start_t, 2),
                "error": None
            }
    except Exception as e:
        results_dict[worker_id] = {
            "success": False,
            "latency_s": round(time.time() - start_t, 2),
            "error": str(e)
        }


def run_concurrency_tier(num_workers: int, test_duration: int = 6) -> Dict[str, Any]:
    """Execute a batch of N concurrent workers and measure system memory/CPU delta."""
    mem_before = get_system_memory()
    threads: List[threading.Thread] = []
    results: Dict[int, dict] = {}

    start_clock = time.time()

    for i in range(num_workers):
        t = threading.Thread(target=simulate_single_worker, args=(i, results, test_duration))
        threads.append(t)
        t.start()

    # Sample memory midway while all workers are actively rendering
    time.sleep(test_duration / 2.0)
    mem_peak = get_system_memory()

    for t in threads:
        t.join(timeout=test_duration + 5)

    duration = time.time() - start_clock
    mem_after = get_system_memory()

    # Calculate metrics
    success_count = sum(1 for r in results.values() if r.get("success"))
    ram_consumed_mb = max(0.0, mem_peak["used_mb"] - mem_before["used_mb"])
    ram_per_worker = round(ram_consumed_mb / num_workers, 1) if num_workers > 0 else 0.0

    return {
        "workers": num_workers,
        "success_count": success_count,
        "failed_count": num_workers - success_count,
        "ram_before_mb": mem_before["used_mb"],
        "ram_peak_mb": mem_peak["used_mb"],
        "ram_avail_after_mb": mem_after["avail_mb"],
        "ram_consumed_mb": round(ram_consumed_mb, 1),
        "ram_per_worker_mb": ram_per_worker,
        "duration_s": round(duration, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="GeMBridge Server Worker Concurrency Benchmarker")
    parser.add_argument("--max-workers", type=int, default=0, help="Maximum worker count to test (default: auto)")
    parser.add_argument("--quick", action="store_true", help="Quick mode (test 1, 2, 4 workers only)")
    args = parser.parse_args()

    print("\n" + "=" * 68)
    print("  🚀 GeMBridge — Hostinger KVM 4 & Ubuntu Worker Load Tester")
    print("=" * 68)

    # 1. System Inventory
    cpu = get_cpu_info()
    mem = get_system_memory()

    print("\n[1/3] System Environment Audit:")
    print(f"  • CPU Cores Available : {cpu['cores']} vCPU (Load avg: {cpu['load_1m']})")
    print(f"  • Total Physical RAM  : {mem['total_mb']:,.0f} MB (~{mem['total_mb']/1024:.1f} GB)")
    print(f"  • Currently Used RAM  : {mem['used_mb']:,.0f} MB ({mem['used_pct']}%) by OS & other projects")
    print(f"  • Available Free RAM  : {mem['avail_mb']:,.0f} MB (~{mem['avail_mb']/1024:.1f} GB)")

    if mem["swap_total_mb"] == 0:
        print(f"  • Swap Memory         : \033[91m0 MB (NO SWAP! High risk of sudden OOM kill)\033[0m")
    else:
        print(f"  • Swap Memory         : {mem['swap_total_mb']:,.0f} MB ({mem['swap_used_mb']:,.0f} MB used)")

    # 2. Playwright Headless Verification
    print("\n[2/3] Playwright Headless Engine Verification:")
    pw_ok, pw_msg = check_playwright_ready()
    if not pw_ok:
        print(f"  ❌ \033[91m{pw_msg}\033[0m\n")
        print("  To install missing Chromium & Linux libraries on Ubuntu, run:")
        print("    \033[96mplaywright install --with-deps chromium\033[0m\n")
        sys.exit(1)
    else:
        print(f"  ✅ \033[92m{pw_msg}\033[0m")

    # 3. Determine Concurrency Test Tiers
    if args.max_workers > 0:
        tiers = [w for w in [1, 2, 4, 6, 8, 10, 12, 16] if w <= args.max_workers]
        if args.max_workers not in tiers:
            tiers.append(args.max_workers)
            tiers.sort()
    elif args.quick:
        tiers = [1, 2, 4]
    else:
        # Determine based on Hostinger KVM 4 headroom
        # 16 GB server with ~12 GB free can test up to 8 workers
        if mem["avail_mb"] >= 8000:
            tiers = [1, 2, 4, 6, 8]
        elif mem["avail_mb"] >= 4000:
            tiers = [1, 2, 4, 6]
        else:
            tiers = [1, 2, 3]

    print("\n[3/3] Running Live Concurrent Worker Load Tests...")
    print("  Testing concurrent Playwright Chromium workers under real DOM rendering:\n")

    results_table = []
    safe_max_workers = 1

    for w in tiers:
        print(f"  ▶ Benchmarking concurrency tier: {w} Worker(s)...", end="", flush=True)
        tier_res = run_concurrency_tier(num_workers=w, test_duration=5)
        print(f" Done ({tier_res['duration_s']}s)")

        # Evaluate safety
        # We want at least 1500 MB of available RAM remaining for system stability
        avail_after = tier_res["ram_avail_after_mb"]
        if tier_res["failed_count"] > 0:
            status = "\033[91mFAILED (Errors)\033[0m"
        elif avail_after < 1000:
            status = "\033[91mCRITICAL (<1GB Free)\033[0m"
        elif avail_after < 2000:
            status = "\033[93mWARNING (Low Headroom)\033[0m"
            safe_max_workers = max(safe_max_workers, w)
        else:
            status = "\033[92mSAFE & STABLE\033[0m"
            safe_max_workers = max(safe_max_workers, w)

        results_table.append({
            "workers": w,
            "consumed_mb": tier_res["ram_consumed_mb"],
            "per_worker_mb": tier_res["ram_per_worker_mb"],
            "avail_after": avail_after,
            "status": status,
        })

    # Summary Report Table
    print("\n" + "=" * 78)
    print("  📊 CONCURRENCY BENCHMARK RESULTS")
    print("=" * 78)
    print(f"  {'Workers':<9} | {'RAM Consumed':<14} | {'RAM / Worker':<14} | {'Free RAM Left':<15} | {'Health Status'}")
    print("  " + "-" * 74)
    for row in results_table:
        print(
            f"  {row['workers']:<9} | "
            f"{row['consumed_mb']:>8.1f} MB    | "
            f"{row['per_worker_mb']:>8.1f} MB    | "
            f"{row['avail_after']:>9.1f} MB    | "
            f"{row['status']}"
        )
    print("=" * 78)

    # Final Recommendation
    print("\n  🎯 SIZING & DEPLOYMENT RECOMMENDATIONS:")
    print(f"  • Safe Recommended Worker Concurrency : \033[1m\033[92m{safe_max_workers} Worker(s)\033[0m")
    print(f"  • Memory Per Worker Tab               : ~300 MB - 400 MB")
    print(f"  • Recommended .env Settings:")
    print("    \033[96mMAX_CONCURRENT_WORKERS=" + str(safe_max_workers))
    print("    OCR_PROVIDER=mistral  # (Cloud API uses 0 local GPU/RAM)")
    print("    ENABLE_PDF_ATC_SPLIT=true\033[0m")

    if mem["swap_total_mb"] == 0:
        print("\n  \033[93m⚠️  CRITICAL ACTION REQUIRED ON HOSTINGER KVM 4:\033[0m")
        print("  Your server has 0 MB swap. If Chromium spikes during large PDF rendering,")
        print("  the Linux kernel will terminate your scraper process without notice.")
        print("  Create a 4GB swapfile by running:")
        print("    \033[96msudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile\033[0m")
        print("    \033[96mecho '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab\033[0m")

    print("\n" + "=" * 68 + "\n")


if __name__ == "__main__":
    main()
