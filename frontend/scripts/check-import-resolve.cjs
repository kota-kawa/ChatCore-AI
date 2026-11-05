#!/usr/bin/env node
// フロントエンドのimport先が解決できるか検査する。
// Checks that frontend import targets resolve.


const fs = require("fs");
const path = require("path");
const { createRequire, builtinModules } = require("module");

const projectRoot = path.resolve(__dirname, "..");
const requireFromRoot = createRequire(path.join(projectRoot, "package.json"));

const scanDirs = [
  "pages",
  "scripts",
  "components"
];

const scanExts = new Set([".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"]);
const ignoreDirs = new Set(["node_modules", ".next", ".git"]);

const builtinSet = new Set([
  ...builtinModules,
  ...builtinModules
    .filter((name) => !name.startsWith("node:"))
    .map((name) => `node:${name}`)
]);

const importPatterns = [
  /import\s+(?:[^"'`]*?\s+from\s+)?["'`]([^"'`]+)["'`]/g,
  /export\s+[^"'`]*?\s+from\s+["'`]([^"'`]+)["'`]/g,
  /import\(\s*["'`]([^"'`]+)["'`]\s*\)/g,
  /require\(\s*["'`]([^"'`]+)["'`]\s*\)/g
];

function collectFiles(dir) {
  const files = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (ignoreDirs.has(entry.name)) continue;
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectFiles(fullPath));
      continue;
    }
    if (entry.isFile() && scanExts.has(path.extname(entry.name))) {
      files.push(fullPath);
    }
  }
  return files;
}

function isBareModule(specifier) {
  if (!specifier) return false;
  if (specifier.startsWith(".") || specifier.startsWith("/") || specifier.startsWith("#")) {
    return false;
  }
  if (specifier.startsWith("http://") || specifier.startsWith("https://")) {
    return false;
  }
  return true;
}

function extractImports(code) {
  const results = [];
  for (const pattern of importPatterns) {
    let match;
    while ((match = pattern.exec(code)) !== null) {
      results.push(match[1]);
    }
  }
  return results;
}

function rel(filePath) {
  return path.relative(projectRoot, filePath).replace(/\\/g, "/");
}

const missingByModule = new Map();

for (const relativeDir of scanDirs) {
  const fullDir = path.join(projectRoot, relativeDir);
  if (!fs.existsSync(fullDir)) continue;

  const files = collectFiles(fullDir);
  for (const filePath of files) {
    const code = fs.readFileSync(filePath, "utf8");
    const imports = extractImports(code);

    for (const specifier of imports) {
      if (!isBareModule(specifier)) continue;
      if (builtinSet.has(specifier)) continue;

      try {
        requireFromRoot.resolve(specifier);
      } catch {
        const existing = missingByModule.get(specifier) || [];
        existing.push(rel(filePath));
        missingByModule.set(specifier, existing);
      }
    }
  }
}

if (missingByModule.size > 0) {
  console.error("Missing module(s) detected in frontend imports:");
  for (const [specifier, files] of missingByModule.entries()) {
    console.error(`- ${specifier}`);
    for (const file of Array.from(new Set(files)).sort()) {
      console.error(`  referenced from: ${file}`);
    }
  }
  console.error("\nRun `npm install` (or `npm ci`) in /frontend and ensure dependencies are declared.");
  process.exit(1);
}

console.log("Frontend import resolution check passed.");
