/**
 * 分组版式 × 书写方向
 * flow: continuous | break | group | group-line
 * direction: horizontal | vertical
 */

/** @typedef {'model'|'trace'|'blank'} CellRole */
/** @typedef {'continuous'|'break'|'group'|'group-line'} FlowMode */
/** @typedef {'horizontal'|'vertical'} WriteDirection */
/** @typedef {{ char: string, pinyin: string, role: CellRole, groupIndex: number, atomId?: number }} LayoutCell */
/** @typedef {LayoutCell & { x: number, y: number, size: number, pinyinSide?: 'top'|'right' }} PlacedCell */
/** @typedef {{ cells: PlacedCell[], pageIndex: number }} LayoutPage */

import { PINYIN_FONT_SIZE_PT, PINYIN_GAP_FROM_CELL_PT } from "./fonts.js";

export const CM_TO_PT = 72 / 2.54;
export const MM_TO_PT = 72 / 25.4;

export function cmToPt(cm) {
  return cm * CM_TO_PT;
}

export function mmToPt(mm) {
  return mm * MM_TO_PT;
}

const LINE_START_FORBIDDEN = new Set([
  "，", "。", "、", "；", "：", "？", "！",
  ",", ".", ";", ":", "?", "!", "､",
  "）", ")", "］", "]", "】", "〕", "〉", "》", "」", "』", "”", "’", "›", "»",
  "—", "～", "…", "・", "·", "%", "‰", "℃",
]);

export function isLineStartForbidden(char) {
  const s = String(char ?? "");
  if (!s) return false;
  for (const ch of s) {
    if (LINE_START_FORBIDDEN.has(ch)) return true;
  }
  return false;
}

function normalizeFlow(mode) {
  if (mode === "grouped") return "group";
  if (mode === "continuous" || mode === "break" || mode === "group" || mode === "group-line") {
    return mode;
  }
  return "group";
}

/**
 * 输入排版（断行分组，空格占格）：同一输入行已是一个排版单元（解析时空格已占格）。
 * 若仍收到同行多组（兼容旧数据），则合并且在组间补一空格。
 * @param {import('./input.js').CharGroup[]} groups
 */
export function coalesceByInputLine(groups) {
  /** @type {import('./input.js').CharGroup[]} */
  const units = [];
  for (const g of groups) {
    const startNew =
      !units.length || g.inputLineBreakBefore || g.sectionBreakBefore;
    if (startNew) {
      units.push({
        items: [...(g.items || [])],
        sectionBreakBefore: !!g.sectionBreakBefore,
        inputLineBreakBefore: !!g.inputLineBreakBefore,
      });
    } else {
      const dest = units[units.length - 1];
      dest.items.push({ char: "", pinyin: "" });
      dest.items.push(...(g.items || []));
    }
  }
  return units.filter((u) => u.items.length);
}

/**
 * @param {import('./input.js').CharGroup[]} groups
 * @param {FlowMode} flow
 */
export function prepareUnits(groups, flow) {
  const f = normalizeFlow(flow);
  if (f === "group-line") return coalesceByInputLine(groups);
  return (groups || []).filter((g) => g.items?.length);
}

/**
 * 整组节奏：返回每一遍的字格数组（范／描／空）。
 * @param {import('./input.js').CharGroup} unit
 * @param {object} dist
 * @param {number} groupIndex
 * @param {number} atomIdStart
 */
export function buildPassesForUnit(unit, dist, groupIndex, atomIdStart = 0) {
  const { modelCount = 1, traceCount = 2, blankCount = 2 } = dist;
  const items = unit.items || [];
  /** @type {LayoutCell[][]} */
  const passes = [];
  let atomId = atomIdStart;
  let passIndex = 0;

  const pushPass = (role, withPinyin) => {
    /** @type {LayoutCell[]} */
    const cells = [];
    for (const item of items) {
      cells.push({
        char: role === "blank" ? "" : item.char,
        pinyin: withPinyin && role !== "blank" ? item.pinyin || "" : "",
        role,
        groupIndex,
        atomId: atomId++,
      });
    }
    passes.push(cells);
    passIndex += 1;
  };

  for (let i = 0; i < modelCount; i++) pushPass("model", passIndex === 0);
  for (let i = 0; i < traceCount; i++) pushPass("trace", passIndex === 0);
  for (let i = 0; i < blankCount; i++) pushPass("blank", false);

  return { passes, nextAtomId: atomId, width: items.length };
}

