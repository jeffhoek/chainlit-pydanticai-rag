from pathlib import Path

import aioboto3
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient

from config import settings


async def load_data() -> str:
    """Load text: Azure Blob → S3 → local (first configured source wins)."""
    if settings.azure_storage_account_name and settings.azure_storage_container_name:
        return await load_from_blob()
    elif settings.s3_bucket and settings.s3_key:
        return await load_from_s3()
    else:
        return load_from_local(settings.data_path)


async def load_from_blob() -> str:
    """Fetch raw text from Azure Blob Storage using Managed Identity."""
    account_url = f"https://{settings.azure_storage_account_name}.blob.core.windows.net"
    async with DefaultAzureCredential() as credential:
        async with BlobServiceClient(account_url, credential=credential) as client:
            blob_client = client.get_blob_client(
                container=settings.azure_storage_container_name,
                blob=settings.azure_storage_blob_name,
            )
            download = await blob_client.download_blob()
            content = await download.readall()
            return content.decode("utf-8").replace("\r\n", "\n")


def load_from_local(data_path: str) -> str:
    """Read and concatenate all files from a local directory."""
    path = Path(data_path)
    if not path.is_dir():
        raise FileNotFoundError(f"Local data directory not found: {data_path}")
    files = sorted(path.iterdir())
    if not files:
        raise FileNotFoundError(f"No files found in: {data_path}")
    parts = []
    for f in files:
        if f.is_file():
            parts.append(f.read_text(encoding="utf-8"))
    if not parts:
        raise FileNotFoundError(f"No readable files in: {data_path}")
    return "\n\n".join(parts).replace("\r\n", "\n")


async def load_from_s3() -> str:
    """Fetch raw text from S3."""
    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )

    async with session.client("s3") as s3:
        response = await s3.get_object(Bucket=settings.s3_bucket, Key=settings.s3_key)
        content = await response["Body"].read()
        text = content.decode("utf-8")
        # Normalize line endings (Windows \r\n -> Unix \n)
        return text.replace("\r\n", "\n")


def chunk_text(text: str) -> list[str]:
    """Split text into chunks by paragraph (double newline).

    Preserves semantic units by splitting on paragraph breaks rather than
    fixed character counts.
    """
    if not text:
        return []

    # Split on double newlines (paragraph breaks)
    raw_chunks = text.split("\n\n")

    # Clean up chunks: strip whitespace, filter empty
    return [chunk.strip() for chunk in raw_chunks if chunk.strip()]
