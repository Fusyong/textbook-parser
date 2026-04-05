/**
 * 教材字词工具 — 依赖 window.TEXTBOOK_WEB_DATA（由 scripts/export_web_data.py 生成）
 * 字表范围、组词范围均由「册 + 目录项」起点/终点确定（按书目顺序与目录顺序比较，可跨册）。
 */

const HAN_RE = /\p{Script=Han}/u;

function data() {
  return window.TEXTBOOK_WEB_DATA;
}

function showDataBanner(msg) {
  const el = document.getElementById("data-banner");
  if (!el) return;
  if (!msg) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.textContent = msg;
  el.classList.remove("hidden");
}

function isHanChar(ch) {
  return HAN_RE.test(ch);
}

/** @returns {{ bi: number, ti: number } | null} */
function tocPosition(d, bookCode, tocId) {
  if (!tocId) return null;
  const books = d.books || [];
  const bi = books.findIndex((x) => x.code === bookCode);
  if (bi < 0) return null;
  const list = d.tocByBook?.[bookCode] || [];
  const ti = list.findIndex((e) => e.id === tocId);
  if (ti < 0) return null;
  return { bi, ti };
}

/** @param {{ bi: number, ti: number }} a @param {{ bi: number, ti: number }} b */
function comparePos(a, b) {
  if (a.bi !== b.bi) return a.bi - b.bi;
  return a.ti - b.ti;
}

/**
 * @returns {{ lo: {bi:number,ti:number}, hi: {bi:number,ti:number} } | null}
 */
function normalizeLessonRange(d, startBook, startTocId, endBook, endTocId) {
  let lo = tocPosition(d, startBook, startTocId);
  let hi = tocPosition(d, endBook, endTocId);
  if (!lo || !hi) return null;
  if (comparePos(lo, hi) > 0) {
    const t = lo;
    lo = hi;
    hi = t;
  }
  return { lo, hi };
}

/** @param {{ bi:number,ti:number} } p @param {{ lo, hi }} range */
function posInRange(p, range) {
  return comparePos(range.lo, p) <= 0 && comparePos(p, range.hi) <= 0;
}

/**
 * @param {{ lo, hi }} range
 * @param {{ useShizi: boolean, useXiezi: boolean }} opts
 */
function charSetForLessonRange(range, opts) {
  const d = data();
  const { useShizi, useXiezi } = opts;
  const set = new Set();

  for (const b of d.books || []) {
    const code = b.code;
    const pack = d.charByBook[code];
    if (!pack) continue;

    if (useShizi) {
      for (const row of pack["识字表"] || []) {
        if (!row.tocId) continue;
        const p = tocPosition(d, code, row.tocId);
        if (!p || !posInRange(p, range)) continue;
        for (const c of row.chars || []) {
          if (c) set.add(c);
        }
      }
    }
    if (useXiezi) {
      for (const row of pack["写字表"] || []) {
        if (!row.tocId) continue;
        const p = tocPosition(d, code, row.tocId);
        if (!p || !posInRange(p, range)) continue;
        for (const c of row.chars || []) {
          if (c) set.add(c);
        }
      }
    }
  }
  return set;
}

/**
 * 替换模板：含 `$1` 时每个 `$1` 换为当前汉字；不含时整段作为固定替换（如 □）。
 * @param {string} template
 * @param {string} ch 当前待替换的一个汉字
 */
function applyReplaceTemplate(template, ch) {
  if (template.includes("$1")) {
    return template.split("$1").join(ch);
  }
  return template;
}

/**
 * @param {string} text
 * @param {Set<string>} knownSet
 * @param {string} placeholder 替换模板或固定字符
 * @param {"replace-known"|"replace-unknown"} mode
 */
function replaceByKnownSet(text, knownSet, placeholder, mode) {
  const chars = [...text];
  let replaced = 0;
  let hanCount = 0;

  const out = chars.map((ch) => {
    if (!isHanChar(ch)) return ch;
    hanCount++;
    const known = knownSet.has(ch);
    const shouldReplace =
      mode === "replace-known" ? known : !known;
    if (shouldReplace) {
      replaced++;
      return applyReplaceTemplate(placeholder, ch);
    }
    return ch;
  });

  return {
    text: out.join(""),
    replaced,
    hanCount,
    knownSetSize: knownSet.size,
  };
}

