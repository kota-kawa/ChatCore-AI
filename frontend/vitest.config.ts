import { defineConfig } from "vitest/config";

export default defineConfig({
  oxc: {
    jsx: {
      runtime: "automatic",
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.component.test.tsx"],
    setupFiles: ["./tests/component_test_setup.ts"],
    clearMocks: true,
    restoreMocks: true,
  },
});
