// Unit tests for the pure parts of the web app, with no extra packages: Node's built-in test runner, and the
// TypeScript compiler the app already has, hooked into require() to load .ts/.tsx files and the "@/..." alias.
//   npm test
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("typescript");

const SRC = path.join(__dirname, "..", "src");

const resolve = Module._resolveFilename;
Module._resolveFilename = function (request, parent, ...rest) {
  if (request.startsWith("@/")) request = path.join(SRC, request.slice(2));
  if (request.endsWith(".css")) return require.resolve("./empty.cjs");
  return resolve.call(this, request, parent, ...rest);
};
for (const ext of [".ts", ".tsx"]) {
  require.extensions[ext] = (mod, file) => {
    const out = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      fileName: file,
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    });
    mod._compile(out.outputText, file);
  };
}

function find(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? find(path.join(dir, e.name)) : e.name.endsWith(".test.ts") ? [path.join(dir, e.name)] : []);
}
for (const f of find(SRC)) require(f);