/**
 * 从用户输入中取第一个汉字（多字、夹杂非汉字时仅首字参与组词）。
 * @param {string} s
 */
function firstHanCharFromInput(s) {
  const t = (s || "").trim();
  if (!t) return "";
  if (typeof Intl !== "undefined" && Intl.Segmenter) {
    const iter = new Intl.Segmenter("zh", { granularity: "grapheme" });
    for (const { segment } of iter.segment(t)) {
      if (segment && isHanChar(segment)) return segment;
    }
    return "";
  }
  for (const ch of t) {
    if (isHanChar(ch)) return ch;
  }
  return "";
}

/**
 * @param {{ lo, hi }} range
 * @param {string} needle
 * @param {boolean} onlyOk
 */
function collectChunkTokenHits(range, needle, onlyOk) {
  const d = data();
  /** @type {{ w: string, src: 'c', book: string, i: number, l: string }[]} */
  const flat = [];

  for (const b of d.books || []) {
    const code = b.code;
    const chunks = d.chunksByBook?.[code] || [];
    const tokenLists = d.chunkTokensByBook?.[code] || [];
    if (tokenLists.length !== chunks.length) continue;

    for (let i = 0; i < chunks.length; i++) {
      const meta = chunks[i];
      if (!meta?.id) continue;
      const p = tocPosition(d, code, meta.id);
      if (!p || !posInRange(p, range)) continue;
      if (onlyOk && !meta.ok) continue;
      const toks = tokenLists[i] || [];
      const seenTok = new Set();
      for (const tok of toks) {
        const t = String(tok).trim();
        if (!t || !t.includes(needle) || seenTok.has(t)) continue;
        seenTok.add(t);
        flat.push({
          w: t,
          src: "c",
          book: code,
          i,
          l: meta.label || meta.id || "",
          tocId: meta.id,
        });
      }
    }
  }
  return flat;
}

/**
 * @param {{ lo, hi }} range
 * @param {string} needle
 */
function collectTableHits(range, needle) {
  const d = data();
  /** @type {{ w: string, src: 't', book: string, ri: number, l: string }[]} */
  const flat = [];

  for (const b of d.books || []) {
    const code = b.code;
    const rows = (d.wordByBook?.[code]?.["词语表"]) || [];
    for (let ri = 0; ri < rows.length; ri++) {
      const row = rows[ri];
      if (!row?.tocId) continue;
      const p = tocPosition(d, code, row.tocId);
      if (!p || !posInRange(p, range)) continue;
      const lab = row.label || "";
      const seenW = new Set();
      for (const w of row.words || []) {
        const word = String(w);
        if (!word.includes(needle) || seenW.has(word)) continue;
        seenW.add(word);
        flat.push({
          w: word,
          src: "t",
          book: code,
          ri,
          l: lab,
          tocId: row.tocId,
        });
      }
    }
  }
  return flat;
}

/** 全套教材目录项顺序（册顺序 × 每册目录顺序） */
function buildFlatTocList(d) {
  const list = [];
  for (const b of d.books || []) {
    const code = b.code;
    for (const e of d.tocByBook?.[code] || []) {
      list.push({ book: code, id: e.id });
    }
  }
  return list;
}

/**
 * 以组词面板所选「终点册 + 终点课」为锚，在全套目录顺序上：
 * - last：即该终点目录项；
 * - near：紧挨在其之前的两个目录项（倒数第二、第三，相对终点而言）；
 * - other：其余。
 * @returns {"last"|"near"|"other"}
 */
