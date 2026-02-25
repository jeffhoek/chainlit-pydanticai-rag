from pathlib import Path

import aioboto3

from config import settings


async def load_data() -> str:
    """Load text from S3 if configured, otherwise from local data/ directory."""
    if settings.s3_bucket and settings.s3_key:
        return await load_from_s3()
    else:
        return load_from_local(settings.data_path)


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
