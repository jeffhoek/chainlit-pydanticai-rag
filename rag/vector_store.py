import numpy as np
from numpy.typing import NDArray


class VectorStore:
    """In-memory vector store using NumPy with cosine similarity search."""

    def __init__(self) -> None:
        self.documents: list[str] = []
        self.embeddings: NDArray[np.float32] | None = None

    def add_documents(
        self, documents: list[str], embeddings: list[list[float]]
    ) -> None:
        """Store documents with their embeddings."""
        self.documents.extend(documents)
        new_embeddings = np.array(embeddings, dtype=np.float32)
        norms = np.linalg.norm(new_embeddings, axis=1, keepdims=True)
        new_embeddings = new_embeddings / norms

        if self.embeddings is None:
            self.embeddings = new_embeddings
        else:
            self.embeddings = np.vstack([self.embeddings, new_embeddings])

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[str]:
        """Find top-k most similar documents using cosine similarity."""
        if self.embeddings is None or len(self.documents) == 0:
            return []

        query = np.array(query_embedding, dtype=np.float32)

        query_norm = query / np.linalg.norm(query)
        similarities = self.embeddings @ query_norm

        # Get top-k indices
        top_indices = np.argsort(similarities)[::-1][:top_k]

        return [self.documents[i] for i in top_indices]
