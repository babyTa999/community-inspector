"""Vector search integration with Qdrant for knowledge base."""
from __future__ import annotations

import hashlib
import json
from typing import Any

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams
except ImportError:
    QdrantClient = None

from sqlalchemy.orm import Session

try:
    from crm.models import KnowledgeBase
except ImportError:
    from models import KnowledgeBase


class VectorSearch:
    """Vector search for knowledge base using Qdrant."""

    def __init__(self, url: str = "http://localhost:6333", collection_name: str = "knowledge_base"):
        """Initialize vector search.

        Args:
            url: Qdrant server URL
            collection_name: Name of the collection
        """
        self.url = url
        self.collection_name = collection_name
        self.client: QdrantClient | None = None

        if QdrantClient is not None:
            try:
                self.client = QdrantClient(url=url)
                self._ensure_collection()
            except Exception as e:
                print(f"Warning: Could not connect to Qdrant: {e}")
                self.client = None

    def _ensure_collection(self) -> None:
        """Ensure collection exists."""
        if self.client is None:
            return

        try:
            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]

            if self.collection_name not in collection_names:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=768, distance=Distance.COSINE),
                )
                print(f"Created Qdrant collection: {self.collection_name}")
        except Exception as e:
            print(f"Warning: Could not create collection: {e}")

    def is_available(self) -> bool:
        """Check if vector search is available."""
        return self.client is not None

    def _get_embedding(self, text: str) -> list[float] | None:
        """Get embedding vector from Ollama.

        Args:
            text: Text to embed

        Returns:
            Embedding vector or None if failed
        """
        try:
            import httpx

            response = httpx.post(
                "http://localhost:11434/api/embeddings",
                json={
                    "model": "nomic-embed-text",
                    "prompt": text,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("embedding")
        except Exception as e:
            print(f"Error getting embedding: {e}")
            return None

    def add_document(
        self,
        doc_id: str,
        title: str,
        content: str,
        metadata: dict | None = None,
    ) -> bool:
        """Add document to vector store.

        Args:
            doc_id: Document ID
            title: Document title
            content: Document content
            metadata: Additional metadata

        Returns:
            True if successful
        """
        if self.client is None:
            return False

        # Combine title and content for embedding
        text = f"{title}\n\n{content}"
        embedding = self._get_embedding(text)

        if embedding is None:
            return False

        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                        id=doc_id,
                        vector=embedding,
                        payload={
                            "id": doc_id,
                            "title": title,
                            "content": content,
                            **(metadata or {}),
                        },
                    )
                ],
            )
            return True
        except Exception as e:
            print(f"Error adding document: {e}")
            return False

    def search(
        self,
        query: str,
        limit: int = 5,
        score_threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Search for similar documents.

        Args:
            query: Search query
            limit: Maximum number of results
            score_threshold: Minimum similarity score

        Returns:
            List of matching documents with scores
        """
        if self.client is None:
            return []

        embedding = self._get_embedding(query)
        if embedding is None:
            return []

        try:
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=embedding,
                limit=limit,
                score_threshold=score_threshold,
            )

            return [
                {
                    "id": r.payload.get("id"),
                    "title": r.payload.get("title"),
                    "content": r.payload.get("content"),
                    "score": r.score,
                    **{k: v for k, v in r.payload.items() if k not in ["id", "title", "content"]},
                }
                for r in results
            ]
        except Exception as e:
            print(f"Error searching: {e}")
            return []

    def delete_document(self, doc_id: str) -> bool:
        """Delete document from vector store.

        Args:
            doc_id: Document ID

        Returns:
            True if successful
        """
        if self.client is None:
            return False

        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=[doc_id],
            )
            return True
        except Exception as e:
            print(f"Error deleting document: {e}")
            return False


# Global instance
_vector_search: VectorSearch | None = None


def get_vector_search(url: str = "http://localhost:6333") -> VectorSearch:
    """Get or create global vector search instance."""
    global _vector_search
    if _vector_search is None:
        _vector_search = VectorSearch(url=url)
    return _vector_search


def sync_knowledge_base_to_vector_db(db: Session) -> int:
    """Sync all knowledge base entries to vector database.

    Args:
        db: Database session

    Returns:
        Number of documents synced
    """
    vector_search = get_vector_search()
    if not vector_search.is_available():
        print("Vector search not available, skipping sync")
        return 0

    kb_entries = db.query(KnowledgeBase).all()
    synced = 0

    for entry in kb_entries:
        if vector_search.add_document(
            doc_id=entry.id,
            title=entry.title,
            content=entry.content,
            metadata={
                "tags": entry.tags,
                "source_issue_id": entry.source_issue_id,
                "usage_count": entry.usage_count,
            },
        ):
            synced += 1

    return synced