function padCells(cells, n, groupIndex = -1) {
  const out = cells.slice();
  while (out.length < n) {
    out.push({ char: "", pinyin: "", role: "blank", groupIndex, atomId: -1 });
  }
  return out.slice(0, n);
}

function pullLastAtom(prevCells, lineLen) {
  let last = -1;
  for (let i = prevCells.length - 1; i >= 0; i--) {
    const id = prevCells[i].atomId;
    if (id != null && id >= 0 && prevCells[i].char) {
      last = id;
      break;
    }
  }
  if (last < 0) return null;
  const kept = [];
  const pulled = [];
  for (const c of prevCells) {
    if (c.atomId === last) pulled.push({ ...c });
    else kept.push(c);
  }
  if (!pulled.length || !kept.some((c) => c.atomId != null && c.atomId >= 0 && c.char)) {
    return null;
  }
  prevCells.length = 0;
  prevCells.push(...padCells(kept, lineLen));
  return pulled;
}

/**
 * @param {{ cells: LayoutCell[], forbidStart: boolean }[]} blocks
 * @param {number} lineLen
 */
export function packBlocksWithBitou(blocks, lineLen) {
  /** @type {LayoutCell[][]} */
  const lines = [];
  /** @type {LayoutCell[]} */
  let current = [];

  const flush = () => {
    if (!current.length) return;
    lines.push(padCells(current, lineLen));
    current = [];
  };

  for (const block of blocks) {
    const need = block.cells.length;
    if (!need) continue;

    if (current.length > 0 && current.length + need > lineLen) flush();

    if (current.length === 0 && block.forbidStart && lines.length > 0) {
      const prev = lines[lines.length - 1];
      const pulled = pullLastAtom(prev, lineLen);
      if (pulled?.length) {
        if (pulled.length + need > lineLen) lines.push(padCells(pulled, lineLen));
        else current.push(...pulled);
      }
    }

    if (current.length === 0 && need > lineLen) {
      for (const c of block.cells) {
        current.push(c);
        if (current.length >= lineLen) flush();
      }
      continue;
    }

    if (current.length > 0 && current.length + need > lineLen) flush();
    current.push(...block.cells);
    while (current.length >= lineLen) {
      lines.push(current.slice(0, lineLen));
      current = current.slice(lineLen);
    }
  }
  flush();
  return lines;
}

export function evenCellsPerLine(usablePt, stridePt) {
  let n = Math.floor(usablePt / stridePt);
  if (n < 2) n = 2;
  if (n % 2 !== 0) n -= 1;
  return Math.max(2, n);
}

/**
 * @param {LayoutCell[]} cells
 * @param {object} geo
 * @param {'horizontal'|'vertical'} direction
 * @param {number} originX
 * @param {number} originTop
 */
function placeLineCells(cells, geo, direction, originX, originTop) {
  const { cellSizePt, pinyinBandPt, strideMain } = geo;
  /** @type {PlacedCell[]} */
  const placed = [];
  if (direction === "horizontal") {
    for (let i = 0; i < cells.length; i++) {
      const cellY = originTop - pinyinBandPt - cellSizePt;
      placed.push({
        ...cells[i],
        x: originX + i * strideMain,
        y: cellY,
        size: cellSizePt,
        pinyinSide: "top",
      });
    }
  } else {
    for (let i = 0; i < cells.length; i++) {
      const cellY = originTop - (i + 1) * strideMain;
      placed.push({
        ...cells[i],
        x: originX,
        y: cellY,
        size: cellSizePt,
        pinyinSide: "right",
      });
    }
  }
  return placed;
}
/**
 * 连续／断行：主流水线排版
 * @param {import('./input.js').CharGroup[]} units
 * @param {object} opts
 * @param {boolean} atomicGroup 断行：整组节奏格按「一遍宽度」判断换行
 */
