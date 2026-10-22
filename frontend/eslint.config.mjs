import js from "@eslint/js";
import nextPlugin from "@next/eslint-plugin-next";
import tseslint from "typescript-eslint";

export default [
  {
    ignores: [".next/**", "node_modules/**", "next-env.d.ts", "public/widget.js"],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["tests/assistant-ui-widget.test.mjs", "tests/native-widget-session.test.mjs"],
    languageOptions: {
      globals: {
        console: "readonly",
        document: "readonly",
        process: "readonly",
        sessionStorage: "readonly",
        URL: "readonly",
        URLSearchParams: "readonly",
        window: "readonly",
      },
    },
  },
  {
    files: ["**/*.{ts,tsx}"],
    plugins: {
      "@next/next": nextPlugin,
    },
    rules: {
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,
    },
  },
];
