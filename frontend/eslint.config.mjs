import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTypescript,
  {
    settings: { next: { rootDir: import.meta.dirname } },
    rules: {
      "@next/next/no-html-link-for-pages": ["error", `${import.meta.dirname}/app`],
    },
  },
  globalIgnores([
    "**/.next/**",
    "**/next-env.d.ts",
    "**/test-results/**",
    "**/playwright-report/**",
    "**/node_modules/**",
  ]),
]);