function layoutFlowStream(units, opts, atomicGroup) {
  const {
    direction = "horizontal",
    cellSizePt,
    pinyinBandPt,
    cellsPerLine,
    strideMain,
    contentLeftPt,
    contentTopPt,
    contentBottomPt,
    contentRightPt,
    rowGapPt,
    groupGapPt,
    modelCount,
    traceCount,
    blankCount,
  } = opts;

  const dist = { modelCount, traceCount, blankCount };

  /** @type {LayoutPage[]} */
  const pages = [];
  /** @type {PlacedCell[]} */
  let pageCells = [];
  let atomSeq = 0;
  let pageIndex = 0;

  function packBreakAware(blockList, lineLen) {
    if (!atomicGroup) return packBlocksWithBitou(blockList, lineLen);

    /** @type {LayoutCell[][]} */
    const lines = [];
    /** @type {LayoutCell[]} */
    let current = [];
    let currentUsed = 0;

    const flush = () => {
      if (!current.length) return;
      lines.push(padCells(current, lineLen));
      current = [];
      currentUsed = 0;
    };

    for (const block of blockList) {
      const breakW = block._breakWidth || block.cells.length;
      const needAll = block.cells.length;

      if (currentUsed > 0 && currentUsed + breakW > lineLen) flush();

      if (current.length === 0 && block.forbidStart && lines.length > 0) {
        const prev = lines[lines.length - 1];
        const pulled = pullLastAtom(prev, lineLen);
        if (pulled?.length && pulled.length + needAll <= lineLen) {
          current.push(...pulled);
          currentUsed += pulled.length;
        }
      }

      if (needAll > lineLen) {
        if (current.length) flush();
        for (const c of block.cells) {
          current.push(c);
          currentUsed += 1;
          if (currentUsed >= lineLen) flush();
        }
        continue;
      }

      if (currentUsed + needAll > lineLen && currentUsed > 0) flush();
      current.push(...block.cells);
      currentUsed += needAll;
      if (currentUsed >= lineLen) flush();
    }
    flush();
    return lines;
  }

  /** @type {{ lines: LayoutCell[][], gapBefore: number }[]} */
  const chunks = [];
  /** @type {{ cells: LayoutCell[], forbidStart: boolean, _breakWidth?: number }[]} */
  let pendingBlocks = [];
  let pendingGap = 0;

  const flushPending = () => {
    if (!pendingBlocks.length) return;
    chunks.push({
      lines: packBreakAware(pendingBlocks, cellsPerLine),
      gapBefore: pendingGap,
    });
    pendingBlocks = [];
    pendingGap = 0;
  };

  for (let ui = 0; ui < units.length; ui++) {
    const unit = units[ui];
    if (unit.sectionBreakBefore) {
      flushPending();
      pendingGap = groupGapPt;
    }

    const { passes, nextAtomId } = buildPassesForUnit(unit, dist, ui, atomSeq);
    atomSeq = nextAtomId;
    const flat = passes.flat();
    if (atomicGroup) {
      pendingBlocks.push({
        cells: flat,
        forbidStart: isLineStartForbidden(unit.items[0]?.char),
        _breakWidth: unit.items.length,
      });
    } else {
      for (const c of flat) {
        pendingBlocks.push({
          cells: [c],
          forbidStart: c.role !== "blank" && !!c.char && isLineStartForbidden(c.char),
        });
      }
    }
  }
  flushPending();
  let cursorMain = contentTopPt;
  // 竖向：栏从右向左推进（cursorCross 为当前栏右缘）
  let cursorCross = direction === "vertical" ? contentRightPt : contentLeftPt;

  const flushPage = () => {
    if (pageCells.length) {
      pages.push({ cells: pageCells, pageIndex: pageIndex++ });
      pageCells = [];
    }
    cursorMain = contentTopPt;
    cursorCross = direction === "vertical" ? contentRightPt : contentLeftPt;
  };

  for (let ci = 0; ci < chunks.length; ci++) {
    const chunk = chunks[ci];
    if (chunk.gapBefore && pageCells.length) {
      if (direction === "horizontal") cursorMain -= chunk.gapBefore;
      else cursorCross -= chunk.gapBefore;
    }

    for (let li = 0; li < chunk.lines.length; li++) {
      const line = chunk.lines[li];
      if (direction === "horizontal") {
        const rowH = cellSizePt + pinyinBandPt;
        if (cursorMain - rowH < contentBottomPt && pageCells.length) flushPage();
        const placed = placeLineCells(
          line,
          { cellSizePt, pinyinBandPt, strideMain },
          "horizontal",
          contentLeftPt,
          cursorMain,
        );
        pageCells.push(...placed);
        cursorMain -= rowH + rowGapPt;
      } else {
        const colW = cellSizePt + pinyinBandPt;
        if (cursorCross - colW < contentLeftPt && pageCells.length) flushPage();
        const cellX = cursorCross - colW;
        const placed = placeLineCells(
          line,
          { cellSizePt, pinyinBandPt, strideMain },
          "vertical",
          cellX,
          cursorMain,
        );
        pageCells.push(...placed);
        cursorCross = cellX - rowGapPt;
      }
    }
  }
  flushPage();
  return {
    pages,
    writeDirection: direction,
    pinyinBandPt,
    cellSizePt,
    rowGapPt,
    groupGapPt,
  };
}

