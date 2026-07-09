// frontend/scripts/prompt_share/prompt_category_registry.ts
// 共有プロンプトのカテゴリ軸のフロント側レジストリ (services/prompt_categories.py のミラー)。
// Frontend registry for the prompt category axis. Mirror of services/prompt_categories.py.
//
// カテゴリは「話題」ではなく「タスク（AIに何をさせるか）」で分類する。話題の流行に左右されない
// ため、カテゴリ自体の追加・変更をほぼ不要にできる。DBには安定キーを保存し、日本語ラベルは
// 表示時に解決するので、改名・多言語化でも過去データが壊れない。
// Categories are task-oriented, not topic-oriented, so the set stays stable. The DB stores
// stable keys; Japanese labels are resolved at render time.

// カテゴリ未設定を表す空値。表示側では「未分類」として扱う。
// Empty value meaning "no category"; rendered as 未分類.
export const CATEGORY_UNSET = "";

// その他カテゴリのキー。
// Key for the catch-all category.
export const CATEGORY_OTHER = "other";

// カテゴリ軸の1エントリ。
// One entry on the category axis.
export type PromptCategoryDescriptor = {
  key: string;
  label: string;
  // Bootstrap Icons のクラス名。
  // Bootstrap Icons class name.
  icon: string;
};

// --- カテゴリレジストリ -----------------------------------------------------
// 並び順はフィルタUI・投稿フォームの表示順。"other" は必ず末尾に置く。
// Order drives the filter UI and composer form; "other" must stay last.
export const PROMPT_CATEGORY_REGISTRY: PromptCategoryDescriptor[] = [
  { key: "writing", label: "文章作成", icon: "bi-pencil" },
  { key: "coding", label: "開発・プログラミング", icon: "bi-code-slash" },
  { key: "business", label: "仕事・ビジネス", icon: "bi-briefcase" },
  { key: "learning", label: "学習・教育", icon: "bi-book" },
  { key: "research", label: "調査・分析", icon: "bi-graph-up" },
  { key: "ideation", label: "アイデア・企画", icon: "bi-lightbulb" },
  { key: "creative", label: "創作・ロールプレイ", icon: "bi-palette" },
  { key: "language", label: "翻訳・語学", icon: "bi-translate" },
  { key: "daily_life", label: "暮らし・相談", icon: "bi-house-heart" },
  { key: "hobby", label: "趣味・エンタメ", icon: "bi-controller" },
  { key: CATEGORY_OTHER, label: "その他", icon: "bi-stars" }
];

// 旧カテゴリ（日本語ラベル保存値）から新キーへのエイリアス。
// 移行前に配信されたクライアントや、古いキャッシュが持つ値を表示できるようにする。
// Aliases mapping legacy Japanese category values to canonical keys, so pre-migration
// values coming from an old client or a stale cache still render correctly.
const LEGACY_CATEGORY_ALIASES: Record<string, string> = {
  恋愛: "daily_life",
  旅行: "daily_life",
  グルメ: "daily_life",
  勉強: "learning",
  趣味: "hobby",
  スポーツ: "hobby",
  音楽: "hobby",
  仕事: "business",
  その他: CATEGORY_OTHER,
  未選択: CATEGORY_UNSET
};

const CATEGORY_MAP = new Map(PROMPT_CATEGORY_REGISTRY.map((category) => [category.key, category]));

// カテゴリキーの一覧 (投稿フォームのバリデーション等で使う)。
// All canonical category keys.
export const PROMPT_CATEGORY_KEYS: string[] = PROMPT_CATEGORY_REGISTRY.map((category) => category.key);

// カテゴリ値を正準キーへ正規化する。未知の値は null を返す (呼び出し側で弾く)。
// Normalize a category value to its canonical key; unknown values return null.
export function normalizeCategory(value?: string | null): string | null {
  const normalized = (value ?? "").trim();
  if (!normalized) {
    return CATEGORY_UNSET;
  }
  const lowered = normalized.toLowerCase();
  if (CATEGORY_MAP.has(lowered)) {
    return lowered;
  }
  const alias = LEGACY_CATEGORY_ALIASES[normalized];
  return alias === undefined ? null : alias;
}

// カテゴリキーから表示ラベルを解決する。未設定・未知は空文字列。
// Resolve a category key to its display label; unset or unknown yields an empty string.
export function getCategoryLabel(value?: string | null): string {
  const normalized = normalizeCategory(value);
  if (!normalized) {
    return "";
  }
  return CATEGORY_MAP.get(normalized)?.label ?? "";
}

// 表示用のラベルを、未設定時のフォールバック付きで返す。
// Resolve a category label, falling back to 未分類 when unset or unknown.
export function getCategoryLabelOrFallback(value?: string | null, fallback = "未分類"): string {
  return getCategoryLabel(value) || fallback;
}
