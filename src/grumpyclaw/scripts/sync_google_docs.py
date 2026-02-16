"""Sync Google Docs (e.g. journal) into the local knowledge base."""

from __future__ import annotations

import os
import sys


def main() -> int:
    # Optional: load .env if python-dotenv is available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from grumpyclaw.adapters.google_docs import GoogleDocsAdapter
    from grumpyclaw.memory.indexer import Indexer

    folder_id = os.environ.get("GOOGLE_DOCS_FOLDER_ID") or None
    adapter = GoogleDocsAdapter()
    indexer = Indexer()
    try:
        n = adapter.sync_to_indexer(indexer, folder_id=folder_id)
    except Exception as e:
        print("Error syncing Google Docs:", e, file=sys.stderr)
        return 1
    print(f"Indexed {n} chunks from Google Docs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
