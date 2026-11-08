import { ESLint } from "eslint";
import { fileURLToPath } from "node:url";

const eslint = new ESLint({
  cwd: fileURLToPath(new URL("../..", import.meta.url)),
  overrideConfigFile: fileURLToPath(new URL("../eslint.config.mjs", import.meta.url)),
});
const results = await eslint.lintFiles([
  "frontend/**/*.{ts,tsx,mjs}",
  "tests/e2e/**/*.{ts,tsx,mjs}",
]);
const formatter = await eslint.loadFormatter("stylish");
process.stdout.write(formatter.format(results));
const failures = results.reduce(
  (total, result) => total + result.errorCount + result.warningCount,
  0,
);
process.stdout.write(
  `${results.length} files checked; ${failures} lint errors or warnings.\n`,
);
if (failures > 0) process.exitCode = 1;
