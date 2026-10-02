import { rgb, LineCapStyle, degrees } from "../../vendor/pdf-lib/pdf-lib.esm.min.js";

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
  const mx = x + size / 2;
  const my = y + size / 2;
  const inset = size * 0.22;

  /** 田字辅助线（虚线） */
  const drawTianGuides = () => {
    line(page, { x, y: my }, { x: x + size, y: my }, DASHED);
    line(page, { x: mx, y }, { x: mx, y: y + size }, DASHED);
  };

  /** 米字辅助线（虚线：十字 + 两对角线） */
  const drawMiGuides = () => {
    drawTianGuides();
    line(page, { x, y }, { x: x + size, y: y + size }, DASHED);
    line(page, { x: x + size, y }, { x, y: y + size }, DASHED);
  };

  /** 回宫内框（虚线） */
  const drawHuiInner = () => {
    rectBorder(page, x + inset, y + inset, size - 2 * inset, DASHED);
  };

  switch (gridType) {
    case "hengxian":
      // 仅字下横线（方框最下一边），无四周边框
      line(page, { x, y }, { x: x + size, y }, SOLID);
      break;
    case "tian":
      rectBorder(page, x, y, size, SOLID);
      drawTianGuides();
      break;
    case "mi":
      rectBorder(page, x, y, size, SOLID);
      drawMiGuides();
      break;
    case "jiugong":
      rectBorder(page, x, y, size, SOLID);
      for (let i = 1; i <= 2; i++) {
        const off = (size * i) / 3;
        line(page, { x: x + off, y }, { x: x + off, y: y + size }, DASHED);
        line(page, { x, y: y + off }, { x: x + size, y: y + off }, DASHED);
      }
      break;
    case "huigong":
      rectBorder(page, x, y, size, SOLID);
      drawHuiInner();
      break;
    case "huitian":
      // 回田格：外框 + 回宫内框 + 田字线
      rectBorder(page, x, y, size, SOLID);
      drawHuiInner();
      drawTianGuides();
      break;
    case "huimi":
      // 回米格：外框 + 回宫内框 + 米字线
      rectBorder(page, x, y, size, SOLID);
      drawHuiInner();
      drawMiGuides();
      break;
    case "fang":
    default:
      rectBorder(page, x, y, size, SOLID);
      break;
  }
}

/**
 * 按字形墨迹包围盒把汉字放进字格中央。
 * pdf-lib 的 drawText 以基线为原点；字体 ascent/descent／字号一半都不等于墨心，
 * 楷体实测墨心约在基线上方 0.35×字号，按字号一半算会整体偏下。
 * 做法对齐常见字帖引擎：取 fontkit glyph.bbox 再换算到 pt。
 * @param {object} font pdf-lib PDFFont
 * @param {string} char
 * @param {number} fontSize
 * @param {number} cellX
 * @param {number} cellY
 * @param {number} cellSize
 * @returns {{ textX: number, textY: number }}
 */
function placeCharInCell(font, char, fontSize, cellX, cellY, cellSize) {
  const cx = cellX + cellSize / 2;
  const cy = cellY + cellSize / 2;
  const advanceW = font.widthOfTextAtSize(char, fontSize);
  let textX = cx - advanceW / 2;
  // 回退：em 盒近似（仍可能略偏）
  let textY = cy - fontSize / 2;

  const embedder = font?.embedder;
  const fkFont = embedder?.font;
  const cp = [...char][0]?.codePointAt?.(0);
  if (fkFont && typeof fkFont.glyphForCodePoint === "function" && cp != null) {
    try {
      const glyph = fkFont.glyphForCodePoint(cp);
      const bbox = glyph?.bbox;
      if (
        bbox &&
        Number.isFinite(bbox.minX) &&
        Number.isFinite(bbox.maxX) &&
        Number.isFinite(bbox.minY) &&
        Number.isFinite(bbox.maxY)
      ) {
        // pdf-lib：glyph 坐标先 × embedder.scale 进 1000em，再 × size/1000 成 pt
        // 等价于 size / unitsPerEm
        const upe = fkFont.unitsPerEm || 1000;
        const s = fontSize / upe;
        const midX = ((bbox.maxX + bbox.minX) / 2) * s;
        const midY = ((bbox.maxY + bbox.minY) / 2) * s;
        // drawText 的 (x,y) 是笔位／基线；墨心相对笔位偏移 (midX, midY)
        textX = cx - midX;
        textY = cy - midY;
      }
    } catch {
      /* keep fallback */
    }
  }
  return { textX, textY };
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
    pinyinFont,
    pinyinSizePt,
    pinyinGapFromCellPt,
    traceColor,
    traceOpacity,
    showPinyin,
    pinyinSide,
    charFillRatio,
  } = params;

  drawGrid(page, x, y, size, gridType);

  if (char && role !== "blank") {
    const fill =
      Number.isFinite(charFillRatio) && charFillRatio > 0
        ? Math.min(1, Math.max(0.4, charFillRatio))
        : 0.85;
    const fontSize = size * fill;
    const { textX, textY } = placeCharInCell(font, char, fontSize, x, y, size);

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
    const pySize = pinyinSizePt || 10.5;
    const pyGap = pinyinGapFromCellPt ?? 5;
    const side = pinyinSide || "top";
    // 首选拼音字体；缺字／编码失败时回退汉字字体（避免 Helvetica/WinAnsi 炸掉整页）
    const fontsToTry = [pinyinFont, font].filter(Boolean);
    for (const pyFont of fontsToTry) {
      try {
        const pyWidth = pyFont.widthOfTextAtSize(pinyin, pySize);
        if (side === "right") {
          // 竖排：拼音在格右侧，顺时针 90°（字串自上而下；字形向 +x）
          page.drawText(pinyin, {
            x: x + size + pyGap,
            y: y + (size + pyWidth) / 2,
            size: pySize,
            font: pyFont,
            color: rgb(0.25, 0.25, 0.25),
            rotate: degrees(-90),
          });
        } else {
          page.drawText(pinyin, {
            x: x + (size - pyWidth) / 2,
            y: y + size + pyGap,
            size: pySize,
            font: pyFont,
            color: rgb(0.25, 0.25, 0.25),
          });
        }
        break;
      } catch {
        /* try next font；皆失败则跳过该拼音，不阻断整份 PDF */
      }
    }
  }
}

/** @param {string} hex #RRGGBB */
export function hexToRgb(hex) {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.replace(/./g, "$&$&") : h, 16);
  return rgb(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255);
}
