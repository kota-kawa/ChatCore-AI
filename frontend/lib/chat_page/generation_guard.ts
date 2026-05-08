export type ActiveGeneration = {
  id: number;
  roomId: string;
  abortController: AbortController;
};

export type GenerationGuard = {
  acquire: (roomId: string) => ActiveGeneration | null;
  isActive: (generation: ActiveGeneration) => boolean;
  release: (generation: ActiveGeneration) => boolean;
  abortActive: () => ActiveGeneration | null;
  current: () => ActiveGeneration | null;
};

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
  };
}
