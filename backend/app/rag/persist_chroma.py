from __future__ import annotations
from datetime import datetime, timezone
from langchain_core.documents import Document
from backend.app.rag.models import TravelListing
from backend.app.services.chroma_client import chroma_add_documents
from backend.app.tools.get_travel_details import Config

def write_listings_to_chroma(items: list[TravelListing]) -> int:
    """把旅游套餐写入与 vector_store_retriever 共用的 Chroma 集合。"""
    if not items:
        return 0

    docs: list[Document] = []
    ids: list[str] = []
    uploaded_at = datetime.now(timezone.utc).isoformat()
    for it in items:
        docs.append(
            Document(
                page_content=it.chroma_page_content()[:8000],
                metadata={
                    "source": it.source_site,
                    "source_id": it.source_id,
                    "departure": it.departure,
                    "price": it.price,
                    "url": it.url or "",
                    "uploaded_at": uploaded_at,
                    "source_file": it.raw_title or it.source_id,
                },
            )
        )
        ids.append(f"{it.source_site}_{it.source_id}"[:512])
    try:
        chroma_add_documents(Config.collection_name, docs, ids)
    except Exception:
        return -1
    return len(docs)