function lessonBucketRelativeToEnd(
  flatList,
  book,
  tocId,
  endBook,
  endTocId,
) {
  if (!tocId || !endBook || !endTocId) return "other";
  const endIdx = flatList.findIndex(
    (x) => x.book === endBook && x.id === endTocId,
  );
  if (endIdx < 0) return "other";
  const hitIdx = flatList.findIndex((x) => x.book === book && x.id === tocId);
  if (hitIdx < 0) return "other";
  if (hitIdx === endIdx) return "last";
  if (hitIdx === endIdx - 1 || hitIdx === endIdx - 2) return "near";
  return "other";
}

function sortWordsByFreq(words, freqMap) {
  const arr = [...words];
  arr.sort((a, b) => {
    const fa = freqMap[a] ?? 0;
    const fb = freqMap[b] ?? 0;
    if (fb !== fa) return fb - fa;
    return a.localeCompare(b, "zh");
  });
  return arr;
}

/**
 * @param {{ w: string, book: string, tocId?: string }[]} hits
 * @param {string} endBook
 * @param {string} endTocId
 * @returns {Record<"last"|"near"|"other", string>}
 */
function bucketedWordText(hits, d, endBook, endTocId) {
  const flat = buildFlatTocList(d);
  /** @type {Record<string, Set<string>>} */
  const buckets = {
    last: new Set(),
    near: new Set(),
    other: new Set(),
  };
  for (const h of hits) {
    const b = lessonBucketRelativeToEnd(
      flat,
      h.book,
      h.tocId || "",
      endBook,
      endTocId,
    );
    buckets[b].add(h.w);
  }
  const freq = d.wordFreq && typeof d.wordFreq === "object" ? d.wordFreq : {};
  const sep = "  ";
  return {
    last: sortWordsByFreq([...buckets.last], freq).join(sep),
    near: sortWordsByFreq([...buckets.near], freq).join(sep),
    other: sortWordsByFreq([...buckets.other], freq).join(sep),
  };
}

function clearWordOutputCells() {
  for (const id of [
    "word-out-body-last",
    "word-out-body-near",
    "word-out-body-other",
    "word-out-table-last",
    "word-out-table-near",
    "word-out-table-other",
  ]) {
    const el = document.getElementById(id);
    if (el) el.value = "";
  }
}

function setupTabs() {
  const tabs = document.querySelectorAll(".tab");
  const panels = {
    chars: document.getElementById("panel-chars"),
    words: document.getElementById("panel-words"),
  };
  tabs.forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-tab");
      tabs.forEach((b) => b.classList.toggle("active", b === btn));
      Object.entries(panels).forEach(([k, el]) => {
        if (el) el.classList.toggle("active", k === id);
      });
    });
  });
}

function fillBookSelect(selectId) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  const d = data();
  const cur = sel.value;
  sel.innerHTML = "";
  for (const b of d.books || []) {
    const opt = document.createElement("option");
    opt.value = b.code;
    opt.textContent = b.code;
    sel.appendChild(opt);
  }
  if (cur && [...sel.options].some((o) => o.value === cur)) sel.value = cur;
}

function fillTocSelect(bookCode, selectId) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  const d = data();
  const items = d.tocByBook?.[bookCode] || [];
  const cur = sel.value;
  sel.innerHTML = "";
  for (const e of items) {
    const opt = document.createElement("option");
    opt.value = e.id;
    opt.textContent = e.label;
    sel.appendChild(opt);
  }
  if (cur && [...sel.options].some((o) => o.value === cur)) {
    sel.value = cur;
  } else if (items.length) {
    sel.selectedIndex = 0;
  }
}

/**
 * @param {string} prefix 如 char-start → #prefix-book #prefix-toc
 */
function bindBookTocPair(prefix) {
  const bookSel = document.getElementById(`${prefix}-book`);
  const tocSel = document.getElementById(`${prefix}-toc`);
  if (!bookSel || !tocSel) return;
  const sync = () => fillTocSelect(bookSel.value, `${prefix}-toc`);
  bookSel.addEventListener("change", sync);
  sync();
}

