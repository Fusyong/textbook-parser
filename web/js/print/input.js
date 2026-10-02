/** @typedef {{ char: string, pinyin: string }} CharItem */
/** @typedef {{ items: CharItem[], sectionBreakBefore?: boolean, inputLineBreakBefore?: boolean }} CharGroup */

const HAN_RE = /\p{Script=Han}/u;
const PUNCT_RE = /\p{P}|\p{S}/u;

/** @deprecated 旧双栏用；新输入请用 parsePrintInput（保留单换行为输入行） */
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

function isHan(ch) {
  return HAN_RE.test(ch);
}

function isPunct(ch) {
  return PUNCT_RE.test(ch);
}

/**
 * 将正文展开为占格单元：汉字／标点各一格；相邻两个标点合并占一格。
 * @param {string} text
 * @returns {CharItem[]}
 */
export function expandTextToCells(text) {
  const chars = [...String(text ?? "")].filter((c) => c && !/[ \t\u00a0\r\n]/.test(c));
  /** @type {CharItem[]} */
  const items = [];
  let i = 0;
  while (i < chars.length) {
    const c = chars[i];
    if (isPunct(c) && i + 1 < chars.length && isPunct(chars[i + 1])) {
      items.push({ char: c + chars[i + 1], pinyin: "" });
      i += 2;
      continue;
    }
    // 汉字、标点、以及其他可见字符均占格
    items.push({ char: c, pinyin: "" });
    i += 1;
  }
  return items;
}

/**
 * 将括号内拼音音节就近标注到字格：音节数=字数则一一对应；少则从末尾对齐。
 * @param {CharItem[]} cells
 * @param {string} pyRaw
 */
function applyPinyinToCells(cells, pyRaw) {
  if (!cells.length) return;
  const syllables = String(pyRaw || "")
    .trim()
    .split(/[ \t\u00a0]+/)
    .filter(Boolean);
  if (!syllables.length) return;

  if (syllables.length >= cells.length) {
    // 单字多音节：整段注音保留在该字上（如 冬（qiu dong））
    if (cells.length === 1 && syllables.length > 1) {
      cells[0].pinyin = syllables.join(" ");
      return;
    }
    for (let i = 0; i < cells.length; i++) {
      cells[i].pinyin = syllables[i];
    }
    return;
  }
  // 就近：从靠近括号的一侧（末尾）对齐
  const offset = cells.length - syllables.length;
  for (let i = 0; i < syllables.length; i++) {
    cells[offset + i].pinyin = syllables[i];
  }
}

/**
 * 解析单个字词组（空格分隔的一段）。
 * 例：我（wǒ） / 我们（wǒ men） / 我们（men） / 我（wǒ）们（men）
 * 括号内含汉字时，括号与内容均作正文占格。
 * @param {string} token
 * @returns {CharItem[]}
 */
export function parseToken(token) {
  const s = String(token ?? "");
  if (!s) return [];

  /** @type {{ kind: 'text' | 'py', value: string }[]} */
  const pieces = [];
  let i = 0;
  while (i < s.length) {
    const ch = s[i];
    if (ch === "（" || ch === "(") {
      const close = ch === "（" ? "）" : ")";
      const end = s.indexOf(close, i + 1);
      if (end < 0) {
        // 无闭合：开括号当正文
        pieces.push({ kind: "text", value: ch });
        i += 1;
        continue;
      }
      const inner = s.slice(i + 1, end);
      if (HAN_RE.test(inner)) {
        pieces.push({ kind: "text", value: ch + inner + close });
      } else {
        pieces.push({ kind: "py", value: inner.trim() });
      }
      i = end + 1;
      continue;
    }
    let j = i + 1;
    while (j < s.length && s[j] !== "（" && s[j] !== "(") j += 1;
    pieces.push({ kind: "text", value: s.slice(i, j) });
    i = j;
  }

  /** @type {CharItem[]} */
  const items = [];
  for (let p = 0; p < pieces.length; p++) {
    const piece = pieces[p];
    if (piece.kind === "py") {
      // 孤立注音（前无正文）忽略
      continue;
    }
    const cells = expandTextToCells(piece.value);
    const next = pieces[p + 1];
    if (next?.kind === "py") {
      applyPinyinToCells(cells, next.value);
      p += 1;
    }
    items.push(...cells);
  }
  return items;
}

