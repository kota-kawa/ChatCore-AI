// オフライン / 低速回線 / 復帰を控えめに知らせるグローバルバナー。
// A subtle global banner that announces offline / slow-link / recovery states.
//
// 遅い・不安定な回線でも「いま何が起きているか」を非ブロッキングに伝え、操作の不安を減らす。
// Communicates "what is happening now" non-blockingly on slow/flaky links to reduce anxiety.
// 視覚は globals.css の .cc-net-banner に従い、prefers-reduced-motion で動きは止まる。
// Visuals follow .cc-net-banner in globals.css; motion halts under prefers-reduced-motion.

import { useEffect, useRef, useState } from "react";
import { useNetworkStatus } from "../hooks/use_network_status";
import { useTranslation } from "../contexts/locale_context";

type BannerState =
  | { variant: "offline"; message: string }
  | { variant: "slow"; message: string }
  | { variant: "recovered"; message: string }
  | null;

const RECOVERED_VISIBLE_MS = 2400;

// useNetworkStatus の online / slow から、表示するバナー（オフライン・低速・復帰）を1つ決める。pages/_app.tsx から描画される。
// Picks the single banner (offline / slow / recovered) to show from useNetworkStatus' online / slow flags; rendered from pages/_app.tsx.
export function NetworkStatusBanner() {
  const { locale, t } = useTranslation();
  const { online, slow } = useNetworkStatus();
  // wasOfflineRef は「直前までオフラインだったか」を覚え、復帰時だけ「復帰」バナーを出すために使う
  // wasOfflineRef remembers whether we were just offline so the "recovered" banner appears only on reconnection
  const [banner, setBanner] = useState<BannerState>(null);
  const wasOfflineRef = useRef(false);
  const recoveredTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (recoveredTimerRef.current !== null) {
      clearTimeout(recoveredTimerRef.current);
      recoveredTimerRef.current = null;
    }

    if (!online) {
      wasOfflineRef.current = true;
      setBanner({ variant: "offline", message: t("network.offline") });
      return;
    }

    if (wasOfflineRef.current) {
      // オフラインから復帰した直後だけ、短時間「復帰」を表示する。
      // Show a brief "recovered" message only right after coming back from offline.
      wasOfflineRef.current = false;
      setBanner({ variant: "recovered", message: t("network.online") });
      recoveredTimerRef.current = setTimeout(() => {
        setBanner((current) => (current?.variant === "recovered" ? null : current));
        recoveredTimerRef.current = null;
      }, RECOVERED_VISIBLE_MS);
      return;
    }

    if (slow) {
      setBanner({ variant: "slow", message: locale === "en" ? "Your connection is slow." : "通信が遅くなっています" });
      return;
    }

    setBanner(null);
  }, [locale, online, slow, t]);

  useEffect(() => {
    return () => {
      if (recoveredTimerRef.current !== null) clearTimeout(recoveredTimerRef.current);
    };
  }, []);

  const visible = banner !== null;
  // 復帰メッセージは success 相当の緑、それ以外は variant に従う。
  // The recovered message uses a success-like variant; others follow their own variant.
  const dataVariant = banner?.variant === "recovered" ? "recovered" : banner?.variant ?? "slow";

  return (
    <div
      className={`cc-net-banner${visible ? " is-visible" : ""}`}
      data-variant={dataVariant}
      role="status"
      aria-live="polite"
      aria-hidden={visible ? undefined : true}
    >
      <span className="cc-net-banner__dot" aria-hidden="true" />
      <span>{banner?.message ?? ""}</span>
    </div>
  );
}
