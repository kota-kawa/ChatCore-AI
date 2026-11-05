// Tailwindの設定。ユーティリティの色・文字サイズ・余白・角丸・影を、globals.css 側のCSS変数（デザイントークン）に対応づける。
// Tailwind configuration; maps utility colors, font sizes, spacing, radii and shadows to the CSS variables (design tokens) defined in globals.css.
import type { Config } from "tailwindcss";

// 解析対象のファイル。ここに含まれないディレクトリのクラス名はビルドで生成されない
// Files scanned for class names; classes used outside these directories are not generated at build time
const config: Config = {
  content: ["./pages/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./scripts/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // 値は直接指定せずCSS変数を参照し、テーマ切り替えがユーティリティにも反映されるようにする
      // Reference CSS variables instead of literal values so theme switching also applies to the utilities
      colors: {
        primary: {
          DEFAULT: "var(--primary-color)",
          hover: "var(--primary-hover)",
          dark: "var(--primary-dark)",
          subtle: "var(--primary-subtle)",
          border: "var(--primary-border)"
        },
        danger: {
          DEFAULT: "var(--danger-color)",
          hover: "var(--danger-hover)"
        },
        surface: {
          primary: "var(--surface-primary)",
          secondary: "var(--surface-secondary)",
          tertiary: "var(--surface-tertiary)"
        },
        text: {
          DEFAULT: "var(--text-dark)",
          secondary: "var(--text-secondary)",
          light: "var(--text-light)"
        }
      },
      fontFamily: {
        sans: ["var(--font-app-sans)", "ui-sans-serif", "system-ui"]
      },
      fontSize: {
        "2xs": "var(--text-2xs)",
        xs: "var(--text-xs)",
        sm: "var(--text-sm)",
        base: "var(--text-base)",
        md: "var(--text-md)",
        lg: "var(--text-lg)",
        xl: "var(--text-xl)",
        "2xl": "var(--text-2xl)"
      },
      // cc-* は --space-* トークンに対応する独自の余白スケール
      // cc-* is a custom spacing scale backed by the --space-* tokens
      spacing: {
        "cc-1": "var(--space-1)",
        "cc-2": "var(--space-2)",
        "cc-3": "var(--space-3)",
        "cc-4": "var(--space-4)",
        "cc-5": "var(--space-5)",
        "cc-6": "var(--space-6)",
        "cc-8": "var(--space-8)",
        "cc-10": "var(--space-10)",
        "cc-12": "var(--space-12)"
      },
      borderRadius: {
        xs: "var(--radius-xs)",
        s: "var(--radius-s)",
        sm: "var(--radius-sm)",
        m: "var(--radius-m)",
        md: "var(--radius-md)",
        l: "var(--radius-l)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
        "2xl": "var(--radius-2xl)",
        full: "var(--radius-full)"
      },
      boxShadow: {
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
        xl: "var(--shadow-xl)",
        panel: "var(--shadow-panel)",
        button: "var(--shadow-button)",
        focus: "var(--shadow-focus)"
      }
    }
  },
  plugins: []
};

export default config;
