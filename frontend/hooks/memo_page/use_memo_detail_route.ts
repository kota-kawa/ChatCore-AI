import { useRouter } from "next/router";
import { useEffect, useRef } from "react";

type UseMemoDetailRouteParams = {
  // 開いている（閉じるアニメーション中ではない）メモの id。無ければ null
  // Id of the memo that is open (and not animating closed), or null
  openMemoId: string | null;
  openMemoDetail: (memoId: string | number) => Promise<boolean>;
  closeMemoDetail: () => Promise<void>;
};

// 開いているメモを URL の ?memo=<id> に映す。詳細を開くと履歴が 1 つ進むので、スマホの
// 「戻る」やブラウザの戻るはページを離れず詳細を閉じる。URL を直接開けばそのメモが開く。
// 画面の操作と履歴の移動のどちらが先に起きたかで同期の向きを決める。
// Mirrors the open memo in the URL as ?memo=<id>. Opening the detail adds a history entry, so the
// phone's back gesture or the browser's back button closes the detail instead of leaving the
// page, and opening the URL directly opens that memo. Whichever changed first (the UI or the
// history) decides the direction of the sync.
export function useMemoDetailRoute({ openMemoId, openMemoDetail, closeMemoDetail }: UseMemoDetailRouteParams) {
  const router = useRouter();
  // URL の値は API のパスに入るので、メモの id（数字）以外は無いものとして扱う
  // The URL value ends up in an API path, so anything but a memo id (digits) counts as absent
  const routeMemoId = typeof router.query.memo === "string" && /^\d{1,18}$/.test(router.query.memo) ? router.query.memo : null;
  const previousRef = useRef<{ route: string | null; open: string | null } | null>(null);
  // この画面で履歴に積んだ分だけ、閉じるときに戻る。直接開いた URL では履歴を戻らない
  // Go back on close only for the entry this page pushed; a directly opened URL is replaced instead
  const pushedEntryRef = useRef(false);

  useEffect(() => {
    if (!router.isReady) return;
    const firstSync = previousRef.current === null;
    const previous = previousRef.current ?? { route: null, open: null };
    previousRef.current = { route: routeMemoId, open: openMemoId };
    if (routeMemoId === openMemoId) return;

    if (previous.open !== openMemoId) {
      if (openMemoId) {
        pushedEntryRef.current = true;
        void router.push({ pathname: router.pathname, query: { ...router.query, memo: openMemoId } }, undefined, { shallow: true });
      } else if (pushedEntryRef.current) {
        pushedEntryRef.current = false;
        router.back();
      } else {
        const query = { ...router.query };
        delete query.memo;
        void router.replace({ pathname: router.pathname, query }, undefined, { shallow: true });
      }
      return;
    }

    if (routeMemoId) {
      // 「進む」で開き直したメモは履歴に 1 つ前（一覧）があるので、閉じるときは戻ればよい。
      // 最初の表示で URL から開いた場合だけは戻る先がこの画面とは限らないので、置き換えにする
      // A memo reopened with "forward" has the list one entry back, so closing can go back. Only
      // a memo opened from the URL on first load may have no entry of this page behind it, so
      // that one is replaced instead
      pushedEntryRef.current = !firstSync;
      const failedId = routeMemoId;
      void openMemoDetail(routeMemoId).then((opened) => {
        // 開けなかった id（存在しない・他人のメモ）を URL に残すと、再読み込みのたびに失敗を繰り返す
        // Leaving an id that could not open (missing, or someone else's) would fail again on every reload
        if (opened || previousRef.current?.route !== failedId) return;
        const query = { ...router.query };
        delete query.memo;
        void router.replace({ pathname: router.pathname, query }, undefined, { shallow: true });
      });
    } else {
      pushedEntryRef.current = false;
      void closeMemoDetail();
    }
    // router は描画ごとに別物になりうる。同期の引き金は URL と開いているメモだけにする
    // The router object may change per render; only the URL and the open memo trigger the sync
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openMemoId, routeMemoId, router.isReady]);
}
