"""
Cloudflare R2 dosya depolama servisi (S3-uyumlu).
Production'da AWS S3 ile de çalışır — sadece endpoint değişir.
"""

import os
import logging
from pathlib import Path
from io import BytesIO
import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

_client = None
BUCKET = os.getenv("R2_BUCKET", "talentforge-cvs")


def get_r2_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=os.getenv("R2_ENDPOINT"),
            aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        logger.info("✅ Cloudflare R2 bağlantısı hazır")
    return _client


def upload_cv(cv_id: str, file_path: Path, original_name: str) -> str:
    """CV dosyasını R2'ye yükler, object_name döner"""
    client = get_r2_client()
    suffix = Path(original_name).suffix
    object_name = f"cvs/{cv_id}{suffix}"

    client.upload_file(
        Filename=str(file_path),
        Bucket=BUCKET,
        Key=object_name,
        ExtraArgs={"ContentType": "application/octet-stream"},
    )
    logger.info(f"✅ CV R2'ye yüklendi: {object_name}")
    return object_name


def download_cv(object_name: str) -> bytes:
    """R2'den CV dosyasını indirir"""
    client = get_r2_client()
    buf = BytesIO()
    client.download_fileobj(BUCKET, object_name, buf)
    return buf.getvalue()


def delete_cv(object_name: str):
    """R2'den CV siler (KVKK silme hakkı)"""
    client = get_r2_client()
    client.delete_object(Bucket=BUCKET, Key=object_name)
    logger.info(f"🗑️ CV R2'den silindi: {object_name}")