import { Skeleton, SkeletonText } from "../ui/skeleton";

export function SettingsProfileSkeleton() {
  return (
    <div className="settings-profile-skeleton" role="status" aria-label="プロフィールを読み込み中">
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

export function SettingsPromptCardSkeletonGrid() {
  return (
    <>
      {Array.from({ length: 4 }).map((_, index) => (
        <article key={index} className="prompt-card prompt-card--skeleton">
          <div className="prompt-card__main">
            <Skeleton variant="text" width={index % 2 === 0 ? "58%" : "74%"} height="1.1rem" />
            <SkeletonText lines={3} />
            <Skeleton variant="text" width="40%" height="0.8rem" />
          </div>
          <div className="prompt-card__footer">
            <Skeleton variant="text" width={120} height="2rem" />
          </div>
        </article>
      ))}
    </>
  );
}
