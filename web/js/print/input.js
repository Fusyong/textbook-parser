/** @typedef {{ char: string, pinyin: string }} CharItem */
/** @typedef {{ items: CharItem[] }} CharGroup */

const HAN_RE = /\p{Script=Han}/u;

/** 行内连续空白 → 一空格；单换行 → 空格；双换行及以上 → 段落分隔 */
export function normalizePrintText(raw) {
  const t = String(raw ?? "");
  const parts = t.split(/\n{2,}/);
  return parts
    .map((part) =>
      part
        .replace(/\r\n/g, "\n")
        .replace(/\n/g, " ")
        .replace(/[ \t\u00a0]+/g, " ")
        .trim(),
    )
    .filter(Boolean);
}

/** @param {string} token */
function charsFromToken(token) {
  const out = [];
  for (const ch of token) {
    if (HAN_RE.test(ch)) out.push(ch);
  }
  return out;
}

/**
 * @param {string} hanziRaw
 * @param {string} [pinyinRaw]
 * @returns {CharGroup[]}
 */
export function parseManualInput(hanziRaw, pinyinRaw) {
  const hanziParts = normalizePrintText(hanziRaw);
  const pinyinParts = pinyinRaw?.trim() ? normalizePrintText(pinyinRaw) : [];

  /** @type {CharGroup[]} */
  const groups = [];

  for (let gi = 0; gi < hanziParts.length; gi++) {
    const hPart = hanziParts[gi];
    const pPart = pinyinParts[gi] ?? "";
    const hTokens = hPart.split(" ").filter(Boolean);
    const pTokens = pPart ? pPart.split(" ").filter(Boolean) : [];

    /** @type {CharItem[]} */
    const items = [];
    for (let ti = 0; ti < hTokens.length; ti++) {
      const py = pTokens[ti] ?? pTokens[pTokens.length - 1] ?? "";
      for (const ch of charsFromToken(hTokens[ti])) {
        items.push({ char: ch, pinyin: py });
      }
    }
    if (items.length) groups.push({ items });
  }

  if (!groups.length && hanziRaw?.trim()) {
    const flat = [...hanziRaw].filter((c) => HAN_RE.test(c));
    if (flat.length) groups.push({ items: flat.map((c) => ({ char: c, pinyin: "" })) });
  }

  return groups;
}

/**
 * @param {object} data TEXTBOOK_WEB_DATA
 * @param {string} book
 * @param {string} tocId
 * @param {string} kind 识字表|写字表|词语表
 * @returns {CharItem[]}
 */
export function loadLessonCharItems(data, book, tocId, kind) {
  if (!book || !tocId) return [];

  if (kind === "词语表") {
    const rows = data.wordByBook?.[book]?.["词语表"] || [];
    const row = rows.find((r) => r?.tocId === tocId);
    if (!row) return [];
    const wordItems =
      row.wordItems?.length > 0
        ? row.wordItems
        : (row.words || []).map((w) => ({ word: w, pinyin: "" }));
    /** @type {CharItem[]} */
    const items = [];
    for (const it of wordItems) {
      const py = (it.pinyin && String(it.pinyin).trim()) || "";
      const word = String(it.word || "");
      for (const ch of word) {
        if (HAN_RE.test(ch)) items.push({ char: ch, pinyin: py });
      }
    }
    return items;
  }

  const rows = data.charByBook?.[book]?.[kind] || [];
  const row = rows.find((r) => r?.tocId === tocId);
  if (!row) return [];

  const charItems =
    row.charItems?.length > 0
      ? row.charItems
      : (row.chars || []).map((c) => ({ char: c, pinyin: "" }));

  return charItems
    .map((it) => ({
      char: String(it.char || ""),
      pinyin: (it.pinyin && String(it.pinyin).trim()) || "",
    }))
    .filter((it) => it.char && HAN_RE.test(it.char));
}

/**
 * @param {CharItem[]} items
 * @returns {CharGroup[]}
 */
export function itemsToSingleGroup(items) {
  if (!items.length) return [];
  return [{ items }];
}

/**
 * @param {CharGroup[]} groups
 * @returns {{ charCount: number, cellCount: number }}
 */
export function estimateStats(groups, distribution) {
  const { modelCount = 1, traceCount = 2, blankCount = 2 } = distribution;
  const perChar = modelCount + traceCount + blankCount;
  let charCount = 0;
  for (const g of groups) charCount += g.items.length;
  return { charCount, cellCount: charCount * perChar };
}
