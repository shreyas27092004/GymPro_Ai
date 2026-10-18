# app/kb/ingest.py
import argparse
from datetime import date
import json
import logging
from pathlib import Path
from typing import Any
import chromadb
import yaml
from ..settings import settings

logger = logging.getLogger(__name__)

COLLECTIONS = [
    "injury_protocols",
    "exercises",
    "nutrition_science",
    "gym_policies",
]


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extracts YAML front matter and body from markdown content."""
    if not content.startswith("---"):
        return {}, content.strip()

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content.strip()

    fm_text = parts[1]
    body = parts[2].strip()
    try:
        meta = yaml.safe_load(fm_text) or {}
    except Exception as e:
        logger.warning(f"Error parsing frontmatter: {e}")
        meta = {}

    return meta, body


def sanitize_metadata(meta: dict[str, Any]) -> dict[str, str | int | float | bool]:
    """ChromaDB metadata supports str, int, float, and bool. Flatten lists/dicts/dates."""
    clean: dict[str, str | int | float | bool] = {}
    for k, v in meta.items():
        if v is None:
            continue
        elif isinstance(v, (str, int, float, bool)):
            clean[k] = v
        elif isinstance(v, (date,)):
            clean[k] = v.isoformat()
        elif isinstance(v, (list, dict)):
            clean[k] = json.dumps(v)
        else:
            clean[k] = str(v)
    return clean


def ingest_corpus(corpus_dir: Path | None = None, chroma_path: str | None = None) -> dict[str, int]:
    """
    Ingests markdown corpus files into persistent ChromaDB collections.
    Idempotent by document id.
    """
    if corpus_dir is None:
        # Default: backend/kb/corpus
        corpus_dir = Path(__file__).resolve().parent.parent.parent / "kb" / "corpus"

    target_chroma = chroma_path or settings.chroma_path
    client = chromadb.PersistentClient(path=target_chroma)

    counts: dict[str, int] = {}

    for coll_name in COLLECTIONS:
        coll_dir = corpus_dir / coll_name
        collection = client.get_or_create_collection(
            name=coll_name,
            metadata={"description": f"GymPro KB collection for {coll_name}"},
        )

        if not coll_dir.exists():
            counts[coll_name] = 0
            continue

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, str | int | float | bool]] = []

        for p in coll_dir.glob("*.md"):
            raw_text = p.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(raw_text)

            doc_id = str(meta.get("id") or p.stem)
            meta["collection"] = coll_name
            meta["filename"] = p.name
            clean_meta = sanitize_metadata(meta)

            ids.append(doc_id)
            documents.append(body)
            metadatas.append(clean_meta)

        if ids:
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )
            counts[coll_name] = len(ids)
        else:
            counts[coll_name] = 0

    return counts


def main():
    parser = argparse.ArgumentParser(description="Ingest GymPro starter corpus into ChromaDB")
    parser.add_argument("--corpus-dir", type=str, default=None, help="Path to corpus directory")
    parser.add_argument("--chroma-path", type=str, default=None, help="Path to ChromaDB storage")
    args = parser.parse_args()

    c_dir = Path(args.corpus_dir) if args.corpus_dir else None
    res = ingest_corpus(corpus_dir=c_dir, chroma_path=args.chroma_path)
    print(f"Ingestion complete: {res}")


if __name__ == "__main__":
    main()
