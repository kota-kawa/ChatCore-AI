const { readdirSync } = require("node:fs");
const { join } = require("node:path");
const { spawnSync } = require("node:child_process");

function findLogicTests(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return findLogicTests(path);
    return entry.isFile() && entry.name.endsWith(".test.ts") ? [path] : [];
  });
}

const testFiles = findLogicTests("tests").sort();
if (testFiles.length === 0) {
  console.error("No frontend logic tests were found.");
  process.exit(1);
}

const result = spawnSync(
  process.execPath,
  ["--import", "tsx", "--test", ...testFiles],
  { stdio: "inherit" }
);

if (result.error) {
  console.error("Failed to start the frontend logic tests.", result.error);
  process.exit(1);
}

process.exit(result.status ?? 1);
