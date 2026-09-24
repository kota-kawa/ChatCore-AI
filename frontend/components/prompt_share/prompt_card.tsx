import { memo, useEffect, useRef, useState, type MouseEvent } from "react";
import Image from "next/image";

import MarkdownContent from "../MarkdownContent";
import { buildPromptPath } from "../../lib/promptSlug";
import { localizePublicPath } from "../../lib/seo";
import { DEFAULT_AUTHOR_AVATAR_URL } from "../../scripts/prompt_share/constants";
import { getCategoryLabelOrFallback } from "../../scripts/prompt_share/prompt_category_registry";
import { DEFAULT_CONTENT_FORMAT, DEFAULT_MEDIA_TYPE } from "../../scripts/prompt_share/prompt_type_registry";
import {
  formatPromptDate,
  getPromptFormatIconClass,
  getPromptFormatLabel,
  getPromptMediaIconClass,
  getPromptMediaLabel,
  getPromptPreviewSource,
  getPromptReferenceImageUrl,
  normalizePromptContentFormat,
  normalizePromptMediaType,
  truncateContent,
} from "../../scripts/prompt_share/formatters";
import type { PromptData } from "../../scripts/prompt_share/types";
import { useTranslation } from "../../contexts/locale_context";
import type { ImportActionState } from "../../hooks/use_import_action";
import { ContentImportButton } from "../ui/content_import_button";

// サーバーから受け取ったPromptDataに、クライアント専用の状態を追加した拡張型
// Extends server-side PromptData with client-only state (local ID and action status)
export type PromptRecord = PromptData & {
  clientId: string;
  liked: boolean;
  used_in_chat: boolean;
};

// カードが受け取るすべての操作ハンドラと状態をまとめたProps型
// All action handlers and UI state props passed into the card component
type PromptCardProps = {
  prompt: PromptRecord;
  isPriorityImage?: boolean;
  isDropdownOpen: boolean;
  isLikePending: boolean;
  isLikeEffectActive: boolean;
  isAddAsTaskPending: boolean;
  addAsTaskState?: ImportActionState;
  isMemoSavePending: boolean;
  isUseInChatEffectActive: boolean;
  isOwnPrompt?: boolean;
  onOpenDetail: (prompt: PromptRecord) => void;
  onOpenComments: (prompt: PromptRecord) => void;
  onOpenShare: (prompt: PromptRecord, event: MouseEvent<HTMLButtonElement>) => void;
  onToggleDropdown: (promptId: string) => void;
  onCloseDropdown: () => void;
  onAddAsTask: (prompt: PromptRecord) => void;
  onSaveAsMemo: (prompt: PromptRecord) => void;
  onToggleLike: (prompt: PromptRecord) => void;
  onOpenAuthorProfile: (authorUserId: number, authorName: string) => void;
  onEdit?: (prompt: PromptRecord) => void;
  // カードの半分以上が画面に入ったときに 1 回だけ呼ばれる（表示回数の計測用）
  // Called once when at least half of the card has entered the viewport (impression counting)
  onImpression?: (prompt: PromptRecord) => void;
};

// この割合以上が見えたら「表示された」と数える。端が少し覗いただけの状態は数えない。
// A card counts as shown once this share of it is visible, so a sliver at the edge does not count.
const IMPRESSION_VISIBLE_RATIO = 0.5;

// アバター画像の読み込みに失敗した場合、デフォルト画像へ差し替える
// Falls back to the default image when the avatar fails to load
function AuthorAvatarImage({ src, alt }: { src: string; alt: string }) {
  const [hasError, setHasError] = useState(false);
  return (
    <img
      className="prompt-card__author-avatar"
      src={hasError || !src ? DEFAULT_AUTHOR_AVATAR_URL : src}
      alt={alt}
      loading="lazy"
      decoding="async"
      onError={() => {
        setHasError(true);
      }}
    />
  );
}

