/**
 * 冒烟测试：不依赖浏览器，用系统 simkai.ttf 生成一页 PDF。
 * 用法：node scripts/smoke_print_pdf.mjs
 */
import { readFileSync, writeFileSync, existsSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import { PDFDocument, rgb, StandardFonts } from "../web/vendor/pdf-lib/pdf-lib.esm.min.js";
import { buildLayout, cmToPt, mmToPt } from "../web/js/print/layout.js";
import { drawCellContent, hexToRgb } from "../web/js/print/grid.js";
import { itemsToSingleGroup } from "../web/js/print/input.js";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const fontCandidates = [
  "C:/Windows/Fonts/simkai.ttf",
  "C:/Windows/Fonts/STKAITI.TTF",
];

const fontPath = fontCandidates.find((p) => existsSync(p));
if (!fontPath) {
  console.error("未找到系统楷体，跳过 PDF 冒烟测试");
  process.exit(0);
}

const fontkitCode = readFileSync(join(root, "web/vendor/pdf-fontkit/fontkit.umd.min.js"), "utf8");
globalThis.self = globalThis;
globalThis.window = globalThis;
// UMD 在 ESM 中 this 为 undefined，改为挂到 globalThis
eval(fontkitCode.replace("(this,(function", "(globalThis,(function"));
const fontkit = globalThis.fontkit;
if (!fontkit) throw new Error("fontkit UMD 未加载");

const groups = itemsToSingleGroup([
  { char: "春", pinyin: "chūn" },
  { char: "夏", pinyin: "xià" },
]);

const cellSizeCm = 1.2;
const marginPt = mmToPt(15);
const cellSizePt = cmToPt(cellSizeCm);
const layout = buildLayout(groups, {
  pageHeightPt: cmToPt(29.7),
  marginTopPt: marginPt,
  marginBottomPt: marginPt,
  footerHeightPt: mmToPt(12),
  cellSizePt,
  usableWidthPt: cmToPt(21) - 2 * marginPt,
  showPinyin: true,
  layoutMode: "continuous",
  modelCount: 1,
  traceCount: 2,
  blankCount: 2,
  rowGapMm: 4,
  groupGapMm: 8,
});

const pdfDoc = await PDFDocument.create();
pdfDoc.registerFontkit(fontkit);
const fontBytes = readFileSync(fontPath);
const hanFont = await pdfDoc.embedFont(fontBytes, { subset: true });
const footerFont = await pdfDoc.embedFont(StandardFonts.Helvetica);

const page = pdfDoc.addPage([cmToPt(21), cmToPt(29.7)]);
const contentTop = cmToPt(29.7) - marginPt;
const row = layout.pages[0].rows[0];
const cellY = contentTop - row.yOffsetPt;
for (let ci = 0; ci < row.cells.length; ci++) {
  drawCellContent(page, {
    x: marginPt + ci * cellSizePt,
    y: cellY,
    size: cellSizePt,
    gridType: "mi",
    char: row.cells[ci].char,
    pinyin: row.cells[ci].pinyin,
    role: row.cells[ci].role,
    font: hanFont,
    traceColor: hexToRgb("#CC0000"),
    traceOpacity: 0.7,
    showPinyin: true,
    pinyinBandPt: layout.pinyinBandPt,
  });
}

const footerText = `1/1      2026-06-28`;
page.drawText(footerText, {
  x: (cmToPt(21) - footerFont.widthOfTextAtSize(footerText, 9)) / 2,
  y: mmToPt(8),
  size: 9,
  font: footerFont,
  color: rgb(0.35, 0.35, 0.35),
});

const out = join(root, "output", "_smoke_print.pdf");
writeFileSync(out, await pdfDoc.save());
console.log("OK:", out, "font:", fontPath);
