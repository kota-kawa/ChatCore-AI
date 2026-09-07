import { createRequire } from "node:module";

import js from "@eslint/js";
import nextPlugin from "@next/eslint-plugin-next";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

const require = createRequire(import.meta.url);

// 日本語: typescript-eslint 8.x は TypeScript 7.0 の API を拒否するため（読み込み時に throw する）、
//         TypeScript 7 公式が案内する「TypeScript 6 と併存させる」方式に合わせ、`@typescript/typescript6`
//         が再エクスポートする TS 6.0 API を `require("typescript")` の解決結果として先に登録します。
//         リポジトリの `tsc`（型検査）は devDependencies の typescript 7.0.2 のままで、ここは ESLint の
//         パーサーが使う API だけを差し替えます。
// English: typescript-eslint 8.x throws on load when it detects the TypeScript 7.0 API, so we follow the
//          official "run side-by-side with TypeScript 6.0" guidance and pre-populate the CommonJS cache
//          entry for `require("typescript")` with the TS 6.0 API re-exported by `@typescript/typescript6`.
//          The repository's `tsc` (typecheck) still uses typescript 7.0.2 from devDependencies; only the
//          API consumed by the ESLint parser is swapped here.
// 日本語: あわせて package.json の `overrides.typescript` で typescript 7.0.2 を明示しています。
//         typescript-eslint が宣言する peer 範囲（>=4.8.4 <6.1.0）は上記のとおり ESLint 側だけ
//         TS 6 API を渡すことで満たしているため、npm の peer 解決を上書きしています。
// English: package.json also pins `overrides.typescript` to 7.0.2. typescript-eslint declares a peer range
//          of >=4.8.4 <6.1.0, which is satisfied for ESLint by handing it the TS 6 API above, so npm's peer
//          resolution is overridden rather than downgrading the repository's TypeScript.
const typescript6EntryPoint = require.resolve("@typescript/typescript6");
require(typescript6EntryPoint);
require.cache[require.resolve("typescript")] = require.cache[typescript6EntryPoint];

const { default: tseslint } = await import("typescript-eslint");

const SOURCE_FILES = ["**/*.ts", "**/*.tsx", "**/*.mts", "**/*.cts", "**/*.js", "**/*.jsx", "**/*.mjs", "**/*.cjs"];

// 日本語: `_` 接頭辞の識別子は「意図的に使わない」印として扱い、未使用チェックの対象外にします。
// English: Identifiers prefixed with `_` are treated as intentionally unused and skipped by the checks.
const UNUSED_VARS_OPTIONS = {
  args: "all",
  argsIgnorePattern: "^_",
  caughtErrors: "all",
  caughtErrorsIgnorePattern: "^_",
  destructuredArrayIgnorePattern: "^_",
  varsIgnorePattern: "^_",
  ignoreRestSiblings: true,
};

