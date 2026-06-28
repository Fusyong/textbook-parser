/** @typedef {'model'|'trace'|'blank'} CellRole */
/** @typedef {{ char: string, pinyin: string, role: CellRole, groupIndex: number }} LayoutCell */
/** @typedef {{ cells: LayoutCell[], yOffsetPt: number, isGroupStart?: boolean, groupGapMm?: number }} LayoutRow */
/** @typedef {{ rows: LayoutRow[], pageIndex: number }} LayoutPage */

export const CM_TO_PT = 72 / 2.54;
export const MM_TO_PT = 72 / 25.4;

export function cmToPt(cm) {
  return cm * CM_TO_PT;
}

export function mmToPt(mm) {
  return mm * MM_TO_PT;
}

/** @param {import('./input.js').CharItem} item @param {object} dist @param {number} groupIndex */
export function buildCellsForChar(item, dist, groupIndex) {
  const { modelCount = 1, traceCount = 2, blankCount = 2 } = dist;
  /** @type {LayoutCell[]} */
  const cells = [];
  for (let i = 0; i < modelCount; i++) {
    cells.push({ char: item.char, pinyin: item.pinyin, role: "model", groupIndex });
  }
  for (let i = 0; i < traceCount; i++) {
    cells.push({ char: item.char, pinyin: item.pinyin, role: "trace", groupIndex });
  }
  for (let i = 0; i < blankCount; i++) {
    cells.push({ char: "", pinyin: "", role: "blank", groupIndex });
  }
  return cells;
}

/**
 * @param {import('./input.js').CharGroup[]} groups
 * @param {object} opts
 */
export function layoutContinuous(groups, opts) {
  const {
    cellsPerRow,
    modelCount = 1,
    traceCount = 2,
    blankCount = 2,
    groupGapMm = 8,
  } = opts;

  /** @type {LayoutRow[]} */
  const rows = [];
  let currentRow = /** @type {LayoutCell[]} */ ([]);

  const flushRow = () => {
    if (!currentRow.length) return;
    while (currentRow.length % cellsPerRow !== 0) {
      currentRow.push({ char: "", pinyin: "", role: "blank", groupIndex: -1 });
    }
    rows.push({ cells: currentRow, yOffsetPt: 0 });
    currentRow = [];
  };

  for (let gi = 0; gi < groups.length; gi++) {
    if (gi > 0 && rows.length) {
      rows.push({ cells: [], yOffsetPt: 0, isGroupStart: true, groupGapMm });
    }
    const g = groups[gi];
    for (const item of g.items) {
      const cells = buildCellsForChar(item, { modelCount, traceCount, blankCount }, gi);
      for (const c of cells) {
        currentRow.push(c);
        if (currentRow.length >= cellsPerRow) flushRow();
      }
    }
  }
  flushRow();

  return paginateRows(rows, opts);
}

/**
 * @param {import('./input.js').CharGroup[]} groups
 * @param {object} opts
 */
export function layoutGrouped(groups, opts) {
  const {
    cellsPerRow,
    modelCount = 1,
    traceCount = 2,
    blankCount = 2,
    groupGapMm = 10,
  } = opts;

  /** @type {LayoutRow[]} */
  const rows = [];

  for (let gi = 0; gi < groups.length; gi++) {
    if (gi > 0) {
      rows.push({ cells: [], yOffsetPt: 0, isGroupStart: true, groupGapMm });
    }
    const items = groups[gi].items;
    if (!items.length) continue;

    /** @param {CellRole} role */
    const makeRowCells = (role) =>
      items.map((it) => ({
        char: role === "blank" ? "" : it.char,
        pinyin: role === "blank" ? "" : it.pinyin,
        role,
        groupIndex: gi,
      }));

    const pushSplitRows = (cells) => {
      for (let i = 0; i < cells.length; i += cellsPerRow) {
        const slice = cells.slice(i, i + cellsPerRow);
        while (slice.length < cellsPerRow) {
          slice.push({ char: "", pinyin: "", role: "blank", groupIndex: gi });
        }
        rows.push({ cells: slice, yOffsetPt: 0 });
      }
    };

    if (modelCount > 0) pushSplitRows(makeRowCells("model"));
    for (let t = 0; t < traceCount; t++) pushSplitRows(makeRowCells("trace"));
    for (let b = 0; b < blankCount; b++) pushSplitRows(makeRowCells("blank"));
  }

  return paginateRows(rows, opts);
}

/** @param {LayoutRow[]} rows @param {object} pageSpec */
function paginateRows(rows, pageSpec) {
  const {
    pageHeightPt,
    marginTopPt,
    marginBottomPt,
    footerHeightPt,
    cellSizePt,
    showPinyin,
    rowGapMm = 4,
    groupGapMm = 8,
  } = pageSpec;

  const pinyinBandPt = showPinyin ? cellSizePt * 0.32 : 0;
  const rowHeightPt = cellSizePt + pinyinBandPt;
  const rowGapPt = mmToPt(rowGapMm);
  const groupGapPt = mmToPt(groupGapMm);

  const contentTop = pageHeightPt - marginTopPt;
  const contentBottom = marginBottomPt + footerHeightPt;

  /** @type {LayoutPage[]} */
  const pages = [];
  /** @type {LayoutRow[]} */
  let pageRows = [];
  let usedHeight = 0;

  const startNewPage = () => {
    if (pageRows.length) pages.push({ rows: pageRows, pageIndex: pages.length });
    pageRows = [];
    usedHeight = 0;
  };

  startNewPage();

  for (const row of rows) {
    const gapOnly = row.isGroupStart && (!row.cells || row.cells.length === 0);
    const extraGap = row.isGroupStart ? mmToPt(row.groupGapMm ?? groupGapMm) : 0;
    const rowBlock = gapOnly ? extraGap : rowHeightPt + extraGap;

    const need = rowBlock + (usedHeight > 0 ? rowGapPt : 0);
    if (usedHeight + need > contentTop - contentBottom && pageRows.length > 0) {
      startNewPage();
    }

    if (usedHeight > 0 && !gapOnly) usedHeight += rowGapPt;
    if (row.isGroupStart) usedHeight += extraGap;
    if (!gapOnly) usedHeight += rowHeightPt;

    if (!gapOnly) pageRows.push({ ...row, yOffsetPt: usedHeight });
  }

  if (pageRows.length) pages.push({ rows: pageRows, pageIndex: pages.length });

  return {
    pages,
    rowHeightPt,
    pinyinBandPt,
    rowGapPt,
    groupGapPt,
    contentTop,
    contentBottom,
  };
}

/**
 * @param {number} usableWidthPt
 * @param {number} cellSizePt
 */
export function evenCellsPerRow(usableWidthPt, cellSizePt) {
  let n = Math.floor(usableWidthPt / cellSizePt);
  if (n < 2) n = 2;
  if (n % 2 !== 0) n -= 1;
  return Math.max(2, n);
}

/**
 * @param {import('./input.js').CharGroup[]} groups
 * @param {object} opts
 */
export function buildLayout(groups, opts) {
  const cellsPerRow = evenCellsPerRow(opts.usableWidthPt, opts.cellSizePt);
  const layoutOpts = { ...opts, cellsPerRow };
  if (opts.layoutMode === "grouped") return { ...layoutGrouped(groups, layoutOpts), cellsPerRow };
  return { ...layoutContinuous(groups, layoutOpts), cellsPerRow };
}
