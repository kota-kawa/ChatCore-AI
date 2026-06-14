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


# 日本語: ManualChunk に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ManualChunk.
@dataclass
class ManualChunk:
    heading: str
    content: str
    file_title: str


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

# 日本語: strip frontmatter に関する処理の入口です。
# English: Entry point for logic related to strip frontmatter.
def _strip_frontmatter(text: str) -> tuple[str, dict[str, str]]:
    meta: dict[str, str] = {}
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not text.startswith("---"):
        return text, meta
    end = text.find("\n---", 3)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if end == -1:
        return text, meta
    for line in text[3:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return text[end + 4:].lstrip("\n"), meta


# 日本語: split into chunks に関する処理の入口です。
# English: Entry point for logic related to split into chunks.
def _split_into_chunks(body: str, file_title: str) -> list[ManualChunk]:
    chunks: list[ManualChunk] = []
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
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

# 日本語: tokenize に関する処理の入口です。
# English: Entry point for logic related to tokenize.
def _tokenize(text: str) -> list[str]:
    """ASCII は単語分割、CJK 文字はバイグラム＋ユニグラムに展開する。"""
    tokens: list[str] = []
    text = text.lower()
    tokens.extend(re.findall(r"[a-z0-9]+", text))
    cjk_chars = [c for c in text if unicodedata.category(c) in ("Lo", "Ll") and ord(c) > 0x2E7F]
    cjk_str = "".join(cjk_chars)
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for i in range(len(cjk_str) - 1):
        tokens.append(cjk_str[i:i + 2])
    tokens.extend(cjk_chars)
    return tokens


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

# 日本語: compute chunks hash に関する処理の入口です。
# English: Entry point for logic related to compute chunks hash.
def _compute_chunks_hash(chunks: list[ManualChunk]) -> str:
    combined = "\n---\n".join(f"{c.heading}\n{c.content}" for c in chunks)
    return hashlib.sha256(combined.encode()).hexdigest()


# 日本語: fetch embeddings from api の取得処理を担当します。
# English: Handle fetching for fetch embeddings from api.
def _fetch_embeddings_from_api(texts: list[str]) -> np.ndarray:
    from openai import OpenAI
    api_key = os.environ.get("OPENAI_API_KEY", "")
    client = OpenAI(api_key=api_key)
    all_embeddings: list[list[float]] = []
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
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


# 日本語: normalize rows の正規化処理を担当します。
# English: Handle normalizing for normalize rows.
def _normalize_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    return mat / np.maximum(norms, 1e-10)


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

# 日本語: ManualRagIndex に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to ManualRagIndex.
class ManualRagIndex:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, manual_dir: Path = MANUAL_DIR) -> None:
        self._chunks: list[ManualChunk] = []
        self._bm25 = None
        self._chunk_embeddings: np.ndarray | None = None  # shape (n, EMBEDDING_DIMS), L2-normalized

        chunks = self._load_chunks(manual_dir)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
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

    # 日本語: load chunks の読み込み処理を担当します。
    # English: Handle loading for load chunks.
    @staticmethod
    def _load_chunks(manual_dir: Path) -> list[ManualChunk]:
        chunks: list[ManualChunk] = []
        # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
        # English: Process each target item in order and accumulate the needed result.
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

    # 日本語: build bm25 の組み立て処理を担当します。
    # English: Handle building for build bm25.
    @staticmethod
    def _build_bm25(chunks: list[ManualChunk]):
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("rank_bm25 not installed; BM25 disabled.")
            return None
        tokenized = [_tokenize(f"{c.heading} {c.content}") for c in chunks]
        return BM25Okapi(tokenized)

    # 日本語: bm25 search に関する処理の入口です。
    # English: Entry point for logic related to bm25 search.
    def _bm25_search(self, query: str, top_k: int) -> tuple[list[ManualChunk], list[float]]:
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self._bm25 is None:
            return [], []
        tokens = _tokenize(query)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not tokens:
            return [], []
        all_scores: list[float] = self._bm25.get_scores(tokens).tolist()
        ranked = sorted(range(len(all_scores)), key=lambda i: all_scores[i], reverse=True)
        top_chunks = [self._chunks[i] for i in ranked[:top_k] if all_scores[i] > 0]
        return top_chunks, all_scores

    # 日本語: is bm25 weak に関する処理の入口です。
    # English: Entry point for logic related to is bm25 weak.
    def _is_bm25_weak(self, all_scores: list[float]) -> bool:
        top = max(all_scores) if all_scores else 0.0
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if top <= 0:
            return True
        positive = [s for s in all_scores if s > 0]
        mean_pos = sum(positive) / len(positive) if positive else 0.0
        return (top / (mean_pos + 1e-8)) < BM25_MIN_DISCRIMINATION_RATIO

    # ------------------------------------------------------------------
    # Vector embeddings
    # ------------------------------------------------------------------

    # 日本語: load or build embeddings の読み込み処理を担当します。
    # English: Handle loading for load or build embeddings.
    def _load_or_build_embeddings(self, chunks: list[ManualChunk]) -> np.ndarray | None:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not api_key:
            logger.info("OPENAI_API_KEY not set; vector search disabled.")
            return None

        chunks_hash = _compute_chunks_hash(chunks)

        # Try loading from cache
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
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

    # 日本語: embed query に関する処理の入口です。
    # English: Entry point for logic related to embed query.
    def _embed_query(self, query: str) -> np.ndarray | None:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not api_key:
            return None
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
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

    # 日本語: vector search に関する処理の入口です。
    # English: Entry point for logic related to vector search.
    def _vector_search(self, query: str, top_k: int) -> list[ManualChunk]:
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self._chunk_embeddings is None:
            return []
        query_vec = self._embed_query(query)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if query_vec is None:
            return []
        scores = self._chunk_embeddings @ query_vec
        ranked = np.argsort(-scores)[:top_k]
        return [self._chunks[int(i)] for i in ranked]

    # ------------------------------------------------------------------
    # Public search
    # ------------------------------------------------------------------

    # 日本語: search に関する処理の入口です。
    # English: Entry point for logic related to search.
    def search(self, query: str, top_k: int = TOP_K) -> list[ManualChunk]:
        bm25_chunks, all_scores = self._bm25_search(query, top_k)

        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not self._is_bm25_weak(all_scores):
            logger.debug("RAG method=bm25 query=%s", query[:60])
            return bm25_chunks

        logger.debug("RAG BM25 weak → trying vector search. query=%s", query[:60])
        vec_chunks = self._vector_search(query, top_k)
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if vec_chunks:
            return vec_chunks

        return bm25_chunks


