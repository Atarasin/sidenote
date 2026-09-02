// 把 pdfjs-dist 的 cmaps / standard_fonts 拷进 public/pdfjs（dev 与 build 都需要）
import { cpSync, mkdirSync, rmSync } from "node:fs";

rmSync("public/pdfjs", { recursive: true, force: true });
mkdirSync("public/pdfjs", { recursive: true });
cpSync("node_modules/pdfjs-dist/cmaps", "public/pdfjs/cmaps", { recursive: true });
cpSync("node_modules/pdfjs-dist/standard_fonts", "public/pdfjs/standard_fonts", {
  recursive: true,
});
console.log("pdfjs assets copied to public/pdfjs");
