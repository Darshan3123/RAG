# =========================================================================
# Testing Scripts/test_gateway_auth.py
# Phase 1 Verification Suite: FastAPI Gateway Internal Authentication
# =========================================================================
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient
from config import settings
from gateway.main import app

def run_auth_tests():
    print("=" * 80)
    print("🛡️ PHASE 1 SECURITY VERIFICATION: GATEWAY AUTHENTICATION & ACCESS CONTROL")
    print("=" * 80)

    passed = 0
    failed = 0

    def check(test_name: str, condition: bool, details: str = ""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  ✅ PASS: {test_name} {details}")
            return True
        else:
            failed += 1
            print(f"  ❌ FAIL: {test_name} {details}")
            return False

    current_key = settings.GATEWAY_INTERNAL_KEY
    rotation_key = "gem_previous_key_rotation_test_2026"
    settings.GATEWAY_INTERNAL_KEY_PREVIOUS = rotation_key

    # 1. Public Health Check
    print("\n[TEST 1] Public Unauthenticated Endpoint (/health)")
    unauthed_client = TestClient(app)
    res = unauthed_client.get("/health")
    check("GET /health returns 200 OK without any auth header", res.status_code == 200)
    check("GET /health response body contains 'healthy'", res.json().get("status") == "healthy")

    # 2. Block Missing X-Internal-Key
    print("\n[TEST 2] Missing X-Internal-Key Header (Must return 401)")
    res = unauthed_client.get("/api/v1/bids?limit=1")
    check("GET /api/v1/bids returns 401 Unauthorized", res.status_code == 401)
    check("Error code is 'UNAUTHORIZED'", res.json().get("error_code") == "UNAUTHORIZED")

    # 3. Block Invalid Key
    print("\n[TEST 3] Invalid X-Internal-Key Header (Must return 401)")
    bad_client = TestClient(app, headers={"X-Internal-Key": "completely_fake_invalid_key_999"})
    res = bad_client.get("/api/v1/bids?limit=1")
    check("GET /api/v1/bids with invalid key returns 401", res.status_code == 401)

    # 4. Accept Valid Primary Internal Key
    print("\n[TEST 4] Valid Primary Key Authentication")
    authed_client = TestClient(app, headers={"X-Internal-Key": current_key})
    res = authed_client.get("/api/v1/bids?limit=1")
    check("GET /api/v1/bids with valid key returns 200 OK", res.status_code == 200)

    # 5. Dual-Key Zero-Downtime Rotation (Previous Key)
    print("\n[TEST 5] Dual-Key Rotation (Valid Previous Key)")
    rotation_client = TestClient(app, headers={"X-Internal-Key": rotation_key})
    res = rotation_client.get("/api/v1/bids?limit=1")
    check("GET /api/v1/bids with previous key returns 200 OK", res.status_code == 200)

    # 6. Verify All Core Partition Endpoints Are Protected
    print("\n[TEST 6] Blanket Protection Across All Partition Routes")
    protected_endpoints = [
        ("/api/v1/search/quick?q=test", "Quick Search API"),
        ("/api/v1/types", "Discovery Types Aggregations API"),
        ("/api/v1/analytics/overview", "Analytics Overview API"),
        ("/api/v1/documents/GEM_2026_B_12345/pdf", "MinIO Document Presigned API"),
    ]
    for url, desc in protected_endpoints:
        unauth_res = unauthed_client.get(url)
        auth_res = authed_client.get(url)
        check(f"{desc} blocked without key (401)", unauth_res.status_code == 401)
        check(f"{desc} permitted with key (not 401)", auth_res.status_code != 401)

    # 7. Admin Scraper Routes Lockdown
    print("\n[TEST 7] Admin Scraper Routes Lockdown")
    if settings.GATEWAY_ENABLE_ADMIN_ROUTES:
        task_res = authed_client.post("/api/v1/tasks/scrape-bid", json={"bid_no": "TEST/BID/123"})
        check("When GATEWAY_ENABLE_ADMIN_ROUTES=True, tasks route is mounted", task_res.status_code != 404)
    else:
        task_res = authed_client.post("/api/v1/tasks/scrape-bid", json={"bid_no": "TEST/BID/123"})
        check("When GATEWAY_ENABLE_ADMIN_ROUTES=False, tasks route returns 404", task_res.status_code == 404)

    print("\n" + "=" * 80)
    print(f"📊 PHASE 1 TEST SUMMARY: {passed} PASSED, {failed} FAILED")
    print("=" * 80)
    return failed == 0

if __name__ == "__main__":
    success = run_auth_tests()
    sys.exit(0 if success else 1)
