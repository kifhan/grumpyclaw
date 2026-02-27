"""Heartbeat: sync sources (e.g. Google Docs), then LLM decides HEARTBEAT_OK or a short notification."""

from __future__ import annotations

import os
import sys


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from grumpyclaw.adapters.google_docs import GoogleDocsAdapter
    from grumpyclaw.llm.client import chat
    from grumpyclaw.memory.indexer import Indexer

    # 1) Sync Google Docs journal
    folder_id = os.environ.get("GOOGLE_DOCS_FOLDER_ID") or None
    creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "").strip()
    if creds_path:
        try:
            adapter = GoogleDocsAdapter(credentials_path=creds_path)
            indexer = Indexer()
            n_chunks = adapter.sync_to_indexer(indexer, folder_id=folder_id)
            docs_sync_status = f"Google Docs journal synced ({n_chunks} chunks indexed)."
        except Exception as e:
            docs_sync_status = f"Google Docs sync failed: {e}"
            print(f"Heartbeat: {docs_sync_status}", file=sys.stderr)
    else:
        docs_sync_status = "Google Docs sync skipped (GOOGLE_CREDENTIALS_PATH not set)."

    # 2) Stub other sources (v1: no Gmail/Calendar adapters yet)
    context = f"{docs_sync_status} No other sources configured (Gmail/Calendar stubbed)."

    # 3) LLM: HEARTBEAT_OK or one short user notification
    system = (
        "You are a proactive assistant. Given the following context, respond with either "
        "HEARTBEAT_OK (if there is nothing to report) or a single short user-facing notification "
        "(e.g. '15 min until meeting – prep doc empty'). Be concise."
    )
    try:
        reply = chat([{"role": "system", "content": system}, {"role": "user", "content": context}])
    except Exception as e:
        print("Heartbeat: LLM error:", e, file=sys.stderr)
        return 1

    print(reply.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
