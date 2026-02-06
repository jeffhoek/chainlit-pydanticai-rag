import aioboto3

from config import settings


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
