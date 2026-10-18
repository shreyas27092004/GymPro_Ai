# app/kb/retrieval.py
from datetime import date, datetime, timedelta
import json
import logging
from typing import Any
import chromadb
from ..settings import settings

logger = logging.getLogger(__name__)

DEFAULT_FROZEN_DATE = date(2026, 10, 16)


def get_chroma_client(chroma_path: str | None = None) -> chromadb.PersistentClient:
    target_path = chroma_path or settings.chroma_path
    return chromadb.PersistentClient(path=target_path)


def query_kb(
    collection_name: str,
    query: str,
    filters: dict[str, Any] | None = None,
    top_k: int = 5,
    as_of_date: date | None = None,
    chroma_path: str | None = None,
) -> list[dict[str, Any]]:
    """
    Queries a ChromaDB collection with optional metadata filters, similarity ranking,
    and a 12-month staleness exclusion for injury protocols.
    """
    client = get_chroma_client(chroma_path)
    try:
        collection = client.get_collection(name=collection_name)
    except Exception:
        # Collection not created yet or empty
        return []

    where_clause = None
    if filters:
        # Build simple equality filters if single key, or $and if multiple
        items = list(filters.items())
        if len(items) == 1:
            where_clause = {items[0][0]: items[0][1]}
        elif len(items) > 1:
            where_clause = {"$and": [{k: v} for k, v in items]}

    # Query collection
    try:
        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_clause,
        )
    except Exception as e:
        logger.warning(f"Error querying Chroma collection {collection_name}: {e}")
        return []

    passages: list[dict[str, Any]] = []
    current_date = as_of_date or DEFAULT_FROZEN_DATE

    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]

    for doc_id, text_content, meta in zip(ids, docs, metas):
        meta = meta or {}

        # 12-month staleness rule for injury protocols (Section 11)
        if collection_name == "injury_protocols":
            rev_str = meta.get("reviewed_at")
            if rev_str:
                try:
                    rev_date = date.fromisoformat(str(rev_str))
                    if (current_date - rev_date).days > 365:
                        # Stale (> 12 months) docs are excluded from retrieval
                        continue
                except Exception:
                    pass

        # Unpack JSON strings in metadata if present
        unpacked_meta: dict[str, Any] = {}
        for k, v in meta.items():
            if isinstance(v, str) and (v.startswith("[") or v.startswith("{")):
                try:
                    unpacked_meta[k] = json.loads(v)
                    continue
                except Exception:
                    pass
            unpacked_meta[k] = v

        passages.append(
            {
                "id": doc_id,
                "collection": collection_name,
                "content": text_content,
                "metadata": unpacked_meta,
                "citation": {"source": "kb", "collection": collection_name, "id": doc_id},
            }
        )

    return passages


def wrap_retrieved_context(passages: list[dict[str, Any]]) -> str:
    """
    Wraps retrieved passages in XML <retrieved_context> tags marked as untrusted reference facts.
    """
    if not passages:
        return ""

    blocks: list[str] = []
    for p in passages:
        cid = p.get("id", "unknown")
        coll = p.get("collection", "kb")
        content = p.get("content", "").strip()
        blocks.append(f'<retrieved_context id="{cid}" collection="{coll}">\n{content}\n</retrieved_context>')

    return "\n\n".join(blocks)
