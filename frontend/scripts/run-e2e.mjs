import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const apiMode = process.argv.includes("--api");
const environment = {
  ...process.env,
  NEXT_PUBLIC_MOCK: apiMode ? "0" : "1",
  NEXT_PUBLIC_API_BASE: "/api",
  NEXT_TELEMETRY_DISABLED: "1",
};
for (const [script, args] of [
  [require.resolve("next/dist/bin/next"), ["build", "--webpack"]],
  [
    require.resolve("@playwright/test/cli"),
    [
      "test",
      "--config",
      "playwright.config.ts",
      ...(apiMode ? ["--grep", "@api-boundary"] : ["--grep-invert", "@api-boundary"]),
    ],
  ],
]) {
  const result = spawnSync(process.execPath, [script, ...args], {
    stdio: "inherit",
    env: environment,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
