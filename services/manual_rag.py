from __future__ import annotations

import hashlib
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

MANUAL_DIR = Path(__file__).parent.parent / "docs" / "manual"
MAX_CHUNK_CHARS = 600
TOP_K = 3

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 512
EMBEDDING_BATCH_SIZE = 100

# BM25 discrimination ratio: top_score / mean_positive_score.
# Below this value BM25 is considered too weak and vector search is used instead.
# Empirically determined: good queries score 5-9x, weak queries score 1-3x.
BM25_MIN_DISCRIMINATION_RATIO = 4.0

_CACHE_FILE = MANUAL_DIR / ".embeddings.npz"
_CACHE_HASH_FILE = MANUAL_DIR / ".embeddings_hash.txt"


@dataclass
class ManualChunk:
    heading: str
    content: str
    file_title: str


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

def _strip_frontmatter(text: str) -> tuple[str, dict[str, str]]:
    meta: dict[str, str] = {}
    if not text.startswith("---"):
        return text, meta
    end = text.find("\n---", 3)
    if end == -1:
        return text, meta
    for line in text[3:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return text[end + 4:].lstrip("\n"), meta


def _split_into_chunks(body: str, file_title: str) -> list[ManualChunk]:
    chunks: list[ManualChunk] = []
    for section in re.split(r"\n(?=## )", body):
        if not section.strip():
            continue
        lines = section.strip().splitlines()
        heading = lines[0].lstrip("#").strip() if lines else file_title
        content = "\n".join(lines[1:]).strip()
        if not content:
            continue
        if len(content) > MAX_CHUNK_CHARS:
            for sub in re.split(r"\n(?=### )", content):
                sub = sub.strip()
                if not sub:
                    continue
                sub_lines = sub.splitlines()
                sub_heading = sub_lines[0].lstrip("#").strip() if sub_lines else heading
                sub_content = "\n".join(sub_lines[1:]).strip()
                if sub_content:
                    chunks.append(ManualChunk(
                        heading=f"{heading} > {sub_heading}",
                        content=sub_content[:MAX_CHUNK_CHARS],
                        file_title=file_title,
                    ))
        else:
            chunks.append(ManualChunk(heading=heading, content=content, file_title=file_title))
    return chunks


# ---------------------------------------------------------------------------
# Tokenizer (BM25 用)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """ASCII は単語分割、CJK 文字はバイグラム＋ユニグラムに展開する。"""
    tokens: list[str] = []
    text = text.lower()
    tokens.extend(re.findall(r"[a-z0-9]+", text))
    cjk_chars = [c for c in text if unicodedata.category(c) in ("Lo", "Ll") and ord(c) > 0x2E7F]
    cjk_str = "".join(cjk_chars)
    for i in range(len(cjk_str) - 1):
        tokens.append(cjk_str[i:i + 2])
    tokens.extend(cjk_chars)
    return tokens


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def _compute_chunks_hash(chunks: list[ManualChunk]) -> str:
    combined = "\n---\n".join(f"{c.heading}\n{c.content}" for c in chunks)
    return hashlib.sha256(combined.encode()).hexdigest()


def _fetch_embeddings_from_api(texts: list[str]) -> np.ndarray:
    from openai import OpenAI
    api_key = os.environ.get("OPENAI_API_KEY", "")
    client = OpenAI(api_key=api_key)
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i:i + EMBEDDING_BATCH_SIZE]
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=batch,
            dimensions=EMBEDDING_DIMS,
        )
        sorted_data = sorted(response.data, key=lambda x: x.index)
        all_embeddings.extend(item.embedding for item in sorted_data)
    return np.array(all_embeddings, dtype=np.float32)


def _normalize_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    return mat / np.maximum(norms, 1e-10)


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

