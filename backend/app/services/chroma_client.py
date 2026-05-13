# Chroma 单例客户端 + 进程内锁，减轻多路并发打开同一 persist 目录导致的 HNSW/compactor 损坏与报错。

from __future__ import annotations

import logging
import threading
from pathlib import Path

import chromadb
from chromadb.config import Settings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_CLIENT: chromadb.ClientAPI | None = None
_CLIENT_ROOT: str | None = None
_EMBEDDINGS: OllamaEmbeddings | None = None

# 与旧版报错文案兼容（大小写不敏感）
_CORRUPT_MARKERS = (
    "hnsw",
    "compactor",
    "segment reader",
    "backfill",
    "loading hnsw",
    "error executing plan",
)


def chroma_persist_root() -> str:
    # 与 get_travel_details.Config / persist_chroma / chroma_rag_kb 使用同一目录。
    return str(Path(__file__).resolve().parents[2] / "chroma_db")


def _is_corrupt_index_message(msg: str) -> bool:
    m = (msg or "").lower()
    return any(x in m for x in _CORRUPT_MARKERS)


def _get_embeddings() -> OllamaEmbeddings:
    global _EMBEDDINGS
    with _LOCK:
        if _EMBEDDINGS is None:
            _EMBEDDINGS = OllamaEmbeddings(model="nomic-embed-text")
        return _EMBEDDINGS


def _get_chroma_client() -> chromadb.ClientAPI:
    global _CLIENT, _CLIENT_ROOT
    root = chroma_persist_root()
    with _LOCK:
        if _CLIENT is not None and _CLIENT_ROOT == root:
            return _CLIENT
        Path(root).mkdir(parents=True, exist_ok=True)
        _CLIENT = chromadb.PersistentClient(
            path=root,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True,
            ),
        )
        _CLIENT_ROOT = root
        logger.info("Chroma PersistentClient ready path=%s", root)
        return _CLIENT


def reset_chroma_client_for_tests() -> None:
    # 仅测试用：清空进程内单例。
    global _CLIENT, _CLIENT_ROOT, _EMBEDDINGS
    with _LOCK:
        _CLIENT = None
        _CLIENT_ROOT = None
        _EMBEDDINGS = None


def _delete_collection_quiet(name: str) -> None:
    try:
        _get_chroma_client().delete_collection(name)
        logger.warning("Chroma collection deleted (repair): %s", name)
    except Exception as exc:
        logger.debug("delete_collection %s: %s", name, exc)


def repair_chroma_collection(collection_name: str) -> None:
    # 删除损坏集合，由下次 LangChain 访问时按 embedding 维度自动重建。
    with _LOCK:
        _delete_collection_quiet(collection_name)


def get_langchain_chroma(collection_name: str) -> Chroma:
    # 同一 persist 根目录、共享 PersistentClient，避免每次 invoke 新建客户端。
    with _LOCK:
        return Chroma(
            client=_get_chroma_client(),
            collection_name=collection_name,
            embedding_function=_get_embeddings(),
            create_collection_if_not_exists=True,
        )


def chroma_similarity_search(
    collection_name: str,
    query: str,
    *,
    k: int = 3,
    repair_on_corrupt: bool = True,
) -> list[Document]:
    # 带锁的相似度检索；若命中 HNSW/compactor 类错误则删除集合并重试一次（空结果直至重新入库）。
    q = (query or "").strip()
    if not q:
        return []

    def _run() -> list[Document]:
        with _LOCK:
            vs = get_langchain_chroma(collection_name)
            retriever = vs.as_retriever(search_kwargs={"k": k})
            return list(retriever.invoke(q))

    try:
        return _run()
    except Exception as first:
        msg = str(first)
        if not repair_on_corrupt or not _is_corrupt_index_message(msg):
            raise
        logger.exception("Chroma search failed, attempting collection repair: %s", msg[:500])
        repair_chroma_collection(collection_name)
        try:
            return _run()
        except Exception as second:
            logger.exception("Chroma search failed after repair: %s", str(second)[:500])
            raise second from first


def chroma_add_documents(
    collection_name: str,
    documents: list[Document],
    ids: list[str],
) -> None:
    # 写入与检索共用锁，降低并发写读与 compactor 冲突概率。
    if not documents:
        return
    with _LOCK:
        vs = get_langchain_chroma(collection_name)
        vs.add_documents(documents=documents, ids=ids)
