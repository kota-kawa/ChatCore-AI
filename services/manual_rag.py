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


# 日本語: マニュアルデータ内の1つのテキストチャンクを表すデータクラス。
# English: Data class representing a single text chunk extracted from the manual docs.
@dataclass
class ManualChunk:
    heading: str
    content: str
    file_title: str


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

# 日本語: Markdownファイルの先頭にあるFrontmatter(メタデータ)部分を取り除き、メタ情報辞書と本文テキストを返します。
# English: Strip the YAML frontmatter from the beginning of Markdown text, returning the body and meta dictionary.
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


# 日本語: マニュアルの本文テキストをセクション（見出し）ごとに適切な文字数でチャンク分割します。
# English: Split the manual body text into sections (headings) of appropriate character length chunks.
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

# 日本語: BM25検索用に、テキストを単語（ASCII）や文字バイグラム＋ユニグラム（CJK）にトークナイズします。
# English: Tokenize text for BM25 search, splitting ASCII into words and CJK into bigrams/unigrams.
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

# 日本語: 全チャンクの見出しと本文から一意のハッシュ値を計算します（キャッシュの変更検知用）。
# English: Compute a unique SHA256 hash of all chunks content to detect cache staleness.
def _compute_chunks_hash(chunks: list[ManualChunk]) -> str:
    combined = "\n---\n".join(f"{c.heading}\n{c.content}" for c in chunks)
    return hashlib.sha256(combined.encode()).hexdigest()


# 日本語: OpenAI APIを利用して、バッチ処理でテキストの埋め込みベクトルを取得します。
# English: Retrieve text embedding vectors in batches using the OpenAI API.
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


# 日本語: 埋め込みベクトルの行方向のノルムを1に正規化（L2正規化）します（コサイン類似度計算用）。
# English: Normalize embedding matrix rows to unit length (L2 normalization) for cosine similarity.
def _normalize_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    return mat / np.maximum(norms, 1e-10)


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

# 日本語: 操作マニュアルデータに対するインデックス管理クラス。BM25検索とベクトル検索を組み合わせたハイブリッドRAGをサポートします。
# English: Index class for managing operation manuals. Supports hybrid RAG combining BM25 and vector search.
class ManualRagIndex:
    # 日本語: マニュアルファイルを読み込み、BM25インデックスと埋め込みベクトルを構築して初期化します。
    # English: Load manual files and initialize BM25 and embedding vector indexes.
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

    # 日本語: マニュアルディレクトリ配下のすべてのMarkdownファイルを読み込み、チャンク化します。
    # English: Read and chunk all Markdown files in the manual directory.
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

    # 日本語: rank_bm25ライブラリを用いてBM25検索オブジェクトを構築します。
    # English: Build a BM25Okapi search object using the rank_bm25 library.
    @staticmethod
    def _build_bm25(chunks: list[ManualChunk]):
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("rank_bm25 not installed; BM25 disabled.")
            return None
        tokenized = [_tokenize(f"{c.heading} {c.content}") for c in chunks]
        return BM25Okapi(tokenized)

    # 日本語: BM25アルゴリズムを用いてクエリに関連するチャンクを検索します。
    # English: Search manual chunks using the BM25 algorithm.
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

    # 日本語: BM25検索結果の最高スコアと平均スコアの比率をもとに、BM25の検索精度が不十分かどうかを判定します。
    # English: Assess if BM25 results are too weak/ambiguous based on the ratio of top score to positive mean score.
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

    # 日本語: 埋め込みベクトルのキャッシュを読み込みます。ない場合はOpenAI APIを使用して新規作成して保存します。
    # English: Load cached vector embeddings, or build them via OpenAI API and cache them if not present.
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

    # 日本語: OpenAI APIを使用して、ユーザーの検索クエリを埋め込みベクトルに変換します。
    # English: Convert user search query into an embedding vector via OpenAI API.
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

    # 日本語: コサイン類似度を用いて、クエリベクトルに最も類似するチャンクを検索します。
    # English: Search for chunks most semantically similar to the query vector using cosine similarity.
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

    # 日本語: BM25検索を実行し、精度が不十分な場合（または弱い場合）はベクトル検索を併用して類似チャンクを返します。
    # English: Perform BM25 search, falling back to semantic vector search if BM25 results are weak.
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


# 日本語: マニュアルRAGインデックスのシングルトンインスタンスを取得・初期化します。
# English: Retrieve or initialize the singleton instance of ManualRagIndex.
def get_manual_rag_index() -> ManualRagIndex:
    global _index
    if _index is None:
        _index = ManualRagIndex()
    return _index


# 日本語: クエリに類似するマニュアル情報を検索し、プロンプト挿入用のフォーマットテキストとして返します。
# English: Search the manual index and return formatted text of matching sections for LLM context.
def search_manual(query: str, top_k: int = TOP_K) -> str:
    """クエリに関連するマニュアルチャンクを検索して文字列で返す。"""
    chunks = get_manual_rag_index().search(query, top_k=top_k)
    if not chunks:
        return ""
    parts = ["【操作マニュアル（参考情報）】"]
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


# 日本語: ユーザーのメッセージが「アプリ操作方法に関する質問」であるか判定し、マニュアル検索の要否を返します。
# English: Determine whether the user's query asks for application usage help and requires manual search.
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
    if len(q) < 5 or _CONVERSATIONAL_REPLIES.match(q):
        return False

    # アプリ固有の語彙が含まれる
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
