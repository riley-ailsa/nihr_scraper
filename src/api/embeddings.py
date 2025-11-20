"""
Embeddings API for creating text embeddings using OpenAI.
"""

import os
import logging
from typing import List, Optional
import numpy as np
from openai import OpenAI

logger = logging.getLogger(__name__)


class EmbeddingsClient:
    """Client for creating text embeddings."""

    def __init__(self, model: str = "text-embedding-3-small"):
        """
        Initialize embeddings client.

        Args:
            model: OpenAI embedding model to use
                  - text-embedding-3-small: Cheaper, good quality (default)
                  - text-embedding-3-large: Higher quality, more expensive
        """
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable not set. "
                "Get your key from: https://platform.openai.com/api-keys"
            )

        self.client = OpenAI(api_key=api_key)
        self.model = model
        logger.info(f"Embeddings client initialized with model: {model}")

    def create_embedding(self, text: str) -> Optional[np.ndarray]:
        """
        Create embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Numpy array of embeddings or None if failed
        """
        try:
            # Truncate text if too long (max ~8000 tokens)
            max_chars = 30000  # Conservative limit
            if len(text) > max_chars:
                text = text[:max_chars]
                logger.debug(f"Truncated text to {max_chars} chars")

            response = self.client.embeddings.create(
                model=self.model,
                input=text
            )

            embedding = response.data[0].embedding
            return np.array(embedding, dtype=np.float32)

        except Exception as e:
            logger.error(f"Failed to create embedding: {e}")
            return None

    def create_embeddings_batch(self, texts: List[str]) -> List[Optional[np.ndarray]]:
        """
        Create embeddings for multiple texts.

        OpenAI API supports batch requests for efficiency.

        Args:
            texts: List of texts to embed

        Returns:
            List of numpy arrays (or None for failed embeddings)
        """
        if not texts:
            return []

        embeddings = []

        # Process in batches (OpenAI recommends max 2048 embeddings per request)
        batch_size = 100  # Conservative batch size

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]

            # Truncate texts if needed
            truncated_batch = []
            max_chars = 30000
            for text in batch:
                if len(text) > max_chars:
                    truncated_batch.append(text[:max_chars])
                    logger.debug(f"Truncated text to {max_chars} chars")
                else:
                    truncated_batch.append(text)

            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=truncated_batch
                )

                for data in response.data:
                    embedding = np.array(data.embedding, dtype=np.float32)
                    embeddings.append(embedding)

                logger.info(f"Created {len(batch)} embeddings (batch {i//batch_size + 1})")

            except Exception as e:
                logger.error(f"Failed to create batch embeddings: {e}")
                # Add None for failed embeddings
                embeddings.extend([None] * len(batch))

        return embeddings


# Singleton instance
_client = None


def get_embeddings_client() -> EmbeddingsClient:
    """Get or create the global embeddings client."""
    global _client
    if _client is None:
        _client = EmbeddingsClient()
    return _client


def create_embedding(text: str) -> Optional[np.ndarray]:
    """
    Create embedding for a single text.

    Convenience function using the global client.

    Args:
        text: Text to embed

    Returns:
        Numpy array of embeddings or None if failed
    """
    client = get_embeddings_client()
    return client.create_embedding(text)


def create_embeddings_batch(texts: List[str]) -> List[Optional[np.ndarray]]:
    """
    Create embeddings for multiple texts.

    Convenience function using the global client.

    Args:
        texts: List of texts to embed

    Returns:
        List of numpy arrays (or None for failed embeddings)
    """
    client = get_embeddings_client()
    return client.create_embeddings_batch(texts)