/**
 * 按空格分词，但括号内空格不拆开（支持 （wǒ men） / (wo men)）。
 * @param {string} part
 * @returns {string[]}
 */
export function splitTokensRespectingParens(part) {
  const s = String(part ?? "");
  /** @type {string[]} */
  const tokens = [];
  let buf = "";
  let depth = 0;
  for (const ch of s) {
    if (ch === "（" || ch === "(") {
      depth += 1;
      buf += ch;
      continue;
    }
    if (ch === "）" || ch === ")") {
      depth = Math.max(0, depth - 1);
      buf += ch;
      continue;
    }
    if (depth === 0 && /[ \t\u00a0]/.test(ch)) {
      if (buf) tokens.push(buf);
      buf = "";
      continue;
    }
    buf += ch;
  }
  if (buf) tokens.push(buf);
  return tokens;
}

/** 输入排版模式下占格的空白符（含可见替代符 □；兼容旧版 ␣） */
const SPACE_CELL_RE = /[ \t\u00a0\u3000□␣]/u;

/**
 * 行内解析：每个空格／制表符／不换行空格／全角空格／可见空格符「□」各占一格；
 * 括号内空格仍属注音不占格。
 * @param {string} line
 * @returns {CharItem[]}
 */
export function parseLineKeepingSpacesAsCells(line) {
  const s = String(line ?? "");
  /** @type {CharItem[]} */
  const items = [];
  let i = 0;
  while (i < s.length) {
    const ch = s[i];
    if (SPACE_CELL_RE.test(ch)) {
      items.push({ char: "", pinyin: "" });
      i += 1;
      continue;
    }
    let depth = 0;
    let j = i;
    while (j < s.length) {
      const c = s[j];
      if (c === "（" || c === "(") depth += 1;
      else if (c === "）" || c === ")") depth = Math.max(0, depth - 1);
      else if (depth === 0 && SPACE_CELL_RE.test(c)) break;
      j += 1;
    }
    const tok = s.slice(i, j);
    const cells = parseToken(tok);
    if (cells.length) items.push(...cells);
    i = j;
  }
  return items;
}

/**
 * 空格分隔「组」；单换行 = 输入行；双换行 = 分段。
 * 练习节奏作用于整组。
 * @param {string} raw
 * @param {{ spacesAsCells?: boolean }} [opts]
 *   spacesAsCells：行首／行中／行尾每个空格各占一格；仅空格的行也保留（用于「输入排版」）
 * @returns {CharGroup[]}
 */
