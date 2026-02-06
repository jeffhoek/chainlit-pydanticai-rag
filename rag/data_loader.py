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
        return content.decode("utf-8")


def chunk_text(
    text: str,
    chunk_size: int = settings.chunk_size,
    chunk_overlap: int = settings.chunk_overlap,
) -> list[str]:
    """Split text into overlapping chunks."""
    if not text:
        return []

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        if chunk.strip():
            chunks.append(chunk.strip())

        start = end - chunk_overlap

    return chunks
