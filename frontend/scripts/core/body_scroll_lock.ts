type BodyScrollLockState = {
  locks: Set<symbol>;
  previousOverflow: string | null;
};

type BodyScrollLockWindow = typeof window & {
  __chatCoreBodyScrollLockState?: BodyScrollLockState;
};

function getBodyScrollLockState(): BodyScrollLockState {
  const globalWindow = window as BodyScrollLockWindow;
  if (!globalWindow.__chatCoreBodyScrollLockState) {
    globalWindow.__chatCoreBodyScrollLockState = {
      locks: new Set<symbol>(),
      previousOverflow: null,
    };
  }
  return globalWindow.__chatCoreBodyScrollLockState;
}

export function acquireBodyScrollLock() {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return () => {
      // no-op outside the browser
    };
  }

  const state = getBodyScrollLockState();
  const token = Symbol("body-scroll-lock");

  if (state.locks.size === 0) {
    state.previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  state.locks.add(token);

  let released = false;
  return () => {
    if (released) return;
    released = true;

    state.locks.delete(token);
    if (state.locks.size > 0) return;

    document.body.style.overflow = state.previousOverflow ?? "";
    state.previousOverflow = null;
  };
}