# ---------------------------------------------------------------------------
# Singleton & public API
# ---------------------------------------------------------------------------

_index: ManualRagIndex | None = None


# 日本語: get manual rag index の取得処理を担当します。
# English: Handle fetching for get manual rag index.
def get_manual_rag_index() -> ManualRagIndex:
    global _index
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if _index is None:
        _index = ManualRagIndex()
    return _index


# 日本語: search manual に関する処理の入口です。
# English: Entry point for logic related to search manual.
def search_manual(query: str, top_k: int = TOP_K) -> str:
    """クエリに関連するマニュアルチャンクを検索して文字列で返す。"""
    chunks = get_manual_rag_index().search(query, top_k=top_k)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not chunks:
        return ""
    parts = ["【操作マニュアル（参考情報）】"]
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for chunk in chunks:
        parts.append(f"\n### {chunk.heading}\n{chunk.content}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Query routing: マニュアル検索が必要かどうかを判定する
# ---------------------------------------------------------------------------

# アプリ固有の語彙 — これらが含まれれば操作質問の可能性が高い
_APP_TERMS = re.compile(
    r"チャット|チャットルーム|ルーム"
    r"|プロンプト"
    r"|タスク"
    r"|メモ"
    r"|設定|プロフィール|アバター"
    r"|ログイン|ログアウト|サインイン|サインアップ|アカウント|認証"
    r"|パスキー|passkey"
    r"|テーマ|ダークモード|ライトモード|ダーク|ライト"
    r"|共有|シェア"
    r"|ブックマーク|いいね|リスト"
    r"|エージェント|aiエージェント"
    r"|このアプリ|chatcore|chat.core",
    re.IGNORECASE,
)

# 使い方・困りごとを示すパターン — 操作説明が必要な質問
_HELP_PATTERNS = re.compile(
    r"方法|やり方|手順|使い方|やりかた"
    r"|どうやって|どうすれば|どうしたら|どうやれば"
    r"|できますか|できません|できない|できる[？?]"
    r"|わからない|わかりません|教えて|説明して"
    r"|エラー|問題|困って|失敗|うまくいかない|動かない"
    r"|どこ[でにから]?|どの(ページ|画面|ボタン|メニュー|タブ|場所)"
    r"|とは何|とは[？?]|何ですか|何[？?]$"
    r"|how\s+to|what\s+is|where\s+(is|can|do)",
    re.IGNORECASE,
)

# 純粋なコンテンツ生成依頼 — アプリ操作と無関係なタスク
_GENERATION_PATTERNS = re.compile(
    r"翻訳(して|お願い|してください)"
    r"|要約(して|お願い|してください)"
    r"|(まとめ|まとめて|まとめてください)"
    r"|(書いて|書いてください|書いてほしい)"
    r"|(作って|作成して|生成して)(ください|ほしい)?"
    r"|(直して|修正して|校正して)(ください|ほしい)?"
    r"|計算(して|してください)"
    r"|変換(して|してください)",
    re.IGNORECASE,
)

# 会話的な短い返答 — 検索は不要
_CONVERSATIONAL_REPLIES = re.compile(
    r"^(こんにちは|こんばんは|おはようございます?|おはよう"
    r"|ありがとう|ありがとうございます|ありがとうございました"
    r"|助かりました|参考になりました|よくわかりました|理解しました"
    r"|なるほど|そうですね|なるほどです"
    r"|はい|いいえ|わかりました|了解(です)?|おけ"
    r"|ok|okay|hello|hi|thanks|thank\s+you)[!！。、]*$",
    re.IGNORECASE,
)


# 日本語: needs manual search に関する処理の入口です。
# English: Entry point for logic related to needs manual search.
def needs_manual_search(query: str) -> bool:
    """ユーザーのメッセージがアプリ操作マニュアルの検索を必要とするか判定する。

    判定フロー:
      1. 短い会話返答 → NO
      2. アプリ固有語を含む → YES
      3. 使い方・困りごとパターンを含む → YES
      4. コンテンツ生成依頼のみ（アプリ語なし） → NO
      5. 上記いずれも非該当 → YES（フェイルセーフ）
    """
    q = query.strip()

    # 5文字未満または純粋な会話返答
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if len(q) < 5 or _CONVERSATIONAL_REPLIES.match(q):
        return False

    # アプリ固有の語彙が含まれる
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if _APP_TERMS.search(q):
        return True

    # 使い方・困りごとパターン
    if _HELP_PATTERNS.search(q):
        return True

    # アプリ語なしのコンテンツ生成依頼
    if _GENERATION_PATTERNS.search(q):
        return False

    # 判断できない場合はフェイルセーフで検索する
    return True
