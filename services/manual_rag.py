from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MANUAL_DIR = Path(__file__).parent.parent / "docs" / "manual"
MAX_CHUNK_CHARS = 600
TOP_K = 3


@dataclass
class ManualChunk:
    heading: str
    content: str
    file_title: str


def _strip_frontmatter(text: str) -> tuple[str, dict[str, str]]:
    """YAMLフロントマターを除去し、(本文, メタ) を返す。"""
    meta: dict[str, str] = {}
    if not text.startswith("---"):
        return text, meta
    end = text.find("\n---", 3)
    if end == -1:
        return text, meta
    frontmatter = text[3:end]
    for line in frontmatter.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return text[end + 4:].lstrip("\n"), meta


def _split_into_chunks(body: str, file_title: str) -> list[ManualChunk]:
    """## 見出し単位でチャンクに分割する。"""
    chunks: list[ManualChunk] = []
    sections = re.split(r"\n(?=## )", body)
    for section in sections:
        if not section.strip():
            continue
        lines = section.strip().splitlines()
        heading = lines[0].lstrip("#").strip() if lines else file_title
        content = "\n".join(lines[1:]).strip()
        if not content:
            continue
        # 長すぎるチャンクは ### 単位でさらに分割
        if len(content) > MAX_CHUNK_CHARS:
            sub_sections = re.split(r"\n(?=### )", content)
            for sub in sub_sections:
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


def _tokenize(text: str) -> list[str]:
    """ASCII は単語分割、CJK 文字はバイグラムで分割する。"""
    tokens: list[str] = []
    text = text.lower()

    # ASCII 単語
    ascii_tokens = re.findall(r"[a-z0-9]+", text)
    tokens.extend(ascii_tokens)

    # CJK 文字列をバイグラムに分解
    cjk_chars = [c for c in text if unicodedata.category(c) in ("Lo", "Ll") and ord(c) > 0x2E7F]
    cjk_str = "".join(cjk_chars)
    for i in range(len(cjk_str) - 1):
        tokens.append(cjk_str[i:i + 2])
    # 単独文字もユニグラムとして追加（短いクエリ対策）
    tokens.extend(cjk_chars)

    return tokens


class ManualRagIndex:
    def __init__(self, manual_dir: Path = MANUAL_DIR) -> None:
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("rank_bm25 not installed; manual RAG disabled.")
            self._chunks: list[ManualChunk] = []
            self._bm25 = None
            return

        chunks: list[ManualChunk] = []
        for md_file in sorted(manual_dir.glob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
                body, meta = _strip_frontmatter(text)
                file_title = meta.get("title", md_file.stem)
                chunks.extend(_split_into_chunks(body, file_title))
            except Exception:
                logger.exception("Failed to load manual file: %s", md_file)

        if not chunks:
            logger.warning("No manual chunks loaded from %s", manual_dir)
            self._chunks = []
            self._bm25 = None
            return

        tokenized = [_tokenize(f"{c.heading} {c.content}") for c in chunks]
        self._chunks = chunks
        self._bm25 = BM25Okapi(tokenized)
        logger.info("Manual RAG index built: %d chunks from %s", len(chunks), manual_dir)

    def search(self, query: str, top_k: int = TOP_K) -> list[ManualChunk]:
        if self._bm25 is None or not self._chunks:
            return []
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        # スコアが 0 のチャンクは除外
        return [self._chunks[i] for i in ranked[:top_k] if scores[i] > 0]


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
