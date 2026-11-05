// 設定画面でデータ取得中に表示するスケルトン（プロフィール欄とプロンプトカード）。呼び出し元は settings_sections.tsx。
// Skeleton placeholders shown while settings data loads (profile fields and prompt cards). Used by settings_sections.tsx.
import { Skeleton, SkeletonText } from "../ui/skeleton";
import { useTranslation } from "../../contexts/locale_context";

// プロフィールセクションの読み込み中表示。アイコンと入力欄の並びを模す
// Loading placeholder for the profile section, mimicking the avatar and input layout
export function SettingsProfileSkeleton() {
  const { t } = useTranslation();
  return (
    <div className="settings-profile-skeleton" role="status" aria-label={t("settings.loadingProfile")}>
      <Skeleton variant="circle" width={96} height={96} />
      <div className="settings-profile-skeleton__fields">
        <Skeleton variant="text" width="34%" height="0.9rem" />
        <Skeleton variant="block" width="100%" height="2.8rem" />
        <Skeleton variant="text" width="38%" height="0.9rem" />
        <Skeleton variant="block" width="100%" height="2.8rem" />
        <Skeleton variant="text" width="28%" height="0.9rem" />
        <Skeleton variant="block" width="100%" height="7rem" />
        <Skeleton variant="text" width="42%" height="0.9rem" />
        <Skeleton variant="block" width="100%" height="8rem" />
      </div>
    </div>
  );
}

// プロンプトカード一覧の読み込み中表示（4枚）。タイトルの幅を交互に変えて単調に見せない
// Loading placeholder for the prompt card list (4 cards); title widths alternate so it does not look uniform
export function SettingsPromptCardSkeletonGrid() {
  return (
    <>
      {Array.from({ length: 4 }).map((_, index) => (
        <article key={index} className="prompt-card prompt-card--skeleton">
          <div className="prompt-card__main">
            <div className="prompt-card__header">
              <Skeleton variant="text" width="46%" height="1.1rem" />
              <Skeleton variant="text" width="24%" height="0.8rem" />
            </div>
            <Skeleton variant="text" width={index % 2 === 0 ? "58%" : "74%"} height="1.1rem" />
            <SkeletonText lines={3} />
          </div>
          <div className="prompt-card__footer">
            <Skeleton variant="text" width={96} height="2.2rem" />
          </div>
        </article>
      ))}
    </>
  );
}
