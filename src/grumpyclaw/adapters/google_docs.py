"""Google Docs adapter: list and fetch document content, sync to indexer."""

from __future__ import annotations

import os
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Scopes: read Docs and list Drive files (for folder listing)
SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _read_paragraph_element(element: dict) -> str:
    """Extract text from a ParagraphElement."""
    text_run = element.get("textRun")
    if not text_run:
        return ""
    return text_run.get("content", "")


def _read_structural_elements(elements: list[dict]) -> str:
    """Recursively extract text from structural elements (paragraphs, tables, TOC)."""
    parts = []
    for value in elements or []:
        if "paragraph" in value:
            for elem in value["paragraph"].get("elements", []):
                parts.append(_read_paragraph_element(elem))
        elif "table" in value:
            for row in value["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    parts.append(_read_structural_elements(cell.get("content", [])))
        elif "tableOfContents" in value:
            parts.append(_read_structural_elements(value["tableOfContents"].get("content", [])))
    return "".join(parts)


def _extract_doc_text(doc: dict) -> str:
    """Extract plain text from a Docs API document object."""
    body = doc.get("body") or {}
    content = body.get("content") or []
    return _read_structural_elements(content)


class GoogleDocsAdapter:
    """Fetch Google Docs (e.g. journal) and sync content to the knowledge indexer."""

    def __init__(self, credentials_path: str | Path | None = None):
        path = credentials_path or os.environ.get("GOOGLE_CREDENTIALS_PATH", "")
        if not path:
            raise ValueError(
                "Set GOOGLE_CREDENTIALS_PATH or pass credentials_path to GoogleDocsAdapter"
            )
        self.credentials_path = Path(path)
        self._creds = None

    def _get_credentials(self):
        """OAuth2 credentials; uses token file next to credentials for refresh."""
        if self._creds and self._creds.valid:
            return self._creds
        token_path = self.credentials_path.parent / "google_token.json"
        if token_path.exists():
            self._creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if not self._creds or not self._creds.valid:
            if self._creds and self._creds.expired and self._creds.refresh_token:
                self._creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), SCOPES
                )
                self._creds = flow.run_local_server(port=0)
            if token_path:
                token_path.parent.mkdir(parents=True, exist_ok=True)
                with open(token_path, "w") as f:
                    f.write(self._creds.to_json())
        return self._creds

    def _docs_service(self):
        return build("docs", "v1", credentials=self._get_credentials())

    def _drive_service(self):
        return build("drive", "v3", credentials=self._get_credentials())

    def list_docs(
        self,
        folder_id: str | None = None,
        mime_type: str = "application/vnd.google-apps.document",
        page_size: int = 100,
    ) -> list[dict]:
        """
        List Google Docs. If folder_id is set (e.g. GOOGLE_DOCS_FOLDER_ID), only docs in that folder.
        Returns list of {id, name} dicts.
        """
        drive = self._drive_service()
        q_parts = [f"mimeType = '{mime_type}'"]
        if folder_id:
            q_parts.append(f"'{folder_id}' in parents")
        query = " and ".join(q_parts)
        files: list[dict] = []
        page_token: str | None = None
        while True:
            results = (
                drive.files()
                .list(
                    q=query,
                    pageSize=page_size,
                    pageToken=page_token,
                    fields="nextPageToken, files(id, name)",
                )
                .execute()
            )
            files.extend(results.get("files", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break
        return files

    def get_doc_content(self, doc_id: str) -> str:
        """Fetch a single document and return its plain text."""
        docs = self._docs_service()
        doc = docs.documents().get(documentId=doc_id).execute()
        return _extract_doc_text(doc)

    def fetch_journal_docs(
        self,
        folder_id: str | None = None,
    ) -> list[dict]:
        """
        List docs (optionally in folder_id) and fetch each body. Returns list of
        {id, title, text} for indexing.
        """
        folder_id = folder_id or os.environ.get("GOOGLE_DOCS_FOLDER_ID") or None
        files = self.list_docs(folder_id=folder_id)
        out = []
        for f in files:
            doc_id = f["id"]
            name = f.get("name", "")
            try:
                text = self.get_doc_content(doc_id)
            except Exception as e:
                # Skip inaccessible docs
                out.append({"id": doc_id, "title": name, "text": "", "error": str(e)})
                continue
            out.append({"id": doc_id, "title": name, "text": text})
        return out

    def sync_to_indexer(self, indexer, folder_id: str | None = None) -> int:
        """
        Fetch all journal docs and index them. Returns number of chunks indexed.
        """
        docs = self.fetch_journal_docs(folder_id=folder_id)
        # Drop docs that had errors and no text
        to_index = [
            {"id": d["id"], "title": d["title"], "text": d["text"]}
            for d in docs
            if d.get("text", "").strip()
        ]
        return indexer.index_documents(to_index, source_type="google_docs")