function defaultLessonEndpoints() {
  const d = data();
  const first = d.books?.[0]?.code;
  if (!first) return;
  const items = d.tocByBook?.[first] || [];
  const lastId = items.length ? items[items.length - 1].id : "";

  const bookIds = ["char-start-book", "char-end-book", "word-start-book", "word-end-book"];
  for (const bid of bookIds) {
    const bs = document.getElementById(bid);
    if (bs) bs.value = first;
  }
  const tocPairs = [
    ["char-start-book", "char-start-toc"],
    ["char-end-book", "char-end-toc"],
    ["word-start-book", "word-start-toc"],
    ["word-end-book", "word-end-toc"],
  ];
  for (const [bid, tid] of tocPairs) {
    fillTocSelect(document.getElementById(bid)?.value || first, tid);
  }
  const endTocs = ["char-end-toc", "word-end-toc"];
  for (const id of endTocs) {
    const el = document.getElementById(id);
    if (el && lastId) el.value = lastId;
  }
}

function runCharCheck() {
  const d = data();
  const sb = document.getElementById("char-start-book")?.value;
  const st = document.getElementById("char-start-toc")?.value;
  const eb = document.getElementById("char-end-book")?.value;
  const et = document.getElementById("char-end-toc")?.value;

  const range = normalizeLessonRange(d, sb, st, eb, et);
  if (!range) {
    showDataBanner("无法确定目录范围：请确认已导出 目录.json，且起点、终点的「课」有效。");
    return;
  }

  const placeholder = document.getElementById("char-placeholder")?.value || "□";
  const input = document.getElementById("char-input")?.value || "";
  const mode = document.querySelector('input[name="char-mode"]:checked')?.value || "replace-known";

  const useShizi = document.getElementById("char-use-shizi")?.checked;
  const useXiezi = document.getElementById("char-use-xiezi")?.checked;

  if (!useShizi && !useXiezi) {
    showDataBanner("请至少勾选「识字表」或「写字表」之一。");
    return;
  }

  const knownSet = charSetForLessonRange(range, { useShizi, useXiezi });

  const result = replaceByKnownSet(
    input,
    knownSet,
    placeholder,
    mode === "replace-unknown" ? "replace-unknown" : "replace-known",
  );

  const outEl = document.getElementById("char-output");
  if (outEl) outEl.value = result.text;

  const stats = document.getElementById("char-stats");
  if (stats) {
    stats.textContent = `汉字共 ${result.hanCount} 个；本次替换 ${result.replaced} 个；当前范围内字表去重后 ${result.knownSetSize} 字。`;
  }
  showDataBanner("");
}

