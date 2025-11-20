"""
Vector index for semantic search using OpenAI embeddings.

Current implementation:
- Uses OpenAI text-embedding-3-small (1536 dimensions)
- In-memory storage with numpy
- Cosine similarity for search

Production upgrades (TODO):
- Persist embeddings to avoid recomputation
- Migrate to Chroma/Pinecone for scale
- Add hybrid search (keyword + semantic)
"""

import logging
import numpy as np
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from openai import OpenAI

from src.core.domain_models import IndexableDocument
from src.storage.embedding_store import EmbeddingStore


logger = logging.getLogger(__name__)


@dataclass
class VectorHit:
    """
    A single search result from vector index.

    Attributes:
        doc_id: Original document ID
        grant_id: Parent grant ID
        score: Similarity score (0-1, higher is better)
        chunk_index: Which chunk of the document (for long docs)
        source_url: Citable URL
        text: The chunk text
        metadata: Additional metadata
    """
    doc_id: str
    grant_id: Optional[str]
    score: float
    chunk_index: int
    source_url: str
    text: str
    metadata: Dict[str, Any]


class VectorIndex:
    """
    Semantic search index using OpenAI embeddings.

    Features:
    - Real embeddings via text-embedding-3-small
    - Cosine similarity search
    - Document chunking with overlap
    - In-memory storage (migrate to Chroma later)

    Usage:
        index = VectorIndex()
        index.index_documents(docs)
        hits = index.query("quantum computing", top_k=10)
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        chunk_size: int = 1200,
        chunk_overlap: int = 200,
        db_path: str = "grants.db",
        use_persistent_storage: bool = True,
    ):
        """
        Initialize vector index with persistent storage.

        Args:
            model: OpenAI embedding model name
            chunk_size: Maximum characters per chunk
            chunk_overlap: Overlap between consecutive chunks
            db_path: Path to database for persistent storage
            use_persistent_storage: Enable persistent embedding storage

        Raises:
            ValueError: If OPENAI_API_KEY not set
        """
        import os
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable not set. "
                "Required for embedding generation."
            )

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.use_persistent_storage = use_persistent_storage

        # In-memory storage
        self._vectors: List[np.ndarray] = []
        self._texts: List[str] = []
        self._metadatas: List[Dict[str, Any]] = []
        self._emb_ids: List[str] = []

        # Persistent storage
        self.embedding_store = None
        if use_persistent_storage:
            self.embedding_store = EmbeddingStore(db_path)
            self._load_from_storage()

        logger.info(
            f"VectorIndex initialized: model={model}, "
            f"persistent={use_persistent_storage}, "
            f"loaded={len(self._vectors)} embeddings"
        )

    def _load_from_storage(self) -> None:
        """Load all embeddings from persistent storage into memory."""
        if not self.embedding_store:
            return

        logger.info("Loading embeddings from database...")

        embeddings = self.embedding_store.load_all()

        for emb_id, vector, text, metadata in embeddings:
            self._emb_ids.append(emb_id)
            self._vectors.append(vector)
            self._texts.append(text)
            self._metadatas.append(metadata)

        logger.info(f"✓ Loaded {len(embeddings)} embeddings from database")

    def index_documents(self, docs: List[IndexableDocument]) -> None:
        """
        Chunk and index documents with persistent storage.

        Process:
        1. Chunk each document's text
        2. Generate embeddings for each chunk (skip if exists in DB)
        3. Store vectors in memory and database

        Args:
            docs: List of IndexableDocument objects
        """
        logger.info(f"Indexing {len(docs)} documents...")

        total_chunks = 0
        failed_chunks = 0
        skipped_chunks = 0
        batch_embeddings = []

        for doc in docs:
            if not doc.text or not doc.text.strip():
                continue

            # Chunk the document
            chunks = self._chunk_text(doc.text)

            for chunk_idx, chunk_text in enumerate(chunks):
                emb_id = f"{doc.id}_chunk_{chunk_idx}"

                # Skip if already exists in persistent storage
                if self.embedding_store and self.embedding_store.exists(emb_id):
                    skipped_chunks += 1
                    continue

                try:
                    # Generate embedding
                    embedding = self._embed(chunk_text)

                    # Store in memory
                    self._emb_ids.append(emb_id)
                    self._vectors.append(embedding)
                    self._texts.append(chunk_text)

                    metadata = {
                        "doc_id": doc.id,
                        "grant_id": doc.grant_id,
                        "source_url": doc.source_url,
                        "doc_type": doc.doc_type,
                        "scope": doc.scope,
                        "chunk_index": chunk_idx,
                        "total_chunks": len(chunks),
                    }
                    self._metadatas.append(metadata)

                    # Prepare for batch database save
                    if self.embedding_store:
                        batch_embeddings.append({
                            "emb_id": emb_id,
                            "doc_id": doc.id,
                            "grant_id": doc.grant_id,
                            "chunk_index": chunk_idx,
                            "vector": embedding,
                            "text": chunk_text,
                            "source_url": doc.source_url,
                            "doc_type": doc.doc_type,
                            "scope": doc.scope,
                        })

                    total_chunks += 1

                except Exception as e:
                    logger.error(f"Failed to embed chunk from {doc.id}: {e}")
                    failed_chunks += 1

        # Save batch to database
        if self.embedding_store and batch_embeddings:
            self.embedding_store.save_batch(batch_embeddings)

        logger.info(
            f"✓ Indexed {total_chunks} new chunks, "
            f"skipped {skipped_chunks} existing, "
            f"{failed_chunks} failed"
        )

    def query(
        self,
        query_text: str,
        top_k: int = 10,
        filter_grant_ids: Optional[List[str]] = None,
        filter_scope: Optional[str] = None,
    ) -> List[VectorHit]:
        """
        Search for similar document chunks using semantic similarity.

        Args:
            query_text: Search query
            top_k: Number of results to return
            filter_grant_ids: Optional list of grant IDs to filter by
            filter_scope: Optional scope filter ("competition" or "global")

        Returns:
            List of VectorHit objects, sorted by similarity (descending)
        """
        if not self._vectors:
            logger.warning("Vector index is empty. Call index_documents() first.")
            return []

        # Generate query embedding
        query_embedding = self._embed(query_text)

        # Stack all vectors into matrix for efficient computation
        vectors_matrix = np.vstack(self._vectors)

        # Compute cosine similarities (dot product since vectors are normalized)
        similarities = vectors_matrix @ query_embedding

        # Apply filters
        valid_indices = []
        for idx, meta in enumerate(self._metadatas):
            # Filter by grant IDs
            if filter_grant_ids and meta.get("grant_id") not in filter_grant_ids:
                continue

            # Filter by scope
            if filter_scope and meta.get("scope") != filter_scope:
                continue

            valid_indices.append(idx)

        # Get top K from valid indices
        if valid_indices:
            valid_sims = [(idx, similarities[idx]) for idx in valid_indices]
            valid_sims.sort(key=lambda x: x[1], reverse=True)
            top_indices = [idx for idx, _ in valid_sims[:top_k]]
        else:
            # No filters applied, use all
            top_indices = np.argsort(similarities)[::-1][:top_k]

        # Convert to VectorHit objects
        hits = []
        for idx in top_indices:
            meta = self._metadatas[idx]
            score = float(similarities[idx])

            hits.append(
                VectorHit(
                    doc_id=meta["doc_id"],
                    grant_id=meta.get("grant_id"),
                    score=score,
                    chunk_index=meta.get("chunk_index", 0),
                    source_url=meta["source_url"],
                    text=self._texts[idx],
                    metadata=meta,
                )
            )

        logger.debug(f"Query returned {len(hits)} hits from {len(self._vectors)} total chunks")
        return hits

    def _embed(self, text: str) -> np.ndarray:
        """
        Generate embedding vector for text using OpenAI API.

        Args:
            text: Text to embed

        Returns:
            Normalized embedding vector (L2 norm = 1)
        """
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text,
            )

            # Extract embedding and convert to numpy array
            embedding = np.array(response.data[0].embedding, dtype=np.float32)

            # Normalize for cosine similarity (makes dot product = cosine)
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            return embedding

        except Exception as e:
            logger.error(f"Embedding API call failed: {e}")
            # Return zero vector as fallback (will have similarity ~0 with everything)
            return np.zeros(1536, dtype=np.float32)

    def _chunk_text(self, text: str) -> List[str]:
        """
        Split text into overlapping chunks.

        Uses character-based chunking. Production should use token-based
        chunking to respect sentence boundaries.

        Args:
            text: Text to chunk

        Returns:
            List of text chunks
        """
        text = text.strip()

        if len(text) <= self.chunk_size:
            return [text]

        chunks = []
        start = 0

        while start < len(text):
            end = start + self.chunk_size
            chunk = text[start:end]
            chunks.append(chunk)

            if end >= len(text):
                break

            # Move start position back by overlap amount
            start = end - self.chunk_overlap

        return chunks

    def get_stats(self) -> Dict[str, Any]:
        """
        Get index statistics.

        Returns:
            Dict with index stats (size, model, etc.)
        """
        return {
            "total_chunks": len(self._vectors),
            "model": self.model,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
        }
