# =========================================================================
# test_minio_storage.py
# Verification script for MinIO S3 object storage operations
# =========================================================================
import hashlib
import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.s3_storage import (
    ensure_bucket_exists,
    upload_bytes,
    download_bytes,
    upload_file,
    download_file,
    get_presigned_url,
    object_exists,
    list_objects,
)

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def main():
    print("=" * 70)
    print("GeMBridge MinIO S3 Object Storage Verification")
    print("Endpoint: localhost:9000 | Bucket: gem-tenders")
    print("=" * 70)

    # 1. Bucket initialization
    print("\n[1/5] Checking/Creating bucket 'gem-tenders'...")
    ensure_bucket_exists("gem-tenders")
    print("  -> Bucket 'gem-tenders' verified successfully.")

    # 2. In-Memory Streaming Test
    print("\n[2/5] Testing In-Memory Upload and Download...")
    test_payload = b"GeMBridge Enterprise Tender Document Stream Test Content"
    test_key = "test/in_memory_test.txt"
    upload_bytes(test_key, test_payload, content_type="text/plain")

    downloaded = download_bytes(test_key)
    assert downloaded == test_payload, "Downloaded bytes do not match uploaded payload!"
    print(f"  -> In-memory bytes verified (Payload: {len(downloaded)} bytes, SHA256: {sha256_bytes(downloaded)[:16]}...)")

    # 3. Object Existence & Presigned URL
    print("\n[3/5] Testing Object Existence and Presigned URL Generation...")
    assert object_exists(test_key), "object_exists returned False for existing key!"
    presigned = get_presigned_url(test_key, expiry_hours=24)
    print(f"  -> Presigned URL generated: {presigned[:80]}...")

    # 4. Real Tender PDF Upload Test
    sample_pdf = PROJECT_ROOT / "downloads" / "GEM_2025_B_6726924" / "GEM_2025_B_6726924.pdf"
    if sample_pdf.exists():
        print(f"\n[4/5] Testing Real PDF Upload: {sample_pdf}...")
        with open(sample_pdf, "rb") as f:
            pdf_bytes = f.read()

        s3_pdf_key = "bids/GEM_2025_B_6726924/bid.pdf"
        upload_bytes(s3_pdf_key, pdf_bytes, content_type="application/pdf")
        assert object_exists(s3_pdf_key), "Uploaded PDF does not exist in MinIO!"
        print(f"  -> Successfully uploaded {len(pdf_bytes)} bytes to s3://gem-tenders/{s3_pdf_key}")

        # Download and verify integrity
        downloaded_pdf = download_bytes(s3_pdf_key)
        assert sha256_bytes(downloaded_pdf) == sha256_bytes(pdf_bytes), "SHA256 checksum mismatch for uploaded PDF!"
        print("  -> SHA256 checksum matched perfectly!")
    else:
        print(f"\n[4/5] Skipping Real PDF Upload: {sample_pdf} not found.")

    # 5. List objects in bucket
    print("\n[5/5] Listing objects under 'bids/'...")
    objects = list_objects(prefix="bids/")
    for obj in objects[:10]:
        print(f"  - {obj}")
    if len(objects) > 10:
        print(f"  ... and {len(objects) - 10} more objects.")

    print("\n" + "=" * 70)
    print("ALL MINIO S3 OBJECT STORAGE TESTS PASSED")
    print("=" * 70)

if __name__ == "__main__":
    main()