function PromptCardComponent({
  prompt,
  isPriorityImage = false,
  isDropdownOpen,
  isLikePending,
  isLikeEffectActive,
  isAddAsTaskPending,
  addAsTaskState,
  isMemoSavePending,
  isUseInChatEffectActive,
  isOwnPrompt = false,
  onOpenDetail,
  onOpenComments,
  onOpenShare,
  onToggleDropdown,
  onCloseDropdown,
  onAddAsTask,
  onSaveAsMemo,
  onToggleLike,
  onOpenAuthorProfile,
  onEdit,
  onImpression,
}: PromptCardProps) {
  const { locale, t } = useTranslation();
  const rootRef = useRef<HTMLDivElement | null>(null);
  // 呼び出し側の再レンダーで observer を作り直さないよう、最新のハンドラだけ参照で持つ
  // Keep the latest handler in a ref so re-renders of the parent do not recreate the observer
  const onImpressionRef = useRef(onImpression);
  onImpressionRef.current = onImpression;
  useEffect(() => {
    const element = rootRef.current;
    if (!element || !onImpressionRef.current || typeof IntersectionObserver === "undefined") {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) {
          return;
        }
        observer.disconnect();
        onImpressionRef.current?.(prompt);
      },
      { threshold: IMPRESSION_VISIBLE_RATIO }
    );
    observer.observe(element);
    return () => observer.disconnect();
    // 1 枚のカードにつき 1 回数えればよいので、投稿 ID が変わったときだけ観測をやり直す
    // One count per card is enough, so only re-observe when the card shows a different prompt
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prompt.id]);
  // サーバー値を正規化し、未設定時のフォールバックを確保する
  // Normalize server values and set safe fallbacks for missing fields
  const contentFormatValue = normalizePromptContentFormat(String(prompt.content_format || ""));
  const mediaTypeValue = normalizePromptMediaType(String(prompt.media_type || ""));
  // 既定の組み合わせ（プロンプト×テキスト）はカードから読み取れる情報なので、バッジを省いてカテゴリ名に幅を譲る
  // The default combination (prompt x text) is already obvious from the card, so hide those badges and give the width to the category
  const isDefaultFormat = contentFormatValue === DEFAULT_CONTENT_FORMAT;
  const isDefaultMedia = mediaTypeValue === DEFAULT_MEDIA_TYPE;
  const promptId = prompt.clientId;
  const safeCategory = getCategoryLabelOrFallback(prompt.category, undefined, locale);
  const safeCreatedAt = formatPromptDate(prompt.created_at) || t("promptShare.dateUnavailable");
  const commentCount = Number(prompt.comment_count || 0);
  const viewCount = Number(prompt.view_count || 0);
  const likeCount = Number(prompt.like_count || 0);
  const isFeatured = Boolean(prompt.featured_at);
  const isUsedInChat = Boolean(prompt.used_in_chat);
  const isSkillFormat = contentFormatValue === "skill";
  const isAddedToSkills = Boolean(prompt.added_to_skills);
  const isPrimaryActionActive = isSkillFormat ? isAddedToSkills : isUsedInChat;
  const isPrimaryActionPending = isAddAsTaskPending;
  const primaryActionState = addAsTaskState ?? (isPrimaryActionPending ? "pending" : "idle");
  const primaryActionLabel = isSkillFormat
    ? isPrimaryActionPending
      ? t("promptShare.addingSkill")
      : isAddedToSkills
        ? t("promptShare.skillAdded")
        : t("promptShare.addSkill")
    : isPrimaryActionPending
      ? t("promptShare.updatingChat")
      : isUsedInChat
        ? t("promptShare.removeFromChat")
        : t("promptShare.useInChat");
  const menuId = `prompt-actions-menu-${promptId}`;
  const authorName = prompt.author || t("promptShare.authorMissing");
  const authorUserId = Number(prompt.author_user_id || 0);
  const hasAuthorProfile = authorUserId > 0;
  const cardImageUrl = getPromptReferenceImageUrl(prompt, "thumbnail");
  // 管理対象の相対URLだけNext Imageの最適化対象にする。
  // Keep external/legacy URLs on a native img for backwards compatibility.
  const canOptimizeReferenceImage =
    cardImageUrl.startsWith("/prompt_share/api/media/") ||
    cardImageUrl.startsWith("/static/uploads/prompt_share/");

  // SKILLフォーマットはskill_markdownを、それ以外はcontentをプレビューに使う
  // Show skill_markdown preview for skill-format prompts; fall back to content otherwise
  const hasDescription = Boolean(prompt.description?.trim());
  const cardPreviewSource = getPromptPreviewSource(
    prompt.description,
    contentFormatValue,
    prompt.content,
    prompt.skill_markdown
  );
  const cardPreview = truncateContent(
    cardPreviewSource || (contentFormatValue === "skill" ? t("promptShare.skillOpenHelp") : "")
  );

  // 個別ページの正規URL。カード本体はモーダルを開くが、タイトルは実リンクとして出して
  // クローラーの発見経路（sitemapだけに頼らない内部リンク）と別タブで開く操作を確保する。
  // Canonical URL of the detail page. The card body still opens the modal, but the title is a real
  // link so crawlers have an internal path (not just the sitemap) and users can open it in a new tab.
  // 楽観的に追加された投稿などIDが未確定のカードはリンクにしない（遷移先が存在しない）
  // Cards without a settled ID (e.g. optimistically inserted posts) stay unlinked: there is no target yet
  const promptDetailPath = prompt.id === undefined || prompt.id === null || prompt.id === ""
    ? ""
    : localizePublicPath(buildPromptPath(prompt.id, prompt.title), locale);

  // 素の左クリックは既存どおりモーダル表示に任せ（親のonClickへバブリングさせる）、
  // 修飾キー付き・中クリックはブラウザ既定のリンク遷移を通す。
  // A plain left click keeps the modal behavior (the event bubbles to the parent onClick), while
  // modifier and middle clicks fall through to the browser's default link navigation.
  const handleTitleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
    event.preventDefault();
  };

  return (
    <div
      ref={rootRef}
      className={`prompt-card cc-press${isDropdownOpen ? " menu-open" : ""}`}
      data-category={prompt.category || ""}
      role="button"
      tabIndex={0}
      aria-label={t("promptShare.showDetails", { title: prompt.title })}
      onClick={() => {
        onOpenDetail(prompt);
      }}
      onKeyDown={(event) => {
        // カード内のボタン・リンクからバブリングしたキー操作は無視し、
        // カード自体にフォーカスがある場合のみ詳細モーダルを開く
        // Ignore key events bubbling up from nested buttons/links; only act when the card itself is focused
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpenDetail(prompt);
        }
      }}
    >
      <div className="prompt-card__header">
        <div className="prompt-card__badges">
          {/* 運営が選んだ投稿は一覧の先頭に固定されるので、なぜ上にあるかが分かるようバッジで示す */}
          {/* Featured posts are pinned to the top of the feed, so the badge explains why they lead */}
          {isFeatured ? (
            <span className="prompt-card__type-pill prompt-card__type-pill--featured">
              <i className="bi bi-star-fill"></i>
              <span>{t("promptShare.featuredPick")}</span>
            </span>
          ) : null}
          <span className="prompt-card__category-pill">
            <i className="bi bi-hash"></i>
            <span>{safeCategory}</span>
          </span>
          {/* 既定値のバッジ（プロンプト / テキスト）は情報量がなく、狭い画面でカテゴリ名を潰すだけなので出さない */}
          {/* Skip the default badges (prompt / text): they add no information and squeeze the category name on narrow screens */}
          {isDefaultFormat ? null : (
            <span className={`prompt-card__type-pill prompt-card__type-pill--format prompt-card__type-pill--${contentFormatValue}`}>
              <i className={`bi ${getPromptFormatIconClass(contentFormatValue)}`}></i>
              <span>{getPromptFormatLabel(contentFormatValue, locale)}</span>
            </span>
          )}
          {/* メディア軸を独立したバッジとして表示し、画像を生成対象として扱う */}
          {/* Render media as an independent badge, so image is a generation target rather than a post type */}
          {isDefaultMedia ? null : (
            <span className={`prompt-card__type-pill prompt-card__type-pill--media prompt-card__type-pill--${mediaTypeValue}`}>
              <i className={`bi ${getPromptMediaIconClass(mediaTypeValue)}`}></i>
              <span>{getPromptMediaLabel(mediaTypeValue, locale)}</span>
            </span>
          )}
        </div>
        <span className="prompt-card__created-at">
          <i className="bi bi-calendar3"></i>
          {safeCreatedAt}
        </span>
        {/* 投稿者と日付を同じメタ情報行に配置する。ユーザーIDがある場合のみプロフィールへ遷移できる */}
        {/* Keep the author and date on the same metadata row; only make the author interactive when a user ID exists */}
        {hasAuthorProfile ? (
          <button
            type="button"
            className="prompt-card__author"
            onClick={(event) => {
              event.stopPropagation();
              onOpenAuthorProfile(authorUserId, authorName);
            }}
          >
            <AuthorAvatarImage
              src={prompt.author_avatar_url || ""}
              alt={t("promptShare.authorAvatarAlt", { name: authorName })}
            />
            <span className="prompt-card__author-name">{authorName}</span>
          </button>
        ) : (
          <div className="prompt-card__author prompt-card__author--static">
            <AuthorAvatarImage
              src={prompt.author_avatar_url || ""}
              alt={t("promptShare.authorAvatarAlt", { name: authorName })}
            />
            <span className="prompt-card__author-name">{authorName}</span>
          </div>
        )}
        {/* クリックがカード本体に伝播しないようにstopPropagationでモーダル誤起動を防ぐ */}
        {/* Stop propagation so clicking the menu button does not also open the detail modal */}
        <button
          className="meatball-menu cc-press"
          type="button"
          aria-label={t("promptShare.moreActions")}
          aria-haspopup="true"
          aria-expanded={isDropdownOpen ? "true" : "false"}
          aria-controls={menuId}
          data-tooltip={t("promptShare.moreActions")}
          data-tooltip-placement="left"
          onClick={(event) => {
            event.stopPropagation();
            onToggleDropdown(promptId);
          }}
        >
          <i className="bi bi-three-dots"></i>
        </button>
      </div>

      {/* ドロップダウンもカードクリックを遮断し、意図しない詳細モーダルの起動を避ける */}
      {/* Dropdown also stops propagation to prevent unintended detail modal trigger */}
      <div
        id={menuId}
        className={`prompt-actions-dropdown${isDropdownOpen ? " is-open" : ""}`}
        role="menu"
        aria-hidden={isDropdownOpen ? "false" : "true"}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        {isOwnPrompt && onEdit ? (
          <button
            className="dropdown-item cc-press"
            type="button"
            role="menuitem"
            onClick={() => {
              onCloseDropdown();
              onEdit(prompt);
            }}
          >
            <i className="bi bi-pencil-square"></i>
            <span>{t("promptShare.editPrompt")}</span>
          </button>
        ) : null}
        <button
          className="dropdown-item cc-press"
          type="button"
          role="menuitem"
          disabled={isMemoSavePending}
          aria-label={isMemoSavePending ? t("promptShare.savingMemo") : t("promptShare.saveToMemo")}
          onClick={() => {
            if (isMemoSavePending) {
              return;
            }
            void onSaveAsMemo(prompt);
          }}
        >
          <i className={`bi ${isMemoSavePending ? "bi-hourglass-split" : "bi-bookmark-plus"}`}></i>
          <span>{isMemoSavePending ? t("promptShare.savingMemo") : t("promptShare.saveToMemo")}</span>
        </button>
        <button
          className="dropdown-item cc-press"
          type="button"
          role="menuitem"
          data-action="share"
          onClick={(event) => {
            onOpenShare(prompt, event);
          }}
        >
          <i className="bi bi-share"></i>
          <span>{t("common.share")}</span>
        </button>
        <button
          className="dropdown-item cc-press"
          type="button"
          role="menuitem"
          onClick={() => {
            onCloseDropdown();
          }}
        >
          <i className="bi bi-bell-slash"></i>
          <span>{t("promptShare.mute")}</span>
        </button>
        <button
          className="dropdown-item cc-press"
          type="button"
          role="menuitem"
          onClick={() => {
            onCloseDropdown();
          }}
        >
          <i className="bi bi-flag"></i>
          <span>{t("promptShare.report")}</span>
        </button>
      </div>

      {/* 何の投稿かを最初に読ませるため、タイトルは作例画像より前に置く */}
      {/* The title comes before the reference image so the reader sees what the post is first */}
      {/* 文字数で切らず、CSSの2行クランプに任せてカード幅いっぱいまで見せる */}
      {/* No character cap here: the CSS two-line clamp lets the title use the card's full width */}
      <h3>
        {promptDetailPath ? (
          <a href={promptDetailPath} className="prompt-card__title-link" onClick={handleTitleClick}>
            {prompt.title}
          </a>
        ) : (
          prompt.title
        )}
      </h3>

      {/* 作例画像は存在する場合のみ表示し、遅延読み込みで初期描画コストを下げる */}
      {/* Reference image is optional; lazy loading reduces initial render cost */}
      {cardImageUrl ? (
        <div className="prompt-card__image">
          {canOptimizeReferenceImage ? (
            <Image
              src={cardImageUrl}
              alt={t("promptShare.exampleImageAlt", { title: prompt.title })}
              fill
              sizes="(max-width: 700px) calc(100vw - 2rem), (max-width: 1100px) 45vw, 360px"
              quality={75}
              preload={isPriorityImage}
              fetchPriority={isPriorityImage ? "high" : "auto"}
              loading={isPriorityImage ? "eager" : "lazy"}
            />
          ) : (
            <img
              src={cardImageUrl}
              alt={t("promptShare.exampleImageAlt", { title: prompt.title })}
              loading={isPriorityImage ? "eager" : "lazy"}
              fetchPriority={isPriorityImage ? "high" : "auto"}
              decoding="async"
            />
          )}
        </div>
      ) : null}

      {/* カード内の本文プレビューも詳細モーダルと同じ安全なMarkdownレンダラーで整形する */}
      {/* Render the card preview through the same safe Markdown renderer as the detail modal */}
      {hasDescription ? (
        <p className="prompt-card__content">{cardPreview}</p>
      ) : (
        <MarkdownContent text={cardPreview} className="prompt-card__content" />
      )}

      <div className="prompt-meta">
        <div className="prompt-actions">
          {/* 閲覧数は操作ではなく指標。並び順（閲覧数順）の根拠が見えるようカードに出す */}
          {/* The view count is a signal, not an action; showing it makes the feed's popularity order visible */}
          <span className="prompt-action-stat" aria-label={t("promptShare.viewCountLabel", { count: viewCount })}>
            <i className="bi bi-eye" aria-hidden="true"></i>
            <span>{viewCount}</span>
          </span>
          <button
            className="prompt-action-btn comment-btn cc-press"
            type="button"
            aria-label={t("promptShare.comments")}
            data-tooltip={t("promptShare.commentTooltip")}
            data-tooltip-placement="top"
            onClick={(event) => {
              event.stopPropagation();
              onOpenComments(prompt);
            }}
          >
            <i className="bi bi-chat-dots"></i>
            <span className="prompt-action-count">{commentCount}</span>
          </button>

          {/* isPendingの間は追加クリックを無視してAPIの二重送信を防ぐ */}
          {/* Guard against double-submission by ignoring clicks while a like request is in flight */}
          <button
            className={`prompt-action-btn like-btn cc-press${prompt.liked ? " liked" : ""}${isLikePending ? " is-pending" : ""}${isLikeEffectActive ? " is-celebrating" : ""}`}
            type="button"
            aria-label={prompt.liked ? t("promptShare.unlike") : t("promptShare.like")}
            aria-pressed={prompt.liked ? "true" : "false"}
            aria-disabled={isLikePending ? "true" : "false"}
            data-tooltip={prompt.liked ? t("promptShare.unlike") : t("promptShare.likeTooltip")}
            data-tooltip-placement="top"
            onClick={(event) => {
              event.stopPropagation();
              if (isLikePending) {
                return;
              }
              void onToggleLike(prompt);
            }}
          >
            <i className={`bi ${prompt.liked ? "bi-heart-fill" : "bi-heart"}`}></i>
            {likeCount > 0 ? (
              <span className="prompt-action-count" aria-label={t("promptShare.likeCountLabel", { count: likeCount })}>
                {likeCount}
              </span>
            ) : null}
          </button>

          {/* 共有プロンプトの主操作も二重送信を防ぐ */}
          {/* Guard the shared-prompt primary action against duplicate API requests */}
          <ContentImportButton
            variant="compact"
            className={`prompt-action-btn use-in-chat-btn cc-press${isSkillFormat ? " add-to-skill-btn" : ""}${isSkillFormat && isAddedToSkills ? " added-to-skills" : isUsedInChat ? " used-in-chat" : ""}${isPrimaryActionPending ? " is-pending" : ""}${isUseInChatEffectActive ? " is-celebrating" : ""}`}
            pending={isPrimaryActionPending}
            state={primaryActionState}
            active={isPrimaryActionActive}
            disableWhenActive={isSkillFormat}
            label={primaryActionLabel}
            iconClass={isPrimaryActionActive ? "bi-plus-square-fill" : "bi-plus-square"}
            ariaPressed={isSkillFormat ? isAddedToSkills : isUsedInChat}
            dataTooltip={primaryActionLabel}
            dataTooltipPlacement="top"
            onClick={(event) => {
              event.stopPropagation();
              if (isPrimaryActionPending || (isSkillFormat && isAddedToSkills)) {
                return;
              }
              void onAddAsTask(prompt);
            }}
          />
        </div>
      </div>
    </div>
  );
}

// propsが変わらない限り再レンダリングをスキップし、カードリスト全体のパフォーマンスを保つ
// Wrap with memo so unchanged cards in a large list are not re-rendered unnecessarily
export const PromptCard = memo(PromptCardComponent);
PromptCard.displayName = "PromptCard";