/**
 * 分组／输入排版：
 * - 组内不换行；节奏沿交叉方向（横写：字横排、遍数下行；竖写：字竖排、遍数自右向左）
 * - 分组：横写组横向并排、竖写组纵向堆叠，并尝试多行／多列断行
 * - 输入排版 oneGroupPerLine：一组一次折行（横写每组独占一行且行左齐，竖写每组独占一列且列顶齐；整块居中）
 */
function layoutGroupedUnits(units, opts) {
  const {
    direction = "horizontal",
    cellSizePt,
    pinyinBandPt,
    strideMain,
    contentLeftPt,
    contentTopPt,
    contentRightPt,
    usableWidthPt,
    usableHeightPt,
    rowGapPt,
    groupGapPt,
    modelCount,
    traceCount,
    blankCount,
    oneGroupPerLine = false,
  } = opts;

  const dist = { modelCount, traceCount, blankCount };
  /** @type {LayoutPage[]} */
  const pages = [];
  let pageIndex = 0;
  let atomSeq = 0;

  /** @type {{ passes: LayoutCell[][], bandW: number, bandH: number }[]} */
  const bands = [];
  for (let ui = 0; ui < units.length; ui++) {
    const { passes, nextAtomId, width } = buildPassesForUnit(
      units[ui],
      dist,
      ui,
      atomSeq,
    );
    atomSeq = nextAtomId;
    if (direction === "horizontal") {
      let bandH = 0;
      for (const pass of passes) {
        bandH += passRowHeight(pass);
      }
      bands.push({
        passes,
        bandW: width * strideMain,
        bandH,
      });
    } else {
      let bandW = 0;
      for (const pass of passes) {
        bandW += passColWidth(pass);
      }
      bands.push({
        passes,
        bandW,
        bandH: width * strideMain,
      });
    }
  }

  /** 横写：仅有拼音的遍保留拼音带；遍与遍之间不插行距 */
  function passRowHeight(pass) {
    const needPy = pinyinBandPt > 0 && pass.some((c) => c.pinyin);
    return cellSizePt + (needPy ? pinyinBandPt : 0);
  }

  /** 竖写：仅有拼音的遍保留右侧拼音带；遍与遍之间不插列距 */
  function passColWidth(pass) {
    const needPy = pinyinBandPt > 0 && pass.some((c) => c.pinyin);
    return cellSizePt + (needPy ? pinyinBandPt : 0);
  }

  /**
   * @param {{ passes: LayoutCell[][], bandW: number, bandH: number }[]} pageBands
   * @param {{ x: number, y: number, w: number, h: number }[]} slots
   */
  function placeBandsOnPage(pageBands, slots) {
    /** @type {PlacedCell[]} */
    const pageCells = [];
    const geo = { cellSizePt, pinyinBandPt, strideMain };

    for (let i = 0; i < pageBands.length; i++) {
      const band = pageBands[i];
      const slot = slots[i];
      if (direction === "horizontal") {
        // 行内底对齐：无拼音组下移，与有拼音组的字格对齐（多出的高度是拼音带）
        let passTop = slot.y - Math.max(0, (slot.h || band.bandH) - band.bandH);
        for (let pi = 0; pi < band.passes.length; pi++) {
          const pass = band.passes[pi];
          const needPy = pinyinBandPt > 0 && pass.some((c) => c.pinyin);
          const bandPt = needPy ? pinyinBandPt : 0;
          pageCells.push(
            ...placeLineCells(
              pass,
              { cellSizePt, pinyinBandPt: bandPt, strideMain },
              "horizontal",
              slot.x,
              passTop,
            ),
          );
          passTop -= cellSizePt + bandPt;
        }
      } else {
        let edgeRight = slot.x + band.bandW;
        for (let pi = 0; pi < band.passes.length; pi++) {
          const pass = band.passes[pi];
          const needPy = pinyinBandPt > 0 && pass.some((c) => c.pinyin);
          const bandPt = needPy ? pinyinBandPt : 0;
          const colW = cellSizePt + bandPt;
          const passX = edgeRight - colW;
          pageCells.push(
            ...placeLineCells(
              pass,
              { cellSizePt, pinyinBandPt: bandPt, strideMain },
              "vertical",
              passX,
              slot.y,
            ),
          );
          edgeRight = passX;
        }
      }
    }
    if (pageCells.length) pages.push({ cells: pageCells, pageIndex: pageIndex++ });
  }
  /**
   * 将 items 均分成 k 段（顺序不断裂）。
   * @template T
   * @param {T[]} items
   * @param {number} k
   * @returns {T[][]}
   */
  function splitIntoK(items, k) {
    const n = items.length;
    const lines = Math.max(1, Math.min(k, n));
    const base = Math.floor(n / lines);
    const rem = n % lines;
    /** @type {T[][]} */
    const out = [];
    let idx = 0;
    for (let r = 0; r < lines; r++) {
      const take = base + (r < rem ? 1 : 0);
      if (take > 0) out.push(items.slice(idx, idx + take));
      idx += take;
    }
    return out;
  }

  /**
   * 横写：k 行，行内组横向并排；行宽不足时该方案无效。
   * @param {typeof bands} slice
   * @param {number} k
   */
  function tryHorizontalRows(slice, k) {
    const rows = splitIntoK(slice, k);
    /** @type {{ x: number, y: number, w: number, h: number, _rowW?: number }[]} */
    const rawSlots = [];
    /** @type {typeof bands} */
    const ordered = [];
    let blockW = 0;
    let blockH = 0;
    let y = 0;
    for (let ri = 0; ri < rows.length; ri++) {
      const row = rows[ri];
      let rowW = 0;
      let rowH = 0;
      for (let j = 0; j < row.length; j++) {
        if (j) rowW += groupGapPt;
        rowW += row[j].bandW;
        rowH = Math.max(rowH, row[j].bandH);
      }
      if (rowW > usableWidthPt) return null;
      blockW = Math.max(blockW, rowW);
      if (ri) {
        y += groupGapPt;
        blockH += groupGapPt;
      }
      let xCursor = 0;
      const rowStartIndex = rawSlots.length;
      for (const b of row) {
        // 槽高取整行：矮组（无拼音）底对齐，与有拼音组的字格齐平
        rawSlots.push({ x: xCursor, y, w: b.bandW, h: rowH, _rowW: rowW });
        ordered.push(b);
        xCursor += b.bandW + groupGapPt;
      }
      for (let s = rowStartIndex; s < rawSlots.length; s++) {
        rawSlots[s]._rowW = rowW;
      }
      y += rowH;
      blockH += rowH;
    }
    if (blockH > usableHeightPt) return null;
    for (const s of rawSlots) {
      const inset = Math.max(0, (blockW - (s._rowW || s.w)) / 2);
      s.x += inset;
      delete s._rowW;
    }
    return { blockW, blockH, rawSlots, ordered };
  }

  /**
   * 竖写：k 列，列内组纵向堆叠；列自右向左。
   * @param {typeof bands} slice
   * @param {number} k
   */
  function tryVerticalCols(slice, k) {
    const cols = splitIntoK(slice, k);
    const colMetrics = cols.map((col) => {
      let colH = 0;
      let colW = 0;
      for (let j = 0; j < col.length; j++) {
        if (j) colH += groupGapPt;
        colH += col[j].bandH;
        colW = Math.max(colW, col[j].bandW);
      }
      return { col, colW, colH };
    });
    for (const m of colMetrics) {
      if (m.colH > usableHeightPt) return null;
    }
    const maxColH = Math.max(...colMetrics.map((m) => m.colH));
    /** @type {{ x: number, y: number, w: number, h: number }[]} */
    const rawSlots = [];
    /** @type {typeof bands} */
    const ordered = [];
    let blockW = 0;
    let blockH = 0;
    let xFromRight = 0;
    for (let ci = 0; ci < colMetrics.length; ci++) {
      const { col, colW, colH } = colMetrics[ci];
      if (ci) xFromRight += groupGapPt;
      const colY0 = Math.max(0, (maxColH - colH) / 2);
      let yCursor = colY0;
      for (const b of col) {
        rawSlots.push({
          x: xFromRight + (colW - b.bandW),
          y: yCursor,
          w: b.bandW,
          h: b.bandH,
        });
        ordered.push(b);
        yCursor += b.bandH + groupGapPt;
      }
      xFromRight += colW;
      blockW = xFromRight;
      blockH = Math.max(blockH, colY0 + colH);
    }
    if (blockW > usableWidthPt) return null;
    return { blockW, blockH, rawSlots, ordered };
  }

  /**
   * 在 1..n 行／列方案中择优：须进版心；组数尽量均分；块比例接近版心；同质时偏少行／列。
   * @param {typeof bands} slice
   */
  function pickBestPack(slice) {
    if (!slice.length) return null;
    const n = slice.length;
    /** @type {{ blockW: number, blockH: number, rawSlots: any[], ordered: typeof bands, k: number, score: number } | null} */
    let best = null;
    for (let k = 1; k <= n; k++) {
      const pack =
        direction === "horizontal"
          ? tryHorizontalRows(slice, k)
          : tryVerticalCols(slice, k);
      if (!pack) continue;
      const parts = splitIntoK(slice, k);
      const partLens = parts.map((p) => p.length);
      const uneven = Math.max(...partLens) - Math.min(...partLens);
      const aspectPage = usableWidthPt / Math.max(1, usableHeightPt);
      const aspectBlock = pack.blockW / Math.max(1, pack.blockH);
      const aspectPenalty = Math.abs(Math.log(aspectBlock / Math.max(1e-6, aspectPage)));
      // 不均分惩罚最大；其次比例；再次偏少断行（先尝试少行／少列）
      const score = uneven * 1000 + aspectPenalty * 100 + k;
      if (!best || score < best.score) {
        best = { ...pack, k, score };
      }
    }
    return best;
  }
  /**
   * 输入排版：一组一次折行——横写每组独占一行向下排；竖写每组独占一列自右向左排。
   * 块内：横写各行左齐、竖写各列顶齐（与「一行／一列」对应）；整块再在版心居中。
   * @param {typeof bands} rest
   */
  function takeNextPageOnePerLine(rest) {
    /** @type {typeof bands} */
    const pageBands = [];
    /** @type {{ x: number, y: number, w: number, h: number }[]} */
    const rawSlots = [];
    let blockW = 0;
    let blockH = 0;
    let used = 0;

    if (direction === "horizontal") {
      let y = 0;
      for (let i = 0; i < rest.length; i++) {
        const b = rest[i];
        const gap = pageBands.length ? groupGapPt : 0;
        const nextH = y + gap + b.bandH;
        if (pageBands.length && nextH > usableHeightPt) break;
        // 单行过宽不在此拒排：与竖写单列过高一样，超版心由用户处理
        y += gap;
        pageBands.push(b);
        // 左齐：短行与最长行共用左缘
        rawSlots.push({ x: 0, y, w: b.bandW, h: b.bandH });
        blockW = Math.max(blockW, b.bandW);
        y += b.bandH;
        blockH = y;
        used += 1;
      }
    } else {
      let xFromRight = 0;
      for (let i = 0; i < rest.length; i++) {
        const b = rest[i];
        const nextW = pageBands.length ? blockW + groupGapPt + b.bandW : b.bandW;
        if (pageBands.length && nextW > usableWidthPt) break;
        if (pageBands.length) xFromRight += groupGapPt;
        pageBands.push(b);
        // 顶齐：短列与最长列共用上缘（对偶于横写左齐）
        rawSlots.push({
          x: xFromRight,
          y: 0,
          w: b.bandW,
          h: b.bandH,
        });
        xFromRight += b.bandW;
        blockW = xFromRight;
        blockH = Math.max(blockH, b.bandH);
        used += 1;
      }
    }

    if (!used) {
      const one = rest[0];
      return {
        pack: {
          blockW: one.bandW,
          blockH: one.bandH,
          rawSlots: [{ x: 0, y: 0, w: one.bandW, h: one.bandH }],
          ordered: [one],
          k: 1,
          score: 0,
        },
        used: 1,
      };
    }

    return {
      pack: {
        blockW,
        blockH,
        rawSlots,
        ordered: pageBands,
        k: pageBands.length,
        score: 0,
      },
      used,
    };
  }

  /**
   * 尽量多收组到一页：从大前缀往小试，找到能 pack 的最长前缀。
   * @param {typeof bands} rest
   */
  function takeNextPage(rest) {
    if (oneGroupPerLine) return takeNextPageOnePerLine(rest);
    for (let end = rest.length; end >= 1; end--) {
      const pack = pickBestPack(rest.slice(0, end));
      if (pack) return { pack, used: end };
    }
    // 单组过大也硬放
    const one = rest[0];
    return {
      pack: {
        blockW: one.bandW,
        blockH: one.bandH,
        rawSlots: [{ x: 0, y: 0, w: one.bandW, h: one.bandH }],
        ordered: [one],
        k: 1,
        score: 0,
      },
      used: 1,
    };
  }

  let offset = 0;
  while (offset < bands.length) {
    const { pack, used } = takeNextPage(bands.slice(offset));
    offset += used;
    if (direction === "horizontal") {
      const ox = contentLeftPt + Math.max(0, (usableWidthPt - pack.blockW) / 2);
      const oy = contentTopPt - Math.max(0, (usableHeightPt - pack.blockH) / 2);
      const slots = pack.rawSlots.map((s) => ({
        x: ox + s.x,
        y: oy - s.y,
        w: s.w,
        h: s.h,
      }));
      placeBandsOnPage(pack.ordered, slots);
    } else {
      const oxRight = contentRightPt - Math.max(0, (usableWidthPt - pack.blockW) / 2);
      const oy = contentTopPt - Math.max(0, (usableHeightPt - pack.blockH) / 2);
      const slots = pack.rawSlots.map((s) => ({
        x: oxRight - s.x - s.w,
        y: oy - s.y,
        w: s.w,
        h: s.h,
      }));
      placeBandsOnPage(pack.ordered, slots);
    }
  }

  return {
    pages,
    writeDirection: direction,
    pinyinBandPt,
    cellSizePt,
    rowGapPt,
    groupGapPt,
  };
}

