from pinecone import Pinecone, ServerlessSpec
from typing import Iterator, List, Dict, Any, Optional, Union
from .constants import (
    INFERENCE_DIMENSION,
    PINECONE_INDEX_NAME,
    PINECONE_API_KEY,
    INFERENCE_MODEL,
)
from dotenv import load_dotenv
import logging
import time

load_dotenv()

logger = logging.getLogger(__name__)


class PineconeClient:
    """
    A client for interacting with Pinecone.
    """

    def __init__(self):
        self.pc = Pinecone(api_key=PINECONE_API_KEY)
        # Initialize index after checking/creating
        self.ensure_index_exists()
        desc = self.pc.describe_index(PINECONE_INDEX_NAME)
        self.index = self.pc.Index(
            name=PINECONE_INDEX_NAME,
            host=desc.host,  # Get the proper host from the index description
        )

    def ensure_index_exists(self):
        """
        Check if index exists, create if it doesn't.
        """
        try:
            indexes = self.pc.list_indexes()

            exists = any(index["name"] == PINECONE_INDEX_NAME for index in indexes)
            if exists:
                logger.warning(f"Index {PINECONE_INDEX_NAME} already exists")
                return

            self.create_index()

        except Exception as e:
            logger.error(f"Error checking/creating index: {e}")
            raise

    def create_index(self):
        """
        Create a serverless index with integrated inference.
        """
        try:
            logger.info(f"Creating index {PINECONE_INDEX_NAME}")
            return self.pc.create_index(
                name=PINECONE_INDEX_NAME,
                dimension=INFERENCE_DIMENSION,
                metric="cosine",
                deletion_protection="disabled",  # Consider enabling for production
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
        except Exception as e:
            logger.error(f"Failed to create index: {e}")
            raise

    def generate_embeddings(self, text: str) -> List[float]:
        """
        Generate embeddings for a given text using Pinecone Inference API.

        Parameters:
            text: The text to generate embeddings for.

        Returns:
            List[float]: The embeddings for the text.
        """
        response = self.pc.inference.embed(
            model=INFERENCE_MODEL,
            inputs=[text],
            parameters={"input_type": "passage", "truncate": "END"},
        )
        # if the response is empty, raise an error
        if not response.data:
            raise ValueError(f"Failed to generate embeddings for text: {text}")
        return response.data[0].values

    def upsert_records(
        self, records: List[Dict[str, Any]], namespace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Upsert records into the Pinecone index.

        Parameters:
            records: List of records to upsert.
            namespace: Optional namespace to upsert into.

        Returns:
            Dict[str, Any]: The response from Pinecone.
        """
        try:
            vectors = []
            for record in records:
                if "text" in record:
                    vector_values = self.generate_embeddings(record["text"])

                    # Claude can generate a document id so use it if it exists
                    record_id = record.get("id")

                    metadata = record.get("metadata", {})
                    metadata["text"] = record["text"]

                    vectors.append((record_id, vector_values, metadata))

            return self.index.upsert(vectors=vectors, namespace=namespace)

        except Exception as e:
            logger.error(f"Error upserting records: {e}")
            raise

    def search_records(
        self,
        query: Union[str, List[float]],
        top_k: int = 10,
        namespace: Optional[str] = None,
        filter: Optional[Dict] = None,
        include_metadata: bool = True,
    ) -> Dict[str, Any]:
        """
        Search records using integrated inference.

        Parameters:
            query: The query to search for.
            top_k: The number of results to return.
            namespace: Optional namespace to search in.
            filter: Optional filter to apply to the search.
            include_metadata: Whether to include metadata in the search results.

        Returns:
            Dict[str, Any]: The search results from Pinecone.
        """
        try:
            # If query is text, use our custom function to get embeddings
            if isinstance(query, str):
                vector = self.generate_embeddings(query)
            else:
                vector = query

            return self.index.query(
                vector=vector,
                top_k=top_k,
                namespace=namespace,
                include_metadata=include_metadata,
                filter=filter,
            )
        except Exception as e:
            logger.error(f"Error searching records: {e}")
            raise

    def delete_records(
        self, ids: List[str], namespace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Delete records by ID

        Parameters:
            ids: List of record IDs to delete
            namespace: Optional namespace to delete from
        """
        try:
            return self.index.delete(ids=ids, namespace=namespace)
        except Exception as e:
            logger.error(f"Error deleting records: {e}")
            raise

    def fetch_records(
        self, ids: List[str], namespace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Fetch specific records by ID

        Parameters:
            ids: List of record IDs to fetch
            namespace: Optional namespace to fetch from
        """
        try:
            return self.index.fetch(ids=ids, namespace=namespace)
        except Exception as e:
            logger.error(f"Error fetching records: {e}")
            raise

    def list_records(
        self,
        prefix: Optional[str] = None,
        limit: int = 100,
        namespace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List records in the index using pagination.

        Parameters:
            prefix: Optional prefix to filter records by.
            limit: The number of records to return per page.
            namespace: Optional namespace to list records from.
        """
        try:
            # Using list_paginated for single-page results
            response = self.index.list_paginated(
                prefix=prefix, limit=limit, namespace=namespace
            )

            # Add debug logging
            logger.debug(f"Pinecone list_paginated response: {response}")

            # Check if response is None
            if response is None:
                logger.error("Received None response from Pinecone list_paginated")
                return {"vectors": [], "namespace": namespace, "pagination_token": None}

            # Handle the case where vectors might be None
            vectors = response.vectors if hasattr(response, "vectors") else []

            return {
                "vectors": [
                    {
                        "id": getattr(v, "id", None),
                        "metadata": getattr(v, "metadata", {}),
                    }
                    for v in vectors
                ],
                "namespace": getattr(response, "namespace", namespace),
                "pagination_token": getattr(response.pagination, "next", None)
                if hasattr(response, "pagination")
                else None,
            }
        except Exception as e:
            logger.error(f"Error listing records: {e}")
            # Return empty result instead of raising
            return {"vectors": [], "namespace": namespace, "pagination_token": None}

    # Optional: Add a method for iterating through all pages
    def iterate_records(
        self,
        prefix: Optional[str] = None,
        limit: int = 100,
        namespace: Optional[str] = None,
    ) -> Iterator[List[str]]:
        """
        Iterate through all records using the generator-based list method.

        Parameters:
            prefix: Optional prefix to filter records by.
            limit: The number of records to return per page.
            namespace: Optional namespace to list records from.
        """
        try:
            for ids in self.index.list(prefix=prefix, limit=limit, namespace=namespace):
                yield ids
        except Exception as e:
            logger.error(f"Error iterating records: {e}")
            raise

    def get_index_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the index.

        Returns:
            Dict[str, Any]: The statistics about the index.
        """
        try:
            return self.index.describe_index_stats()
        except Exception as e:
            logger.error(f"Error getting index stats: {e}")
            raise