export default tseslint.config(
  {
    // 日本語: 自動生成物・ビルド成果物・配信用のベンダー JS は lint 対象外にします。
    // English: Generated sources, build output, and vendored JS served from public/ are not linted.
    ignores: [
      ".next/**",
      "node_modules/**",
      "public/**",
      "types/generated/**",
      "tsconfig.tsbuildinfo",
    ],
  },
  {
    files: SOURCE_FILES,
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    linterOptions: {
      reportUnusedDisableDirectives: "error",
    },
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: SOURCE_FILES,
    plugins: {
      "react-hooks": reactHooks,
      "@next/next": nextPlugin,
    },
    rules: {
      ...nextPlugin.configs.recommended.rules,

      // 日本語: `no-css-tags` と `no-page-custom-font` は、ページ側で `public/static/css/**` の CSS と
      //         フォントを読み込む本リポジトリの方針（frontend/STYLING_STRATEGY.md）と正面から衝突します。
      //         必要なページだけがCSS・フォントを読み込む設計を維持するため、この2つは無効化します。
      // English: `no-css-tags` and `no-page-custom-font` directly contradict this repository's strategy of
      //          linking CSS and fonts from the owning page under `public/static/css/**`
      //          (see frontend/STYLING_STRATEGY.md). They are disabled so only the pages that need a
      //          stylesheet or font actually load it.
      "@next/next/no-css-tags": "off",
      "@next/next/no-page-custom-font": "off",

      // 日本語: ページ間リンクを `<a>` で書くとクライアント遷移が壊れるため error に引き上げます。
      // English: Writing inter-page links as `<a>` breaks client-side navigation, so this is raised to error.
      "@next/next/no-html-link-for-pages": "error",

      // 日本語: `next/image` への置き換えはレイアウトと画像配信経路の変更を伴うため、警告のまま残します。
      // English: Migrating to `next/image` changes layout and the image delivery path, so this stays a warning.
      "@next/next/no-img-element": "warn",

      // 日本語: フックの呼び出し順序違反は実行時バグ（state の取り違え）に直結するため error 固定です。
      // English: Breaking hook call order causes real runtime bugs (mismatched state), so this stays an error.
      "react-hooks/rules-of-hooks": "error",

      // 日本語: 依存配列の修正は副作用の発火タイミングを変えるため、本 PR では一括修正せず段階移行とします。
      //         大きなチャット系フックを個別に検証しながら error へ引き上げていく前提の warn です。
      // English: Fixing dependency arrays changes when effects re-run, so this is a staged migration rather
      //          than a bulk rewrite. It stays a warning until the large chat hooks are reviewed one by one
      //          and can be promoted to an error.
      "react-hooks/exhaustive-deps": "warn",

      // 日本語: React Compiler 由来の検査のうち、現状の実装で違反ゼロのものは error として固定し、
      //         レンダー中の副作用・純粋性違反・グローバル変更などの再発を防ぎます。
      //         `set-state-in-effect` / `refs` / `no-deriving-state-in-effects` /
      //         `preserve-manual-memoization` / `immutability` は既存違反が残っているため未導入です。
      // English: Of the React Compiler checks, the ones already clean in this codebase are pinned to error so
      //          render-time side effects, purity violations, and global mutation cannot regress.
      //          `set-state-in-effect`, `refs`, `no-deriving-state-in-effects`,
      //          `preserve-manual-memoization`, and `immutability` are not enabled yet because existing
      //          violations remain in the large chat hooks.
      "react-hooks/capitalized-calls": "error",
      "react-hooks/component-hook-factories": "error",
      "react-hooks/error-boundaries": "error",
      "react-hooks/globals": "error",
      "react-hooks/purity": "error",
      "react-hooks/set-state-in-render": "error",
      "react-hooks/static-components": "error",
      "react-hooks/use-memo": "error",
      "react-hooks/void-use-memo": "error",

      // 日本語: デバッグ用の `console.log` は残さず、利用者に届く警告・エラー出力だけを許可します。
      // English: Debug-only `console.log` must not be committed; only user-facing warn/error output is allowed.
      "no-console": ["error", { allow: ["warn", "error"] }],

      "no-unused-vars": "off",
      "@typescript-eslint/no-unused-vars": ["error", UNUSED_VARS_OPTIONS],

      eqeqeq: ["error", "always", { null: "ignore" }],
      "no-var": "error",
      "prefer-const": ["error", { destructuring: "all" }],
      "no-throw-literal": "error",
      "@typescript-eslint/no-explicit-any": "error",
    },
  },
  {
    // 日本語: リポジトリ運用スクリプトは CLI として結果を標準出力に出すため、`console.log` を許可します。
    // English: Repository tooling scripts are CLIs that report results on stdout, so `console.log` is allowed.
    files: ["scripts/*.cjs", "*.config.mjs", "*.config.cjs"],
    languageOptions: {
      globals: globals.node,
    },
    rules: {
      "no-console": "off",
    },
  },
  {
    // 日本語: `.cjs` は CommonJS のため require と module スコープの変数を許可します。
    // English: `.cjs` files are CommonJS, so require() and module-scoped globals are allowed.
    files: ["**/*.cjs"],
    languageOptions: {
      sourceType: "commonjs",
    },
    rules: {
      "@typescript-eslint/no-require-imports": "off",
    },
  },
);