/**
 * @param {import('./input.js').CharGroup[]} groups
 * @param {object} opts
 */
export function buildLayout(groups, opts) {
  const flow = normalizeFlow(opts.layoutMode || opts.flow || "group");
  const direction = opts.writeDirection || opts.direction || "horizontal";
  const cellSizePt = opts.cellSizePt;
  const showPinyin = opts.showPinyin !== false;
  const pinyinBandPt = showPinyin
    ? PINYIN_GAP_FROM_CELL_PT + PINYIN_FONT_SIZE_PT * 1.25
    : 0;
  const rowGapPt = mmToPt(opts.rowGapMm ?? 0);
  const groupGapPt = mmToPt(opts.groupGapMm ?? 2);

  const marginLeftPt = opts.marginLeftPt ?? opts.marginTopPt ?? 0;
  const marginRightPt = opts.marginRightPt ?? marginLeftPt;
  const marginTopPt = opts.marginTopPt ?? 0;
  const marginBottomPt = opts.marginBottomPt ?? 0;
  const pageHeightPt = opts.pageHeightPt;
  const pageWidthPt = opts.pageWidthPt ?? pageHeightPt * (210 / 297);
  const footerHeightPt = opts.footerHeightPt ?? 0;
  const hardEdgePt = opts.hardEdgePt ?? mmToPt(2);
  const overflowMm = Math.max(0, Math.min(30, Number(opts.overflowMm ?? 5) || 0));
  const expandPt = mmToPt(overflowMm);

  const typeLeftPt = marginLeftPt;
  const typeRightPt = pageWidthPt - marginRightPt;
  const typeTopPt = pageHeightPt - marginTopPt;
  const typeBottomPt = marginBottomPt + footerHeightPt;

  /**
   * @param {number} expand
   */
  function makeContentBox(expand) {
    const contentLeftPt = Math.max(hardEdgePt, typeLeftPt - expand);
    const contentRightPt = Math.min(pageWidthPt - hardEdgePt, typeRightPt + expand);
    const contentTopPt = Math.min(pageHeightPt - hardEdgePt, typeTopPt + expand);
    const contentBottomPt = Math.max(hardEdgePt, typeBottomPt - expand);
    return {
      contentLeftPt,
      contentRightPt,
      contentTopPt,
      contentBottomPt,
      usableWidthPt: Math.max(1, contentRightPt - contentLeftPt),
      usableHeightPt: Math.max(1, contentTopPt - contentBottomPt),
    };
  }

  const strictBox = makeContentBox(0);
  const overflowBox = overflowMm > 0 ? makeContentBox(expandPt) : null;

  const strideMain = cellSizePt;
  const strideCross = cellSizePt + pinyinBandPt;
  const units = prepareUnits(groups, flow);
  const distOpts = {
    modelCount: opts.modelCount ?? 1,
    traceCount: opts.traceCount ?? 2,
    blankCount: opts.blankCount ?? 2,
  };

  /**
   * @param {ReturnType<typeof makeContentBox>} box
   */
  function layoutInBox(box) {
    const cellsPerLine =
      direction === "horizontal"
        ? evenCellsPerLine(box.usableWidthPt, strideMain)
        : evenCellsPerLine(box.usableHeightPt, strideMain);
    const common = {
      direction,
      cellSizePt,
      pinyinBandPt,
      cellsPerLine,
      strideMain,
      strideCross,
      ...box,
      rowGapPt,
      groupGapPt,
      ...distOpts,
      oneGroupPerLine: flow === "group-line",
    };
    const raw =
      flow === "group" || flow === "group-line"
        ? layoutGroupedUnits(units, common)
        : layoutFlowStream(units, common, flow === "break");
    return { ...raw, flow, cellsPerLine };
  }

  const strictLayout = layoutInBox(strictBox);
  let chosen = strictLayout;
  let usedBox = strictBox;
  let usedOverflow = false;

  if (overflowBox) {
    const looseLayout = layoutInBox(overflowBox);
    if (isOverflowWorthIt(strictLayout, looseLayout, direction, cellSizePt, expandPt)) {
      chosen = looseLayout;
      usedBox = overflowBox;
      usedOverflow = true;
    }
  }

  centerPagesHorizontally(chosen.pages, usedBox, pinyinBandPt);

  return {
    ...chosen,
    usedOverflow,
    overflowMm: usedOverflow ? overflowMm : 0,
  };
}