export function parsePrintInput(raw, opts = {}) {
  const spacesAsCells = !!opts.spacesAsCells;
  const text = String(raw ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n");
  const paragraphs = text.split(/\n{2,}/);
  /** @type {CharGroup[]} */
  const groups = [];

  for (let pi = 0; pi < paragraphs.length; pi++) {
    const para = paragraphs[pi];
    if (!spacesAsCells && !para.trim()) continue;
    // 输入排版：段落里只要还有字符（含纯空格行）就保留；仅完全空串才跳过
    if (spacesAsCells && para.length === 0) continue;
    const lines = para.split("\n");
    let firstInSection = true;

    for (let li = 0; li < lines.length; li++) {
      if (spacesAsCells) {
        const rawLine = lines[li];
        // 无任何字符的空行跳过；「只有空格」的行保留为相应个数的空字格
        if (rawLine.length === 0) continue;
        const items = parseLineKeepingSpacesAsCells(rawLine);
        if (!items.length) continue;
        groups.push({
          items,
          sectionBreakBefore: pi > 0 && firstInSection,
          inputLineBreakBefore: !firstInSection,
        });
        firstInSection = false;
        continue;
      }

      const line = lines[li].replace(/[ \t\u00a0]+/g, " ").trim();
      if (!line) continue;
      const tokens = splitTokensRespectingParens(line);
      let firstInLine = true;
      for (const tok of tokens) {
        const items = parseToken(tok);
        if (!items.length) continue;
        groups.push({
          items,
          sectionBreakBefore: pi > 0 && firstInSection && firstInLine,
          inputLineBreakBefore: li > 0 && firstInLine,
        });
        firstInSection = false;
        firstInLine = false;
      }
    }
  }
  return groups;
}

/**
 * @deprecated 兼容旧双栏输入；新逻辑请用 parsePrintInput
 * @param {string} hanziRaw
 * @param {string} [pinyinRaw]
 * @returns {CharGroup[]}
 */
export function parseManualInput(hanziRaw, pinyinRaw) {
  if (pinyinRaw?.trim()) {
    // 旧双栏：汉字行 + 拼音行（空格对齐）
    const hanziParts = normalizePrintText(hanziRaw);
    const pinyinParts = normalizePrintText(pinyinRaw);
    /** @type {CharGroup[]} */
    const groups = [];
    for (let gi = 0; gi < hanziParts.length; gi++) {
      const hTokens = hanziParts[gi].split(" ").filter(Boolean);
      const pTokens = (pinyinParts[gi] || "").split(" ").filter(Boolean);
      /** @type {CharItem[]} */
      const items = [];
      for (let ti = 0; ti < hTokens.length; ti++) {
        const py = pTokens[ti] ?? "";
        const cells = expandTextToCells(hTokens[ti]);
        if (py) applyPinyinToCells(cells, py);
        items.push(...cells);
      }
      if (items.length) groups.push({ items });
    }
    return groups;
  }
  return parsePrintInput(hanziRaw);
}

/**
 * 课次勾选项格式化为输入框片段。
 * @param {{ text: string, pinyin?: string }[]} selected
 */
export function formatItemsForInput(selected) {
  return selected
    .map((it) => {
      const text = String(it.text || "").trim();
      if (!text) return "";
      const py = (it.pinyin && String(it.pinyin).trim()) || "";
      return py ? `${text}（${py}）` : text;
    })
    .filter(Boolean)
    .join(" ");
}

/**
 * @param {string} current
 * @param {string} addition
 */
export function appendInputFragment(current, addition) {
  const add = String(addition || "").trim();
  if (!add) return String(current ?? "");
  const cur = String(current ?? "").replace(/\s+$/, "");
  if (!cur) return add;
  // 若末尾已是换行段落，直接拼接；否则空格分隔
  if (/\n$/.test(cur)) return `${cur}${add}`;
  return `${cur} ${add}`;
}

/**
 * @param {object} data TEXTBOOK_WEB_DATA
 * @param {string} book
 * @param {string} tocId
 * @param {string} kind 识字表|写字表|词语表
 * @returns {{ text: string, pinyin: string }[]}
 */
export function loadLessonPrintItems(data, book, tocId, kind) {
  if (!book || !tocId) return [];

  if (kind === "词语表") {
    const rows = data.wordByBook?.[book]?.["词语表"] || [];
    const row = rows.find((r) => r?.tocId === tocId);
    if (!row) return [];
    const wordItems =
      row.wordItems?.length > 0
        ? row.wordItems
        : (row.words || []).map((w) => ({ word: w, pinyin: "" }));
    return wordItems
      .map((it) => ({
        text: String(it.word || ""),
        pinyin: (it.pinyin && String(it.pinyin).trim()) || "",
      }))
      .filter((it) => it.text);
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
      text: String(it.char || ""),
      pinyin: (it.pinyin && String(it.pinyin).trim()) || "",
    }))
    .filter((it) => it.text && isHan(it.text));
}

/**
 * @param {object} data
 * @param {string} book
 * @param {string} tocId
 * @param {string} kind
 * @returns {CharItem[]}
 * @deprecated 保留旧名，内部改走 loadLessonPrintItems 再拆字
 */
export function loadLessonCharItems(data, book, tocId, kind) {
  const tokens = loadLessonPrintItems(data, book, tocId, kind);
  /** @type {CharItem[]} */
  const items = [];
  for (const tok of tokens) {
    const cells = expandTextToCells(tok.text);
    if (tok.pinyin) applyPinyinToCells(cells, tok.pinyin);
    items.push(...cells);
  }
  return items;
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
 * @param {{ modelCount?: number, traceCount?: number, blankCount?: number }} distribution
 * @returns {{ charCount: number, cellCount: number, groupCount: number }}
 */
export function estimateStats(groups, distribution) {
  const { modelCount = 1, traceCount = 2, blankCount = 2 } = distribution;
  const passes = modelCount + traceCount + blankCount;
  let charCount = 0;
  for (const g of groups) charCount += g.items.length;
  return {
    charCount,
    cellCount: charCount * passes,
    groupCount: groups.length,
  };
}
