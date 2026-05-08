import { useEffect } from "react";

import { acquireBodyScrollLock } from "../scripts/core/body_scroll_lock";

export function useBodyScrollLock(isLocked: boolean) {
  useEffect(() => {
    if (!isLocked) return;
    return acquireBodyScrollLock();
  }, [isLocked]);
}