class ManualRagIndex:
    def __init__(self, manual_dir: Path = MANUAL_DIR) -> None:
        self._chunks: list[ManualChunk] = []
        self._bm25 = None
        self._chunk_embeddings: np.ndarray | None = None  # shape (n, EMBEDDING_DIMS), L2-normalized

        chunks = self._load_chunks(manual_dir)
        if not chunks:
            logger.warning("No manual chunks loaded from %s", manual_dir)
            return

        self._chunks = chunks
        self._bm25 = self._build_bm25(chunks)
        self._chunk_embeddings = self._load_or_build_embeddings(chunks)
        logger.info(
            "ManualRagIndex ready: %d chunks, vector=%s",
            len(chunks),
            "enabled" if self._chunk_embeddings is not None else "disabled",
        )

    # ------------------------------------------------------------------
    # Chunk loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_chunks(manual_dir: Path) -> list[ManualChunk]:
        chunks: list[ManualChunk] = []
        for md_file in sorted(manual_dir.glob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
                body, meta = _strip_frontmatter(text)
                file_title = meta.get("title", md_file.stem)
                chunks.extend(_split_into_chunks(body, file_title))
            except Exception:
                logger.exception("Failed to load manual file: %s", md_file)
        return chunks

    # ------------------------------------------------------------------
    # BM25
    # ------------------------------------------------------------------

    @staticmethod
    def _build_bm25(chunks: list[ManualChunk]):
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("rank_bm25 not installed; BM25 disabled.")
            return None
        tokenized = [_tokenize(f"{c.heading} {c.content}") for c in chunks]
        return BM25Okapi(tokenized)

    def _bm25_search(self, query: str, top_k: int) -> tuple[list[ManualChunk], list[float]]:
        if self._bm25 is None:
            return [], []
        tokens = _tokenize(query)
        if not tokens:
            return [], []
        all_scores: list[float] = self._bm25.get_scores(tokens).tolist()
        ranked = sorted(range(len(all_scores)), key=lambda i: all_scores[i], reverse=True)
        top_chunks = [self._chunks[i] for i in ranked[:top_k] if all_scores[i] > 0]
        return top_chunks, all_scores

    def _is_bm25_weak(self, all_scores: list[float]) -> bool:
        top = max(all_scores) if all_scores else 0.0
        if top <= 0:
            return True
        positive = [s for s in all_scores if s > 0]
        mean_pos = sum(positive) / len(positive) if positive else 0.0
        return (top / (mean_pos + 1e-8)) < BM25_MIN_DISCRIMINATION_RATIO

    # ------------------------------------------------------------------
    # Vector embeddings
    # ------------------------------------------------------------------

    def _load_or_build_embeddings(self, chunks: list[ManualChunk]) -> np.ndarray | None:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            logger.info("OPENAI_API_KEY not set; vector search disabled.")
            return None

        chunks_hash = _compute_chunks_hash(chunks)

        # Try loading from cache
        if _CACHE_FILE.exists() and _CACHE_HASH_FILE.exists():
            try:
                cached_hash = _CACHE_HASH_FILE.read_text().strip()
                if cached_hash == chunks_hash:
                    data = np.load(_CACHE_FILE)
                    logger.info("Loaded embedding cache: %d vectors", len(data["embeddings"]))
                    return _normalize_rows(data["embeddings"].astype(np.float32))
            except Exception:
                logger.warning("Embedding cache corrupted; rebuilding.")

        # Build via OpenAI API
        try:
            texts = [f"{c.heading}\n{c.content}" for c in chunks]
            embeddings = _fetch_embeddings_from_api(texts)
            np.savez_compressed(_CACHE_FILE, embeddings=embeddings)
            _CACHE_HASH_FILE.write_text(chunks_hash)
            logger.info("Built and cached %d embeddings", len(embeddings))
            return _normalize_rows(embeddings)
        except Exception:
            logger.exception("Failed to build embeddings; vector search disabled.")
            return None

    def _embed_query(self, query: str) -> np.ndarray | None:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return None
        try:
            from openai import OpenAI
            response = OpenAI(api_key=api_key).embeddings.create(
                model=EMBEDDING_MODEL,
                input=query,
                dimensions=EMBEDDING_DIMS,
            )
            vec = np.array(response.data[0].embedding, dtype=np.float32)
            norm = np.linalg.norm(vec)
            return vec / max(norm, 1e-10)
        except Exception:
            logger.exception("Query embedding failed.")
            return None

    def _vector_search(self, query: str, top_k: int) -> list[ManualChunk]:
        if self._chunk_embeddings is None:
            return []
        query_vec = self._embed_query(query)
        if query_vec is None:
            return []
        scores = self._chunk_embeddings @ query_vec
        ranked = np.argsort(-scores)[:top_k]
        return [self._chunks[int(i)] for i in ranked]

    # ------------------------------------------------------------------
    # Public search
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = TOP_K) -> list[ManualChunk]:
        bm25_chunks, all_scores = self._bm25_search(query, top_k)

        if not self._is_bm25_weak(all_scores):
            logger.debug("RAG method=bm25 query=%s", query[:60])
            return bm25_chunks

        logger.debug("RAG BM25 weak → trying vector search. query=%s", query[:60])
        vec_chunks = self._vector_search(query, top_k)
        if vec_chunks:
            return vec_chunks

        return bm25_chunks


# ---------------------------------------------------------------------------
# Singleton & public API
# ---------------------------------------------------------------------------

_index: ManualRagIndex | None = None


def get_manual_rag_index() -> ManualRagIndex:
    global _index
    if _index is None:
        _index = ManualRagIndex()
    return _index


def search_manual(query: str, top_k: int = TOP_K) -> str:
    """クエリに関連するマニュアルチャンクを検索して文字列で返す。"""
    chunks = get_manual_rag_index().search(query, top_k=top_k)
    if not chunks:
        return ""
    parts = ["【操作マニュアル（参考情報）】"]
    for chunk in chunks:
        parts.append(f"\n### {chunk.heading}\n{chunk.content}")
    return "\n".join(parts)
