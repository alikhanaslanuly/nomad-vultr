import { cpSync } from "node:fs";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const portArgument = process.argv.indexOf("--port");
const port = Number(
  portArgument >= 0 ? process.argv[portArgument + 1] : process.env.PORT || 3000,
);
if (!Number.isInteger(port) || port < 1 || port > 65535)
  throw new Error("Invalid server port");
cpSync(`${root}/.next/static`, `${root}/.next/standalone/.next/static`, {
  recursive: true,
});
const child = spawn(process.execPath, [`${root}/.next/standalone/server.js`], {
  stdio: "inherit",
  env: { ...process.env, PORT: String(port), HOSTNAME: "127.0.0.1" },
});
child.on("error", (error) => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
child.on("exit", (code) => {
  process.exitCode = code ?? 1;
});
process.on("SIGTERM", () => child.kill("SIGTERM"));
process.on("SIGINT", () => child.kill("SIGINT"));
