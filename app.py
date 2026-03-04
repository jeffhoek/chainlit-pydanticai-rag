import os

import chainlit as cl
from openai import AsyncOpenAI
from pydantic_ai import Agent

from config import settings
from rag.agent import Deps, rag_agent
from rag.data_loader import chunk_text, load_data
from rag.embeddings import generate_embeddings_batch
from rag.vector_store import VectorStore

if os.getenv("LANGFUSE_PUBLIC_KEY"):
    from langfuse import get_client
    get_client()
    Agent.instrument_all()


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    expected_username = os.getenv("APP_USERNAME", "admin")
    expected_password = os.getenv("APP_PASSWORD")

    if not expected_password:
        return None

    if username == expected_username and password == expected_password:
        return cl.User(identifier=username)

    return None


def _quick_query_actions() -> list[cl.Action]:
    return [
        cl.Action(name="quick_query", label=label, payload={"query": label})
        for label in settings.action_buttons
    ]


@cl.action_callback("quick_query")
async def on_quick_query(action: cl.Action) -> None:
    query = action.payload["query"]
    deps = cl.user_session.get("deps")
    if deps is None:
        await cl.Message(content="Error: Knowledge base not initialized. Please refresh the page.").send()
        return
    result = await rag_agent.run(query, deps=deps)
    await cl.Message(content=result.output, actions=_quick_query_actions()).send()


@cl.on_chat_start
async def on_chat_start() -> None:
    """Initialize the RAG system on chat start."""
    if settings.azure_storage_account_name:
        source = f"https://{settings.azure_storage_account_name}.blob.core.windows.net/{settings.azure_storage_container_name}/{settings.azure_storage_blob_name}"
    elif settings.s3_bucket:
        source = f"s3://{settings.s3_bucket}/{settings.s3_key}"
    else:
        source = settings.data_path
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
        content=f"Ready! Loaded {len(chunks)} chunks from the knowledge base.",
        actions=_quick_query_actions(),
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
    await cl.Message(content=result.output, actions=_quick_query_actions()).send()