function runWordSearch() {
  const d = data();
  const rawTarget = document.getElementById("word-char")?.value || "";
  const needle = firstHanCharFromInput(rawTarget);
  const statusEl = document.getElementById("word-status");

  if (!needle) {
    showDataBanner("请输入至少一个汉字（多字时只取第一个汉字参与检索）。");
    return;
  }

  const sb = document.getElementById("word-start-book")?.value;
  const st = document.getElementById("word-start-toc")?.value;
  const eb = document.getElementById("word-end-book")?.value;
  const et = document.getElementById("word-end-toc")?.value;

  const range = normalizeLessonRange(d, sb, st, eb, et);
  if (!range) {
    showDataBanner("无法确定目录范围：请确认已导出 目录.json，且起点、终点的「课」有效。");
    clearWordOutputCells();
    if (statusEl) statusEl.textContent = "";
    return;
  }

  const onlyOk = document.getElementById("word-only-ok")?.checked;
  const inclTable = document.getElementById("word-include-words-table")?.checked;

  let chunkTokenMismatch = false;
  for (const b of d.books || []) {
    const c = d.chunksByBook?.[b.code] || [];
    const t = d.chunkTokensByBook?.[b.code];
    if (!Array.isArray(t) || t.length !== c.length) {
      chunkTokenMismatch = true;
      break;
    }
  }

  if (chunkTokenMismatch) {
    showDataBanner(
      "chunkTokensByBook 与分块数量不一致。请安装 jieba 后重新运行: python scripts/export_web_data.py",
    );
    clearWordOutputCells();
    if (statusEl) statusEl.textContent = "";
    return;
  }

  if (!d.wordFreq || typeof d.wordFreq !== "object") {
    showDataBanner(
      "数据缺少 wordFreq（请重新运行 scripts/export_web_data.py 生成 v4 数据）以按全套教材词频排序。",
    );
    clearWordOutputCells();
    if (statusEl) statusEl.textContent = "";
    return;
  }

  const chunkHits = collectChunkTokenHits(range, needle, onlyOk);
  const tableHits = inclTable ? collectTableHits(range, needle) : [];

  const bodyCols = bucketedWordText(chunkHits, d, eb, et);
  const tableCols = bucketedWordText(tableHits, d, eb, et);

  const setVal = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.value = text;
  };
  setVal("word-out-body-last", bodyCols.last);
  setVal("word-out-body-near", bodyCols.near);
  setVal("word-out-body-other", bodyCols.other);
  setVal("word-out-table-last", tableCols.last);
  setVal("word-out-table-near", tableCols.near);
  setVal("word-out-table-other", tableCols.other);

  if (statusEl) {
    const total = chunkHits.length + tableHits.length;
    const uniqChunkWords = new Set(chunkHits.map((h) => h.w)).size;
    const uniqTableWords = new Set(tableHits.map((h) => h.w)).size;
    let scannedTokens = 0;
    for (const b of d.books || []) {
      const code = b.code;
      const chunks = d.chunksByBook?.[code] || [];
      const tokenLists = d.chunkTokensByBook?.[code] || [];
      for (let i = 0; i < chunks.length; i++) {
        const meta = chunks[i];
        if (!meta?.id) continue;
        const p = tocPosition(d, code, meta.id);
        if (!p || !posInRange(p, range)) continue;
        if (onlyOk && !meta.ok) continue;
        scannedTokens += (tokenLists[i] || []).length;
      }
    }
    const usedNote =
      firstHanCharFromInput(rawTarget) &&
      rawTarget.trim() !== needle &&
      rawTarget.trim().length > 0
        ? `（已用首字「${needle}」）`
        : "";
    statusEl.textContent =
      total === 0
        ? `所选范围内无匹配（可扩大目录范围，或取消「仅 ok」）。${usedNote}`
        : `已在约 ${scannedTokens} 个预分词中筛选：正文命中 ${chunkHits.length} 条（${uniqChunkWords} 个不同词），词语表 ${tableHits.length} 条（${uniqTableWords} 个不同词）。${usedNote}`;
  }
  showDataBanner("");
}

function init() {
  const d = data();
  if (!d || !Array.isArray(d.books) || d.books.length === 0) {
    showDataBanner(
      "未找到数据：请在项目根目录运行 python scripts/export_web_data.py，生成 web/generated/data.js 后刷新。",
    );
    setupTabs();
    return;
  }

  if (!d.tocByBook || typeof d.tocByBook !== "object") {
    showDataBanner(
      "数据缺少 tocByBook（版本过旧）。请重新运行: python scripts/export_web_data.py",
    );
    setupTabs();
    return;
  }

  const warns = d.exportWarnings || [];
  if (warns.length) {
    showDataBanner(`数据已加载；导出提示：${warns.slice(0, 3).join("；")}${warns.length > 3 ? "…" : ""}`);
  } else {
    showDataBanner("");
  }

  setupTabs();

  for (const id of ["char-start-book", "char-end-book", "word-start-book", "word-end-book"]) {
    fillBookSelect(id);
  }
  bindBookTocPair("char-start");
  bindBookTocPair("char-end");
  bindBookTocPair("word-start");
  bindBookTocPair("word-end");
  defaultLessonEndpoints();

  document.getElementById("char-run")?.addEventListener("click", runCharCheck);
  document.getElementById("word-run")?.addEventListener("click", runWordSearch);
}

function bindInputEnterShortcuts() {
  const onEnter = (id, fn) => {
    const el = document.getElementById(id);
    el?.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      fn();
    });
  };
  onEnter("char-placeholder", runCharCheck);
  onEnter("word-char", runWordSearch);
}

init();
bindInputEnterShortcuts();
