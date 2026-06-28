import { PDFDocument, rgb, StandardFonts } from "../../vendor/pdf-lib/pdf-lib.esm.min.js";
import { buildLayout, cmToPt, mmToPt } from "./layout.js";
import { drawCellContent, hexToRgb } from "./grid.js";
import { resolveFontBytes } from "./fonts.js";

/** @returns {object} fontkit from UMD script */
function getFontkit() {
  const fk = window.fontkit;
  if (!fk) throw new Error("FONTKIT_MISSING");
  return fk;
}

const A4_WIDTH_PT = cmToPt(21);
const A4_HEIGHT_PT = cmToPt(29.7);
const MARGIN_MM = 15;
const FOOTER_MM = 8;

/**
 * @param {import('./input.js').CharGroup[]} groups
 * @param {object} config
 */
export async function generatePracticePdf(groups, config) {
  if (!groups.length) throw new Error("EMPTY_CONTENT");

  const {
    fontChoice = "kaiti",
    gridType = "mi",
    cellSizeCm = 1.2,
    modelCount = 1,
    traceCount = 2,
    blankCount = 2,
    traceColorHex = "#CC0000",
    traceOpacity = 0.7,
    showPinyin = true,
    layoutMode = "continuous",
    rowGapMm = 4,
    groupGapMm = layoutMode === "grouped" ? 10 : 8,
  } = config;

  const marginPt = mmToPt(MARGIN_MM);
  const footerHeightPt = mmToPt(FOOTER_MM + 4);
  const cellSizePt = cmToPt(cellSizeCm);
  const usableWidthPt = A4_WIDTH_PT - 2 * marginPt;

  const layout = buildLayout(groups, {
    pageHeightPt: A4_HEIGHT_PT,
    marginTopPt: marginPt,
    marginBottomPt: marginPt,
    footerHeightPt,
    cellSizePt,
    usableWidthPt,
    showPinyin,
    layoutMode,
    modelCount,
    traceCount,
    blankCount,
    rowGapMm,
    groupGapMm,
  });

  const pdfDoc = await PDFDocument.create();
  pdfDoc.registerFontkit(getFontkit());

  const { buffer: fontBytes } = await resolveFontBytes(fontChoice);
  const hanFont = await pdfDoc.embedFont(fontBytes, { subset: true });
  const footerFont = await pdfDoc.embedFont(StandardFonts.Helvetica);

  const traceColor = hexToRgb(traceColorHex);
  const totalPages = layout.pages.length;
  const dateStr = formatLocalDate(new Date());

  for (let pi = 0; pi < layout.pages.length; pi++) {
    const pageData = layout.pages[pi];
    const page = pdfDoc.addPage([A4_WIDTH_PT, A4_HEIGHT_PT]);
    const contentTop = A4_HEIGHT_PT - marginPt;

    let prevOffset = 0;
    for (const row of pageData.rows) {
      const rowTopFromContent = row.yOffsetPt;
      const rowGapExtra = row.yOffsetPt - prevOffset - layout.rowHeightPt;
      prevOffset = row.yOffsetPt;

      if (!row.cells?.length) continue;

      const rowBottomY = contentTop - rowTopFromContent;
      const cellY = rowBottomY;

      for (let ci = 0; ci < row.cells.length; ci++) {
        const cell = row.cells[ci];
        const cellX = marginPt + ci * cellSizePt;
        drawCellContent(page, {
          x: cellX,
          y: cellY,
          size: cellSizePt,
          gridType,
          char: cell.char,
          pinyin: cell.pinyin,
          role: cell.role,
          font: hanFont,
          traceColor,
          traceOpacity,
          showPinyin,
          pinyinBandPt: layout.pinyinBandPt,
        });
      }

      void rowGapExtra;
    }

    const footerText = `${pi + 1}/${totalPages}      ${dateStr}`;
    const footerSize = 9;
    const footerWidth = footerFont.widthOfTextAtSize(footerText, footerSize);
    page.drawText(footerText, {
      x: (A4_WIDTH_PT - footerWidth) / 2,
      y: mmToPt(FOOTER_MM),
      size: footerSize,
      font: footerFont,
      color: rgb(0.35, 0.35, 0.35),
    });
  }

  const bytes = await pdfDoc.save();
  return new Blob([bytes], { type: "application/pdf" });
}

/** @param {Date} d */
function formatLocalDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * @param {object} pageSpec
 * @param {import('./input.js').CharGroup[]} groups
 * @param {object} config
 */
export function estimatePageCount(groups, config) {
  if (!groups.length) return 0;
  const marginPt = mmToPt(MARGIN_MM);
  const footerHeightPt = mmToPt(FOOTER_MM + 4);
  const cellSizePt = cmToPt(config.cellSizeCm ?? 1.2);
  const usableWidthPt = A4_WIDTH_PT - 2 * marginPt;
  const layout = buildLayout(groups, {
    pageHeightPt: A4_HEIGHT_PT,
    marginTopPt: marginPt,
    marginBottomPt: marginPt,
    footerHeightPt,
    cellSizePt,
    usableWidthPt,
    showPinyin: config.showPinyin !== false,
    layoutMode: config.layoutMode ?? "continuous",
    modelCount: config.modelCount ?? 1,
    traceCount: config.traceCount ?? 2,
    blankCount: config.blankCount ?? 2,
    rowGapMm: config.rowGapMm ?? 4,
    groupGapMm: config.groupGapMm ?? (config.layoutMode === "grouped" ? 10 : 8),
  });
  return layout.pages.length;
}
