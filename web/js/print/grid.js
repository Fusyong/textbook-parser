import { rgb, LineCapStyle } from "../../vendor/pdf-lib/pdf-lib.esm.min.js";

const GRID_COLOR = rgb(0.15, 0.15, 0.15);
const INNER_COLOR = rgb(0.55, 0.55, 0.55);
const SOLID = { thickness: 0.55, color: GRID_COLOR };
const DASHED = { thickness: 0.4, color: INNER_COLOR, dashArray: [2.5, 2.5] };

/**
 * @param {import('../../vendor/pdf-lib/pdf-lib.esm.min.js').PDFPage} page
 * @param {{ x: number, y: number }} start
 * @param {{ x: number, y: number }} end
 * @param {object} style
 */
function line(page, start, end, style) {
  page.drawLine({
    start,
    end,
    thickness: style.thickness,
    color: style.color,
    dashArray: style.dashArray,
    dashPhase: style.dashArray ? 0 : undefined,
    lineCap: LineCapStyle.Butt,
  });
}

/** @param {import('../../vendor/pdf-lib/pdf-lib.esm.min.js').PDFPage} page */
function rectBorder(page, x, y, size, style) {
  line(page, { x, y }, { x: x + size, y }, style);
  line(page, { x: x + size, y }, { x: x + size, y: y + size }, style);
  line(page, { x: x + size, y: y + size }, { x, y: y + size }, style);
  line(page, { x, y: y + size }, { x, y }, style);
}

/**
 * @param {import('../../vendor/pdf-lib/pdf-lib.esm.min.js').PDFPage} page
 * @param {number} x
 * @param {number} y bottom-left
 * @param {number} size
 * @param {string} gridType
 */
export function drawGrid(page, x, y, size, gridType) {
  rectBorder(page, x, y, size, SOLID);
  const mx = x + size / 2;
  const my = y + size / 2;

  switch (gridType) {
    case "tian":
      line(page, { x, y: my }, { x: x + size, y: my }, DASHED);
      line(page, { x: mx, y }, { x: mx, y: y + size }, DASHED);
      break;
    case "mi":
      line(page, { x, y: my }, { x: x + size, y: my }, DASHED);
      line(page, { x: mx, y }, { x: mx, y: y + size }, DASHED);
      line(page, { x, y }, { x: x + size, y: y + size }, DASHED);
      line(page, { x: x + size, y }, { x, y: y + size }, DASHED);
      break;
    case "jiugong":
      for (let i = 1; i <= 2; i++) {
        const off = (size * i) / 3;
        line(page, { x: x + off, y }, { x: x + off, y: y + size }, DASHED);
        line(page, { x, y: y + off }, { x: x + size, y: y + off }, DASHED);
      }
      break;
    case "huigong": {
      const inset = size * 0.22;
      rectBorder(page, x + inset, y + inset, size - 2 * inset, DASHED);
      break;
    }
    case "hengxian":
      for (let i = 1; i <= 2; i++) {
        const ly = y + (size * i) / 3;
        line(page, { x, y: ly }, { x: x + size, y: ly }, DASHED);
      }
      break;
    case "fang":
    default:
      break;
  }
}

/**
 * @param {import('../../vendor/pdf-lib/pdf-lib.esm.min.js').PDFPage} page
 * @param {object} params
 */
export function drawCellContent(page, params) {
  const {
    x,
    y,
    size,
    gridType,
    char,
    pinyin,
    role,
    font,
    traceColor,
    traceOpacity,
    showPinyin,
    pinyinBandPt,
  } = params;

  drawGrid(page, x, y, size, gridType);

  if (char && role !== "blank") {
    const fontSize = size * 0.68;
    const textWidth = font.widthOfTextAtSize(char, fontSize);
    const textX = x + (size - textWidth) / 2;
    const textY = y + (size - fontSize) / 2 + fontSize * 0.08;

    let color = rgb(0, 0, 0);
    let opacity = 1;
    if (role === "trace") {
      color = traceColor;
      opacity = traceOpacity;
    }

    page.drawText(char, {
      x: textX,
      y: textY,
      size: fontSize,
      font,
      color,
      opacity,
    });
  }

  if (showPinyin && pinyin && role !== "blank") {
    const pySize = Math.max(6, size * 0.2);
    const pyWidth = font.widthOfTextAtSize(pinyin, pySize);
    const pyX = x + (size - pyWidth) / 2;
    const pyY = y + size + pinyinBandPt * 0.22;
    page.drawText(pinyin, {
      x: pyX,
      y: pyY,
      size: pySize,
      font,
      color: rgb(0.25, 0.25, 0.25),
    });
  }
}

/** @param {string} hex #RRGGBB */
export function hexToRgb(hex) {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.replace(/./g, "$&$&") : h, 16);
  return rgb(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255);
}
