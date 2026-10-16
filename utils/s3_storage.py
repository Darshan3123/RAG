# =========================================================================
# utils/s3_storage.py
# MinIO S3 Object Storage Client for In-Memory Document Streaming & Presigned URLs
# =========================================================================
import io
import os
from datetime import timedelta
from typing import Any, Dict, List, Optional, Union

from minio import Minio
from minio.error import S3Error

from config.settings import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
)
from utils.logger import get_logger

log = get_logger("s3_storage")

_CLIENT: Optional[Minio] = None


def get_minio_client() -> Minio:
    """Return a singleton authenticated MinIO client instance."""
    global _CLIENT
    if _CLIENT is None:
        log.info(f"Initializing MinIO client -> {MINIO_ENDPOINT} (secure={MINIO_SECURE})")
        _CLIENT = Minio(
            endpoint=MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )
    return _CLIENT


def ensure_bucket_exists(bucket_name: str = MINIO_BUCKET) -> bool:
    """Check if target bucket exists, and create it if missing."""
    client = get_minio_client()
    try:
        if not client.bucket_exists(bucket_name):
            client.make_bucket(bucket_name)
            log.info(f"Created MinIO bucket: '{bucket_name}'")
        return True
    except S3Error as e:
        log.error(f"Error checking/creating MinIO bucket '{bucket_name}': {e}")
        raise


def upload_bytes(
    key: str,
    data: bytes,
    content_type: str = "application/pdf",
    bucket_name: str = MINIO_BUCKET,
) -> str:
    """
    Stream in-memory bytes directly to MinIO without touching local disk.
    
    Args:
        key (str): S3 object key (e.g., 'bids/GEM_2025_B_6726924/bid.pdf').
        data (bytes): Raw file bytes in memory.
        content_type (str): MIME type for browser rendering.
        bucket_name (str): S3 bucket name.
        
    Returns:
        str: Stored S3 object key.
    """
    client = get_minio_client()
    ensure_bucket_exists(bucket_name)
    stream = io.BytesIO(data)
    client.put_object(
        bucket_name=bucket_name,
        object_name=key,
        data=stream,
        length=len(data),
        content_type=content_type,
    )
    log.info(f"Uploaded {len(data)} bytes to MinIO: s3://{bucket_name}/{key}")
    return key


def download_bytes(key: str, bucket_name: str = MINIO_BUCKET) -> bytes:
    """
    Download an object from MinIO into in-memory bytes.
    
    Args:
        key (str): S3 object key.
        bucket_name (str): S3 bucket name.
        
    Returns:
        bytes: Raw file contents.
    """
    client = get_minio_client()
    response = None
    try:
        response = client.get_object(bucket_name, key)
        return response.read()
    finally:
        if response:
            response.close()
            response.release_conn()


def upload_file(
    key: str,
    file_path: str,
    content_type: Optional[str] = None,
    bucket_name: str = MINIO_BUCKET,
) -> str:
    """
    Upload a local file on disk to MinIO.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    client = get_minio_client()
    ensure_bucket_exists(bucket_name)
    client.fput_object(
        bucket_name=bucket_name,
        object_name=key,
        file_path=file_path,
        content_type=content_type or "application/octet-stream",
    )
    log.info(f"Uploaded file {file_path} to MinIO: s3://{bucket_name}/{key}")
    return key


def download_file(
    key: str,
    dest_path: str,
    bucket_name: str = MINIO_BUCKET,
) -> str:
    """
    Download an object from MinIO and write it to local disk.
    """
    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    client = get_minio_client()
    client.fget_object(
        bucket_name=bucket_name,
        object_name=key,
        file_path=dest_path,
    )
    log.info(f"Downloaded s3://{bucket_name}/{key} to {dest_path}")
    return dest_path


def get_presigned_url(
    key: str,
    expiry_hours: int = 24,
    bucket_name: str = MINIO_BUCKET,
) -> str:
    """
    Generate an expiring presigned GET URL for secure client downloads.
    
    Args:
        key (str): S3 object key.
        expiry_hours (int): Validity window in hours (default: 24h).
        bucket_name (str): S3 bucket name.
        
    Returns:
        str: Presigned HTTP download URL.
    """
    client = get_minio_client()
    url = client.presigned_get_object(
        bucket_name=bucket_name,
        object_name=key,
        expires=timedelta(hours=expiry_hours),
    )
    return url


def object_exists(key: str, bucket_name: str = MINIO_BUCKET) -> bool:
    """Check if an object exists in the bucket."""
    client = get_minio_client()
    try:
        client.stat_object(bucket_name, key)
        return True
    except S3Error as e:
        if e.code == "NoSuchKey":
            return False
        raise


def list_objects(prefix: str = "", bucket_name: str = MINIO_BUCKET) -> List[str]:
    """List all object keys under a prefix."""
    client = get_minio_client()
    objects = client.list_objects(bucket_name, prefix=prefix, recursive=True)
    return [obj.object_name for obj in objects]
