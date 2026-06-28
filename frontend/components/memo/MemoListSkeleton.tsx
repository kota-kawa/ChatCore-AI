import { Skeleton, SkeletonText } from "../ui/skeleton";

export function MemoListSkeleton() {
  return (
    <div className="memo-history__sections memo-history__sections--skeleton" role="status" aria-live="polite" aria-label="メモを読み込み中">
      <section className="memo-history__section">
        <ul className="memo-history__list memo-history__list--skeleton">
          {Array.from({ length: 8 }).map((_, index) => (
            <li key={index}>
              <article className="memo-item memo-item--skeleton">
                <Skeleton variant="text" width={index % 3 === 0 ? "62%" : "78%"} height="1.05rem" />
                <SkeletonText lines={index % 2 === 0 ? 4 : 3} />
                <div className="memo-item__footer memo-item__footer--skeleton">
                  <Skeleton variant="text" width="42%" height="0.75rem" />
                  <Skeleton variant="circle" width={30} height={30} />
                </div>
              </article>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
