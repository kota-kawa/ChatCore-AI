// コンポーネントテスト用のVitest設定。tests/ 配下の *.component.test.tsx をjsdom環境で実行する。
// Vitest configuration for component tests; runs tests/**/*.component.test.tsx in a jsdom environment.
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
    // 各テストの前後でモックを初期化・復元し、テスト間で状態が漏れないようにする
    // Reset and restore mocks around each test so state does not leak between tests
    clearMocks: true,
    restoreMocks: true,
  },
});