/**
 * 比较严格版心与超版心方案：页数更少、每行／列格数更多，
 * 或实际内容主向跨度／面积增益达到约半格（且不少于允许超出版心的一半）则采用超版心。
 * @param {object} strict
 * @param {object} loose
 * @param {'horizontal'|'vertical'} direction
 * @param {number} cellSizePt
 * @param {number} expandPt
 */
function isOverflowWorthIt(strict, loose, direction, cellSizePt, expandPt) {
  if ((loose.pages?.length || 0) < (strict.pages?.length || 0)) return true;
  if ((loose.cellsPerLine || 0) > (strict.cellsPerLine || 0)) return true;

  const a = measureLayoutContent(strict, direction);
  const b = measureLayoutContent(loose, direction);
  const spanGain = b.mainSpan - a.mainSpan;
  const areaGain = b.area - a.area;
  const spanThreshold = Math.max(cellSizePt * 0.5, expandPt * 0.5);
  if (spanGain >= spanThreshold - 0.01) return true;
  if (areaGain >= cellSizePt * cellSizePt * 0.5) return true;
  return false;
}

/**
 * @param {object} layout
 * @param {'horizontal'|'vertical'} direction
 */
function measureLayoutContent(layout, direction) {
  const pinyinBandPt = layout.pinyinBandPt || 0;
  let area = 0;
  let mainSpan = 0;
  for (const page of layout.pages || []) {
    const cells = page.cells || [];
    if (!cells.length) continue;
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const c of cells) {
      const size = c.size || layout.cellSizePt || 0;
      const x1 = c.x;
      const x2 =
        c.x + size + (c.pinyinSide === "right" ? pinyinBandPt : 0);
      const y1 = c.y;
      const y2 = c.y + size + (c.pinyinSide === "top" ? pinyinBandPt : 0);
      minX = Math.min(minX, x1);
      maxX = Math.max(maxX, x2);
      minY = Math.min(minY, y1);
      maxY = Math.max(maxY, y2);
    }
    const w = Math.max(0, maxX - minX);
    const h = Math.max(0, maxY - minY);
    area += w * h;
    mainSpan = Math.max(mainSpan, direction === "horizontal" ? w : h);
  }
  return { area, mainSpan };
}

