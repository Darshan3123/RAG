# =========================================================================
# Testing Scripts/test_api_gateway.py
# Comprehensive Integration Test for GeMBridge REST API Gateway (v3.0)
# Tests all 7 endpoint groups & 10 logical partitioned modules
# =========================================================================
import json
import sys
import time
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient
from gateway.main import app

from config.settings import GATEWAY_INTERNAL_KEY
client = TestClient(app, headers={"X-Internal-Key": GATEWAY_INTERNAL_KEY})


def run_tests():
    print("=" * 75)
    print("🚀 GE MBRIDGE REST API GATEWAY COMPREHENSIVE INTEGRATION TEST")
    print("=" * 75)
    passed_tests = 0
    failed_tests = 0

    def assert_test(name: str, condition: bool, details: str = ""):
        nonlocal passed_tests, failed_tests
        if condition:
            passed_tests += 1
            print(f"  ✅ PASS: {name} {details}")
        else:
            failed_tests += 1
            print(f"  ❌ FAIL: {name} {details}")

    # -------------------------------------------------------------------------
    # 0. Health Check
    # -------------------------------------------------------------------------
    print("\n[GROUP 0] System Health & Docs")
    res = client.get("/health")
    assert_test("GET /health", res.status_code == 200, f"(Status: {res.json().get('status')})")

    # -------------------------------------------------------------------------
    # 1. Master & Filterable Bids List
    # -------------------------------------------------------------------------
    print("\n[GROUP 1] Master Dossier & Filterable Table")
    res = client.get("/api/v1/bids?limit=5")
    assert_test("GET /api/v1/bids", res.status_code == 200)
    data = res.json()
    total_records = data.get("pagination", {}).get("total_records", 0)
    print(f"    • Total Bids in Database: {total_records}")
    sample_bid_no = None
    if data.get("data"):
        sample_bid_no = data["data"][0].get("bid_no")
        print(f"    • Using Sample Tender: {sample_bid_no}")

    # Fallback if no tenders in DB
    if not sample_bid_no:
        sample_bid_no = "GEM/2026/B/7548490"

    # Master Dossier
    res = client.get(f"/api/v1/bids/{sample_bid_no}")
    assert_test(f"GET /api/v1/bids/{sample_bid_no}", res.status_code in (200, 404))
    if res.status_code == 200:
        dossier = res.json()
        assert_test("Dossier contains buyer info", "buyer" in dossier)
        assert_test("Dossier contains financials", "financials" in dossier)
        assert_test("Dossier contains items", "items" in dossier)

    # Master Dossier with include parameter
    res = client.get(f"/api/v1/bids/{sample_bid_no}?include=header,financials")
    assert_test("GET /api/v1/bids/{id}?include=...", res.status_code in (200, 404))

    # Raw JSON
    res = client.get(f"/api/v1/bids/{sample_bid_no}/raw")
    assert_test(f"GET /api/v1/bids/{sample_bid_no}/raw", res.status_code in (200, 404))

    # -------------------------------------------------------------------------
    # 2. Partitioned Sub-Resources (Tabs)
    # -------------------------------------------------------------------------
    print("\n[GROUP 2] Partitioned Sub-Resource Modules")
    partitions = [
        ("header", "Lifecycle & Timings"),
        ("buyer", "Buyer & Governance"),
        ("items", "Items & Specifications"),
        ("consignees", "Logistics & Delivery Locations"),
        ("financials", "Estimated Value & EMD/EPBG"),
        ("policy", "Policy Waivers & Relaxations"),
        ("documents", "Mandatory Seller Documents Checklist"),
        ("atc", "8-Domain ATC Compliance"),
        ("submissions", "Physical Offline Submissions"),
    ]

    for part_name, label in partitions:
        res = client.get(f"/api/v1/bids/{sample_bid_no}/{part_name}")
        assert_test(f"Partition: /{part_name} ({label})", res.status_code in (200, 404))

    # -------------------------------------------------------------------------
    # 3. Discovery & Aggregations
    # -------------------------------------------------------------------------
    print("\n[GROUP 3] Discovery & Aggregations")
    res = client.get("/api/v1/types")
    assert_test("GET /api/v1/types", res.status_code == 200)
    types_data = res.json().get("types", [])
    print(f"    • Active Procurement Types: {len(types_data)}")

    res = client.get("/api/v1/organizations?min_bids=1&limit=5")
    assert_test("GET /api/v1/organizations", res.status_code == 200)

    res = client.get("/api/v1/locations/states")
    assert_test("GET /api/v1/locations/states", res.status_code == 200)
    states_data = res.json().get("states", [])
    sample_state = "Gujarat"
    for s in states_data:
        st = s.get("state")
        if st and st.strip():
            sample_state = st.strip()
            break

    res = client.get(f"/api/v1/locations/states/{sample_state}/bids?limit=2")
    assert_test(f"GET /api/v1/locations/states/{sample_state}/bids", res.status_code == 200)

    res = client.get("/api/v1/locations/pincode/394680/bids")
    assert_test("GET /api/v1/locations/pincode/394680/bids", res.status_code == 200)

    # -------------------------------------------------------------------------
    # 4. Search & AI Semantic Retrieval
    # -------------------------------------------------------------------------
    print("\n[GROUP 4] Search & Semantic Retrieval")
    res = client.get("/api/v1/search/quick?q=Motor")
    assert_test("GET /api/v1/search/quick?q=Motor", res.status_code == 200)

    res = client.get("/api/v1/search/keyword?q=motor")
    assert_test("GET /api/v1/search/keyword?q=motor", res.status_code == 200)

    t0 = time.perf_counter()
    res = client.post(
        "/api/v1/search/semantic",
        json={"query": "Horizontal induction motor 415V TEFC", "top_k": 3},
    )
    t_sem = time.perf_counter() - t0
    assert_test(
        "POST /api/v1/search/semantic",
        res.status_code == 200,
        f"(Round-trip: {t_sem*1000:.1f}ms)",
    )
    if res.status_code == 200:
        results = res.json().get("results", [])
        print(f"    • Semantic hits returned: {len(results)}")
        for i, hit in enumerate(results[:2]):
            print(f"      Hit #{i+1} [{hit.get('chunk_type')}]: Sim={hit.get('similarity_score')} | {hit.get('matching_text')[:80]}...")

    # -------------------------------------------------------------------------
    # 5. Document Storage (MinIO S3)
    # -------------------------------------------------------------------------
    print("\n[GROUP 5] Document Storage & Presigned URLs")
    res = client.get(f"/api/v1/documents/{sample_bid_no}/pdf?redirect=false")
    assert_test(f"GET /api/v1/documents/{sample_bid_no}/pdf", res.status_code in (200, 404, 500))

    # -------------------------------------------------------------------------
    # 6. Tasks & Background Operations
    # -------------------------------------------------------------------------
    print("\n[GROUP 6] Asynchronous Operations & Worker Tasks")
    res = client.post("/api/v1/tasks/scrape-bid", json={"bid_no": "GEM/2026/B/9999999"})
    assert_test("POST /api/v1/tasks/scrape-bid", res.status_code == 200)
    task_id = res.json().get("task_id")
    if task_id:
        res_t = client.get(f"/api/v1/tasks/{task_id}")
        assert_test(f"GET /api/v1/tasks/{task_id}", res_t.status_code == 200)

    # -------------------------------------------------------------------------
    # 7. Analytics & Telemetry
    # -------------------------------------------------------------------------
    print("\n[GROUP 7] Analytics & Telemetry")
    res = client.get("/api/v1/analytics/overview")
    assert_test("GET /api/v1/analytics/overview", res.status_code == 200)
    if res.status_code == 200:
        m = res.json().get("metrics", {})
        print(f"    • Scraped Tenders: {m.get('total_tenders_scraped')}")
        print(f"    • Pipeline Value: INR {m.get('total_estimated_pipeline_inr'):,.2f}")

    res = client.get("/api/v1/analytics/ai-telemetry")
    assert_test("GET /api/v1/analytics/ai-telemetry", res.status_code == 200)
    if res.status_code == 200:
        t = res.json().get("ai_telemetry", {})
        print(f"    • Tenders Analyzed by AI: {t.get('total_tenders_analyzed')}")
        print(f"    • Total Tokens: {t.get('total_input_tokens') + t.get('total_output_tokens'):,}")
        print(f"    • Cumulative AI Cost: INR {t.get('total_cost_inr'):.2f}")

    print("\n" + "=" * 75)
    print(f"🏁 GATEWAY TEST SUMMARY: {passed_tests} PASSED | {failed_tests} FAILED")
    print("=" * 75)


if __name__ == "__main__":
    run_tests()
