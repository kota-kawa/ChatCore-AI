// 回答生成を同時に 1 つだけ走らせるためのガード。現在の生成の取得・解放・中断を管理する。
// Guard that allows only one answer generation at a time, managing acquiring, releasing, and aborting the current one.
export type ActiveGeneration = {
  id: number;
  roomId: string;
  abortController: AbortController;
  serverGenerationId?: string;
};

export type GenerationGuard = {
  acquire: (roomId: string) => ActiveGeneration | null;
  isActive: (generation: ActiveGeneration) => boolean;
  release: (generation: ActiveGeneration) => boolean;
  abortActive: () => ActiveGeneration | null;
  current: () => ActiveGeneration | null;
  revision: () => number;
};

// acquire は生成中なら null を返す。release は引数が現在の生成と一致するときだけ解放するので、古い生成の後始末が新しい生成を巻き込まない。revision は払い出した生成 ID の最新値で、生成が入れ替わったかの比較に使う。
// acquire returns null while a generation is active. release only frees the guard when the argument is the current generation, so a stale cleanup cannot affect a newer one. revision is the latest issued generation id, usable to detect that generations have changed.
export function createGenerationGuard(): GenerationGuard {
  let currentGeneration: ActiveGeneration | null = null;
  let nextGenerationId = 0;

  return {
    acquire(roomId: string) {
      if (currentGeneration) return null;

      nextGenerationId += 1;
      currentGeneration = {
        id: nextGenerationId,
        roomId,
        abortController: new AbortController(),
      };
      return currentGeneration;
    },

    isActive(generation: ActiveGeneration) {
      return currentGeneration === generation;
    },

    release(generation: ActiveGeneration) {
      if (currentGeneration !== generation) return false;
      currentGeneration = null;
      return true;
    },

    abortActive() {
      const generation = currentGeneration;
      if (!generation) return null;
      currentGeneration = null;
      generation.abortController.abort();
      return generation;
    },

    current() {
      return currentGeneration;
    },

    revision() {
      return nextGenerationId;
    },
  };
}