/**
 * 将每页实际内容块左右居中到当前内容框（版心或已采用的超版心框）中央。
 * @param {LayoutPage[]} pages
 * @param {{ contentLeftPt: number, contentRightPt: number }} box
 * @param {number} pinyinBandPt
 */
function centerPagesHorizontally(pages, box, pinyinBandPt) {
  const mid = (box.contentLeftPt + box.contentRightPt) / 2;
  for (const page of pages || []) {
    const cells = page.cells || [];
    if (!cells.length) continue;
    let minX = Infinity;
    let maxX = -Infinity;
    for (const c of cells) {
      const size = c.size || 0;
      minX = Math.min(minX, c.x);
      maxX = Math.max(
        maxX,
        c.x + size + (c.pinyinSide === "right" ? pinyinBandPt : 0),
      );
    }
    const dx = mid - (minX + maxX) / 2;
    if (Math.abs(dx) < 0.05) continue;
    for (const c of cells) c.x += dx;
  }
}

/** @deprecated 兼容旧调用 */
export function buildCellsForChar(item, dist, groupIndex, atomId = 0) {
  const { passes, nextAtomId } = buildPassesForUnit(
    { items: [item] },
    dist,
    groupIndex,
    atomId,
  );
  return { cells: passes.flat(), nextAtomId };
}

/** @deprecated */
export function buildCellsForGroup(group, dist, groupIndex, atomIdStart = 0) {
  const { passes, nextAtomId } = buildPassesForUnit(group, dist, groupIndex, atomIdStart);
  return { cells: passes.flat(), nextAtomId };
}
