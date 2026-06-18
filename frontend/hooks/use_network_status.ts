// ネットワークのオンライン状態と「遅さ」を購読するフック。
// A hook that subscribes to the browser's online state and "slowness".
//
// navigator.onLine と Network Information API（connection.effectiveType / saveData）を組み合わせ、
// オフライン／低速回線を検知してグローバルバナーや取得戦略の調整に使う。
// Combines navigator.onLine with the Network Information API (connection.effectiveType / saveData)
// to detect offline / slow links for the global banner and fetch-strategy tuning.

import { useEffect, useState } from "react";

export type NetworkStatus = {
  online: boolean;
  slow: boolean;
};

type NetworkInformationLike = {
  effectiveType?: string;
  saveData?: boolean;
  addEventListener?: (type: "change", listener: () => void) => void;
  removeEventListener?: (type: "change", listener: () => void) => void;
};

function getConnection(): NetworkInformationLike | undefined {
  if (typeof navigator === "undefined") return undefined;
  return (navigator as Navigator & { connection?: NetworkInformationLike }).connection;
}

function readStatus(): NetworkStatus {
  if (typeof navigator === "undefined") {
    return { online: true, slow: false };
  }
  const connection = getConnection();
  const effectiveType = connection?.effectiveType || "";
  const slow = Boolean(connection?.saveData) || effectiveType === "slow-2g" || effectiveType === "2g";
  return { online: navigator.onLine !== false, slow };
}

export function useNetworkStatus(): NetworkStatus {
  // SSR とのハイドレーション不一致を避けるため、初期値は楽観的（オンライン）に固定する。
  // Start optimistic (online) to avoid SSR/client hydration mismatch; sync in an effect.
  const [status, setStatus] = useState<NetworkStatus>({ online: true, slow: false });

  useEffect(() => {
    const update = () => setStatus(readStatus());
    update();

    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    const connection = getConnection();
    connection?.addEventListener?.("change", update);

    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
      connection?.removeEventListener?.("change", update);
    };
  }, []);

  return status;
}
