import os

import chainlit as cl
from openai import AsyncOpenAI

from config import settings
from rag.agent import Deps, rag_agent
from rag.data_loader import chunk_text, load_data
from rag.embeddings import generate_embeddings_batch
from rag.vector_store import VectorStore


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    expected_username = os.getenv("APP_USERNAME", "admin")
    expected_password = os.getenv("APP_PASSWORD")

    if not expected_password:
        return None

    if username == expected_username and password == expected_password:
        return cl.User(identifier=username)

    return None


@cl.on_chat_start
async def on_chat_start() -> None:
    """Initialize the RAG system on chat start."""
    source = f"s3://{settings.s3_bucket}/{settings.s3_key}" if settings.s3_bucket else settings.data_path
    await cl.Message(content=f"Loading knowledge base from {source}...").send()

    # Initialize OpenAI client for embeddings
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

    # Load and chunk data
    raw_text = await load_data()
    chunks = chunk_text(raw_text)

    # Generate embeddings for all chunks
    embeddings = await generate_embeddings_batch(openai_client, chunks)

    # Create and populate vector store
    vector_store = VectorStore()
    vector_store.add_documents(chunks, embeddings)

    # Store dependencies in session
    deps = Deps(openai_client=openai_client, vector_store=vector_store)
    cl.user_session.set("deps", deps)

    await cl.Message(
        content=f"Ready! Loaded {len(chunks)} chunks from the knowledge base."
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Handle incoming messages."""
    deps = cl.user_session.get("deps")

    if deps is None:
        await cl.Message(
            content="Error: Knowledge base not initialized. Please refresh the page."
        ).send()
        return

    result = await rag_agent.run(message.content, deps=deps)
    await cl.Message(content=result.output).send()
