import { PDFDocument, rgb, StandardFonts } from "../../vendor/pdf-lib/pdf-lib.esm.min.js";
import { buildLayout, cmToPt, mmToPt } from "./layout.js";
import { drawCellContent, hexToRgb } from "./grid.js";
import { resolveFontBytes, resolvePinyinFontBytes, PINYIN_FONT_SIZE_PT, PINYIN_GAP_FROM_CELL_PT } from "./fonts.js";

/** @returns {object} fontkit from UMD script */
function getFontkit() {
  const fk = window.fontkit;
  if (!fk) throw new Error("FONTKIT_MISSING");
  return fk;
}

/** @typedef {'a4-portrait'|'a4-landscape'|'a5-portrait'|'a5-landscape'} PaperId */

/** @type {Record<PaperId, { id: PaperId, label: string, footerTag: string, widthMm: number, heightMm: number }>} */
export const PAPER_PRESETS = {
  "a4-portrait": { id: "a4-portrait", label: "A4 竖版", footerTag: "A4P", widthMm: 210, heightMm: 297 },
  "a4-landscape": { id: "a4-landscape", label: "A4 横版", footerTag: "A4L", widthMm: 297, heightMm: 210 },
  "a5-portrait": { id: "a5-portrait", label: "A5 竖版", footerTag: "A5P", widthMm: 148, heightMm: 210 },
  "a5-landscape": { id: "a5-landscape", label: "A5 横版", footerTag: "A5L", widthMm: 210, heightMm: 148 },
};

/**
 * @param {string} [paperId]
 * @returns {{ id: PaperId, label: string, widthMm: number, heightMm: number, pageWidthPt: number, pageHeightPt: number }}
 */
export function resolvePaperSize(paperId) {
  const preset = PAPER_PRESETS[paperId] || PAPER_PRESETS["a4-portrait"];
  return {
    ...preset,
    pageWidthPt: mmToPt(preset.widthMm),
    pageHeightPt: mmToPt(preset.heightMm),
  };
}

const DEFAULT_MARGIN_MM = 15;
const FOOTER_MM = 8;
/** 超版心后仍保留的页边安全线 */
const HARD_EDGE_MM = 2;

/**
 * @param {object} config
 */
function layoutOptsFromConfig(config) {
  const flow = config.layoutMode || config.flow || "group";
  const direction = config.writeDirection || config.direction || "horizontal";
  const marginTopMm = config.marginTopMm ?? DEFAULT_MARGIN_MM;
  const marginBottomMm = config.marginBottomMm ?? DEFAULT_MARGIN_MM;
  const marginLeftMm = config.marginLeftMm ?? DEFAULT_MARGIN_MM;
  const marginRightMm = config.marginRightMm ?? DEFAULT_MARGIN_MM;
  const overflowMm = Math.max(0, Math.min(30, Number(config.overflowMm ?? 5) || 0));
  const footerHeightPt = mmToPt(FOOTER_MM + 4);
  const cellSizePt = cmToPt(config.cellSizeCm ?? 1.5);
  const paper = resolvePaperSize(config.paperSize || config.paper);
  return {
    pageHeightPt: paper.pageHeightPt,
    pageWidthPt: paper.pageWidthPt,
    marginTopPt: mmToPt(marginTopMm),
    marginBottomPt: mmToPt(marginBottomMm),
    marginLeftPt: mmToPt(marginLeftMm),
    marginRightPt: mmToPt(marginRightMm),
    overflowMm,
    hardEdgePt: mmToPt(HARD_EDGE_MM),
    footerHeightPt,
    cellSizePt,
    showPinyin: config.showPinyin !== false,
    layoutMode: flow,
    writeDirection: direction,
    modelCount: config.modelCount ?? 1,
    traceCount: config.traceCount ?? 2,
    blankCount: config.blankCount ?? 2,
    rowGapMm: config.rowGapMm ?? 0,
    groupGapMm: config.groupGapMm ?? 2,
  };
}

/**
 * @param {import('./input.js').CharGroup[]} groups
 * @param {object} config
 */
export async function generatePracticePdf(groups, config) {
  if (!groups.length) throw new Error("EMPTY_CONTENT");

  const {
    fontChoice = "kaiti",
    gridType = "tian",
    traceColorHex = "#CC0000",
    traceOpacity = 0.7,
    showPinyin = true,
    charFillRatio = 0.85,
  } = config;

  const paper = resolvePaperSize(config.paperSize || config.paper);
  const layout = buildLayout(groups, layoutOptsFromConfig(config));

  const pdfDoc = await PDFDocument.create();
  pdfDoc.registerFontkit(getFontkit());

  const { buffer: fontBytes } = await resolveFontBytes(fontChoice);
  const hanFont = await pdfDoc.embedFont(fontBytes, { subset: true });
  const footerFont = await pdfDoc.embedFont(StandardFonts.Helvetica);

  /**
   * 拼音字体：优先系统拼音字体；找不到时用汉字字体。
   * 不可回退 Helvetica——带调号拼音（ā á ǎ à 等）超出 WinAnsi，会导致整份 PDF 生成失败。
   */
  let pinyinFont = hanFont;
  if (showPinyin) {
    const pyResolved = await resolvePinyinFontBytes();
    if (pyResolved?.buffer) {
      try {
        pinyinFont = await pdfDoc.embedFont(pyResolved.buffer, { subset: true });
      } catch {
        pinyinFont = hanFont;
      }
    }
  }

  const traceColor = hexToRgb(traceColorHex);
  const totalPages = layout.pages.length;
  const dateStr = formatLocalDate(new Date());
  const cellSizeCm = config.cellSizeCm ?? 1.5;
  const cellSizeMmStr = formatCellSizeMm(cellSizeCm);

  for (let pi = 0; pi < layout.pages.length; pi++) {
    const pageData = layout.pages[pi];
    const page = pdfDoc.addPage([paper.pageWidthPt, paper.pageHeightPt]);

    for (const cell of pageData.cells || []) {
      drawCellContent(page, {
        x: cell.x,
        y: cell.y,
        size: cell.size ?? layout.cellSizePt,
        gridType,
        char: cell.char,
        pinyin: cell.pinyin,
        role: cell.role,
        font: hanFont,
        pinyinFont,
        pinyinSizePt: PINYIN_FONT_SIZE_PT,
        pinyinGapFromCellPt: PINYIN_GAP_FROM_CELL_PT,
        traceColor,
        traceOpacity,
        showPinyin,
        pinyinSide: cell.pinyinSide || (layout.writeDirection === "vertical" ? "right" : "top"),
        charFillRatio,
      });
    }

    const footerText = `${pi + 1}/${totalPages}      ${dateStr}      ${cellSizeMmStr}      ${paper.footerTag}`;
    const footerSize = 9;
    const footerWidth = footerFont.widthOfTextAtSize(footerText, footerSize);
    page.drawText(footerText, {
      x: (paper.pageWidthPt - footerWidth) / 2,
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

/** @param {number} cellSizeCm */
function formatCellSizeMm(cellSizeCm) {
  const mm = Number(cellSizeCm) * 10;
  const text = Number.isInteger(mm) ? String(mm) : String(Math.round(mm * 10) / 10);
  return `${text}mm`;
}

/**
 * @param {import('./input.js').CharGroup[]} groups
 * @param {object} config
 */
export function estimatePageCount(groups, config) {
  if (!groups.length) return 0;
  const layout = buildLayout(groups, layoutOptsFromConfig(config));
  return layout.pages.length;
}
