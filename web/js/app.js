/**
 * 小学语文教材字词工具 — 依赖 window.TEXTBOOK_WEB_DATA（由 scripts/export_web_data.py 生成）
 * 文本检查、组词范围均由「册 + 目录项」起点/终点确定（按书目顺序与目录顺序比较，可跨册）。
 * v9+：可按「成套教材」切换数据视图。
 */

const HAN_RE = /\p{Script=Han}/u;

/** @type {string | null} */
let activeSetId = null;

function rawData() {
  return window.TEXTBOOK_WEB_DATA;
}

/**
 * 当前成套视图（含 books / tocByBook / wordFreq 等）。
 * 无 sets 时退回顶层字段（兼容旧 data.js）。
 */
function data() {
  const r = rawData();
  if (!r) return r;
  const sets = r.sets;
  if (!Array.isArray(sets) || !sets.length) {
    return r;
  }
  const id = activeSetId || r.defaultSetId || sets[0]?.id;
  const set = sets.find((s) => s.id === id) || sets[0];
  const view = set?.view;
  if (!view) {
    return { ...r, _set: set };
  }
  return {
    ...r,
    books: view.books || [],
    tocByBook: view.tocByBook || {},
    charByBook: view.charByBook || {},
    wordByBook: view.wordByBook || {},
    chunksByBook: view.chunksByBook || {},
    chunkTokensByBook: view.chunkTokensByBook || {},
    wordFreq: view.wordFreq || {},
    bookSources: view.bookSources || {},
    _set: set,
  };
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

function formatSubstitutionTip(subs) {
  if (!subs?.length) return "";
  return (
    "教材替换情况：" +
    subs
      .map((s) => {
        if (s.message) return s.message;
        const expect = s.expectedBatch ? `本应由 ${s.expectedBatch} 提供，` : "";
        return `${s.code}：${expect}现以 ${s.fromBatch || "?"} 顶替`;
      })
      .join("；")
  );
}

function setBannerForActiveSet() {
  const d = data();
  const set = d?._set;
  const subs = set?.substitutions || [];
  const setId = set?.id || "";
  const exportWarns = (rawData()?.exportWarnings || [])
    .filter((w) => !setId || String(w).includes(setId))
    .slice(0, 3);
  const parts = [];
  const subTip = formatSubstitutionTip(subs);
  if (subTip) {
    parts.push(subTip);
  }
  if (exportWarns.length) {
    parts.push(`导出提示：${exportWarns.join("；")}`);
  }
  // 仅在有替换或导出告警时显示横幅，避免无事也占一条警告条
  showDataBanner(parts.length ? parts.join("。") : "");
}

function fillSetSelect() {
  const sel = document.getElementById("textbook-set");
  if (!sel) return;
  const r = rawData();
  const sets = r?.sets || [];
  sel.innerHTML = "";
  if (!sets.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "（单批数据）";
    sel.appendChild(opt);
    sel.disabled = true;
    return;
  }
  sel.disabled = false;
  // 较新的套排前面，便于选择
  const ordered = [...sets].reverse();
  for (const s of ordered) {
    const opt = document.createElement("option");
    opt.value = s.id;
    const n = (s.slots || []).filter(Boolean).length;
    const subs = s.substitutions || [];
    opt.textContent = subs.length
      ? `${s.label}（${n}册，有替换）`
      : `${s.label}（${n}册）`;
    const tip = formatSubstitutionTip(subs);
    if (tip) opt.title = tip;
    sel.appendChild(opt);
  }
  const want = activeSetId || r.defaultSetId || sets[0]?.id;
  if (want && [...sel.options].some((o) => o.value === want)) {
    sel.value = want;
    activeSetId = want;
  }
}

function applyActiveSet() {
  const d = data();
  for (const id of [
    "char-start-book",
    "char-end-book",
    "word-start-book",
    "word-end-book",
    "lexicon-book",
    "print-book",
  ]) {
    fillBookSelect(id);
  }
  for (const prefix of ["char-start", "char-end", "word-start", "word-end"]) {
    const bookSel = document.getElementById(`${prefix}-book`);
    if (bookSel) fillTocSelect(bookSel.value, `${prefix}-toc`);
  }
  defaultLessonEndpoints();
  if (d.books?.[0]?.code) {
    const lexBook = document.getElementById("lexicon-book");
    if (lexBook) lexBook.value = d.books[0].code;
    const printBook = document.getElementById("print-book");
    if (printBook) printBook.value = d.books[0].code;
  }
  refreshPrintLessonPanel();
  renderLexicon();
  setBannerForActiveSet();
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

/** 字表行中的汉字列表（兼容仅有 chars[] 的旧导出）。 */
function rowCharsFromRow(row) {
  if (row?.charItems?.length) {
    return row.charItems.map((x) => x?.char).filter(Boolean);
  }
  return row.chars || [];
}

/** 全文按字素拆成数组（含非汉字），用于整词对齐与替换。 */
function graphemesOfString(s) {
  const t = s || "";
  if (typeof Intl !== "undefined" && Intl.Segmenter) {
    const out = [];
    const iter = new Intl.Segmenter("zh", { granularity: "grapheme" });
    for (const { segment } of iter.segment(t)) {
      if (segment) out.push(segment);
    }
    return out;
  }
  return [...t];
}

/** 按出现顺序取出文本中全部汉字（去重时保留首次出现顺序）。 */
function hanGraphemesInOrder(s) {
  return graphemesOfString(s).filter((g) => isHanChar(g));
}

function uniqueHanFirstOrder(s) {
  const seen = new Set();
  const out = [];
  for (const ch of hanGraphemesInOrder(s)) {
    if (seen.has(ch)) continue;
    seen.add(ch);
    out.push(ch);
  }
  return out;
}

/**
 * @param {string} ch
 * @returns {{ book: string, table: string, label: string, rowI: number }[]}
 */
function collectCharLookupHits(d, ch) {
  const hits = [];
  for (const b of d.books || []) {
    const code = b.code;
    const pack = d.charByBook?.[code];
    if (!pack) continue;
    for (const tableName of ["识字表", "写字表"]) {
      const rows = pack[tableName] || [];
      for (const row of rows) {
        if (!row || typeof row !== "object") continue;
        const cs = rowCharsFromRow(row);
        if (!cs.includes(ch)) continue;
        hits.push({
          book: code,
          table: tableName,
          label: row.label || "",
          rowI: typeof row.i === "number" ? row.i : 0,
        });
      }
    }
  }
  return hits;
}

/**
 * @param {string} word
 * @returns {{ book: string, label: string, rowI: number }[]}
 */
function collectWordLookupHits(d, word) {
  const w = String(word).trim();
  const hits = [];
  if (!w) return hits;
  for (const b of d.books || []) {
    const code = b.code;
    const rows = d.wordByBook?.[code]?.["词语表"] || [];
    for (const row of rows) {
      if (!row || typeof row !== "object") continue;
      const words = row.words || [];
      if (!words.includes(w)) continue;
      hits.push({
        book: code,
        label: row.label || "",
        rowI: typeof row.i === "number" ? row.i : 0,
      });
    }
  }
  return hits;
}

function sortCharLookupHits(hits, d) {
  const bookIdx = {};
  (d.books || []).forEach((b, i) => {
    bookIdx[b.code] = i;
  });
  const tOrder = { 识字表: 0, 写字表: 1 };
  return [...hits].sort((a, b) => {
    const bi = bookIdx[a.book] ?? 999;
    const bj = bookIdx[b.book] ?? 999;
    if (bi !== bj) return bi - bj;
    const ti = tOrder[a.table] ?? 9;
    const tj = tOrder[b.table] ?? 9;
    if (ti !== tj) return ti - tj;
    return a.rowI - b.rowI;
  });
}

function sortWordLookupHits(hits, d) {
  const bookIdx = {};
  (d.books || []).forEach((b, i) => {
    bookIdx[b.code] = i;
  });
  return [...hits].sort((a, b) => {
    const bi = bookIdx[a.book] ?? 999;
    const bj = bookIdx[b.book] ?? 999;
    if (bi !== bj) return bi - bj;
    return a.rowI - b.rowI;
  });
}

function runLookup() {
  const d = data();
  const outEl = document.getElementById("lookup-output");
  const mode = document.querySelector('input[name="lookup-mode"]:checked')?.value || "chars";
  const raw = document.getElementById("lookup-input")?.value || "";

  if (!outEl) return;

  if (mode === "words") {
    const parts = raw
      .trim()
      .split(/\s+/)
      .map((x) => x.trim())
      .filter(Boolean);
    if (!parts.length) {
      outEl.value = "请输入至少一个词（多个词用空格分隔）。";
      showDataBanner("");
      return;
    }
    const lines = [];
    for (const w of parts) {
      lines.push(w);
      const hits = sortWordLookupHits(collectWordLookupHits(d, w), d);
      if (!hits.length) {
        lines.push("  （全套教材词语表中未出现。）");
      } else {
        for (const h of hits) {
          const lab = h.label ? ` · ${h.label}` : "";
          lines.push(`  册 ${h.book}${lab}`);
        }
      }
      lines.push("");
    }
    outEl.value = lines.join("\n").trimEnd();
    showDataBanner("");
    return;
  }

  const chars = uniqueHanFirstOrder(raw);
  if (!chars.length) {
    outEl.value = "请输入至少一个汉字。";
    showDataBanner("");
    return;
  }

  const lines = [];
  for (const ch of chars) {
    lines.push(ch);
    const hits = sortCharLookupHits(collectCharLookupHits(d, ch), d);
    if (!hits.length) {
      lines.push("  （识字表、写字表中均未出现。）");
    } else {
      for (const h of hits) {
        const lab = h.label ? ` · ${h.label}` : "";
        lines.push(`  册 ${h.book} · ${h.table}${lab}`);
      }
    }
    lines.push("");
  }
  outEl.value = lines.join("\n").trimEnd();
  showDataBanner("");
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
        for (const c of rowCharsFromRow(row)) {
          if (c) set.add(c);
        }
      }
    }
    if (useXiezi) {
      for (const row of pack["写字表"] || []) {
        if (!row.tocId) continue;
        const p = tocPosition(d, code, row.tocId);
        if (!p || !posInRange(p, range)) continue;
        for (const c of rowCharsFromRow(row)) {
          if (c) set.add(c);
        }
      }
    }
  }

  return set;
}

/** 范围内词语表中的词形（去重），用于整词匹配。 */
function knownWordsInLessonRange(d, range) {
  const words = new Set();
  for (const b of d.books || []) {
    const code = b.code;
    const rows = d.wordByBook?.[code]?.["词语表"] || [];
    for (const row of rows) {
      if (!row.tocId) continue;
      const p = tocPosition(d, code, row.tocId);
      if (!p || !posInRange(p, range)) continue;
      for (const w of row.words || []) {
        const s = String(w).trim();
        if (s) words.add(s);
      }
    }
  }
  return [...words];
}

function sortWordsLongestFirst(words) {
  const arr = [...words];
  arr.sort((a, b) => {
    const la = graphemesOfString(a).length;
    const lb = graphemesOfString(b).length;
    if (lb !== la) return lb - la;
    return a.localeCompare(b, "zh");
  });
  return arr;
}

/**
 * 先按词语表整词匹配（长词优先），再对其余字素按识字／写字集合替换。
 * @param {string} text
 * @param {string[]} sortedWords 已按词长降序
 * @param {Set<string>} charKnownSet
 */
function replaceWordThenChar(text, sortedWords, charKnownSet, placeholder, mode) {
  const g = graphemesOfString(text);
  let hanCount = 0;
  for (const x of g) {
    if (isHanChar(x)) hanCount++;
  }

  const out = [];
  let replaced = 0;
  let i = 0;
  while (i < g.length) {
    let matched = null;
    for (const w of sortedWords) {
      const wg = graphemesOfString(w);
      if (wg.length === 0 || i + wg.length > g.length) continue;
      let same = true;
      for (let k = 0; k < wg.length; k++) {
        if (g[i + k] !== wg[k]) {
          same = false;
          break;
        }
      }
      if (same) {
        matched = w;
        break;
      }
    }

    if (matched !== null) {
      const wg = graphemesOfString(matched);
      const nHan = wg.reduce((n, ch) => n + (isHanChar(ch) ? 1 : 0), 0);
      const shouldReplace =
        mode === "replace-known" ? true : false;
      if (shouldReplace) {
        if (placeholder.includes("$1")) {
          out.push(wg.map((ch) => applyReplaceTemplate(placeholder, ch)).join(""));
        } else {
          out.push(placeholder);
        }
        replaced += nHan;
      } else {
        out.push(...wg);
      }
      i += wg.length;
      continue;
    }

    const ch = g[i];
    if (!isHanChar(ch)) {
      out.push(ch);
      i++;
      continue;
    }
    const known = charKnownSet.has(ch);
    const shouldReplace =
      mode === "replace-known" ? known : !known;
    if (shouldReplace) {
      replaced++;
      out.push(applyReplaceTemplate(placeholder, ch));
    } else {
      out.push(ch);
    }
    i++;
  }

  return {
    text: out.join(""),
    replaced,
    hanCount,
    knownSetSize: charKnownSet.size,
  };
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
 * 范围内的正文分词（不按字过滤，供单字与批量共用）。
 * @param {{ lo, hi }} range
 * @param {boolean} onlyOk
 * @returns {{ hits: { w: string, src: 'c', book: string, i: number, l: string, tocId: string }[], scanned: number }}
 */
function collectChunkTokens(range, onlyOk) {
  const d = data();
  /** @type {{ w: string, src: 'c', book: string, i: number, l: string, tocId: string }[]} */
  const flat = [];
  let scanned = 0;

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
      scanned += toks.length;
      const seenTok = new Set();
      for (const tok of toks) {
        const t = String(tok).trim();
        if (!t || seenTok.has(t)) continue;
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
  return { hits: flat, scanned };
}

/**
 * @param {{ lo, hi }} range
 * @returns {{ w: string, src: 't', book: string, ri: number, l: string, tocId: string }[]}
 */
function collectTableTokens(range) {
  const d = data();
  /** @type {{ w: string, src: 't', book: string, ri: number, l: string, tocId: string }[]} */
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
        if (!word || seenW.has(word)) continue;
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

/** @param {{ w: string }[]} hits @param {boolean} skipMono */
function filterWordHits(hits, skipMono) {
  if (!skipMono) return hits;
  return hits.filter((h) => [...String(h.w || "")].length >= 2);
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
 * @param {{ book: string, id: string }[]} [flatList]
 * @returns {Record<"last"|"near"|"other", string[]>}
 */
function bucketWordLists(hits, d, endBook, endTocId, flatList) {
  const flat = flatList || buildFlatTocList(d);
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
  return {
    last: sortWordsByFreq([...buckets.last], freq),
    near: sortWordsByFreq([...buckets.near], freq),
    other: sortWordsByFreq([...buckets.other], freq),
  };
}

/** @param {Record<"last"|"near"|"other", string[]>} lists @param {number} n */
function capWordLists(lists, n) {
  if (!n) return lists;
  return {
    last: lists.last.slice(0, n),
    near: lists.near.slice(0, n),
    other: lists.other.slice(0, n),
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
    "word-picked",
  ]) {
    const el = document.getElementById(id);
    if (el) el.value = "";
  }
}

function clearWordOutputs() {
  clearWordOutputCells();
  const batch = document.getElementById("word-batch-output");
  if (batch) batch.value = "";
}

function setWordStatus(msg) {
  const el = document.getElementById("word-status");
  if (el) el.textContent = msg || "";
}

function wordResultApi() {
  const api = window.WordResult;
  if (!api) {
    showDataBanner("组词模块未加载（word-result.js）。");
    return null;
  }
  return api;
}

const WORD_SETTINGS_KEY = "textbook-parser.word-settings.v1";

/** 最近一次单字检索实际使用的汉字，供「按格子重填选用」。 */
let lastSingleNeedle = "";

function readIntInput(id, fallback, min, max) {
  const el = document.getElementById(id);
  const v = parseInt(el?.value ?? "", 10);
  const n = Number.isFinite(v) ? Math.min(max, Math.max(min, v)) : fallback;
  if (el && el.value !== String(n)) el.value = String(n);
  return n;
}

function readWordPickOptions() {
  const prefer = document.querySelector('input[name="word-prefer"]:checked')?.value;
  return {
    limit: readIntInput("word-per-char", 6, 1, 30),
    perBucket: readIntInput("word-per-bucket", 0, 0, 50),
    include: {
      last: document.getElementById("word-bucket-last")?.checked !== false,
      near: document.getElementById("word-bucket-near")?.checked !== false,
      other: document.getElementById("word-bucket-other")?.checked !== false,
    },
    prefer: prefer === "body" ? "body" : "table",
    skipMono: document.getElementById("word-skip-mono")?.checked !== false,
    withNotes: document.getElementById("word-with-notes")?.checked !== false,
  };
}

function wordModeIsBatch() {
  return document.querySelector('input[name="word-mode"]:checked')?.value === "batch";
}

function applyWordMode() {
  const batch = wordModeIsBatch();
  document.getElementById("word-single-result")?.classList.toggle("hidden", batch);
  document.getElementById("word-batch-result")?.classList.toggle("hidden", !batch);
  const input = document.getElementById("word-char");
  if (input) {
    input.placeholder = batch ? "春夏秋冬" : "春";
    input.title = batch ? "" : "多个汉字时只取第一个。";
  }
}

function collectWordSettings() {
  const opts = readWordPickOptions();
  return {
    mode: wordModeIsBatch() ? "batch" : "single",
    onlyOk: document.getElementById("word-only-ok")?.checked !== false,
    includeTable: document.getElementById("word-include-words-table")?.checked !== false,
    perChar: opts.limit,
    perBucket: opts.perBucket,
    bucketLast: opts.include.last,
    bucketNear: opts.include.near,
    bucketOther: opts.include.other,
    prefer: opts.prefer,
    skipMono: opts.skipMono,
    withNotes: opts.withNotes,
  };
}

function saveWordSettings() {
  try {
    localStorage.setItem(WORD_SETTINGS_KEY, JSON.stringify(collectWordSettings()));
  } catch {
    // 隐私模式或配额不足时忽略。
  }
}

function loadWordSettings() {
  let saved = null;
  try {
    const raw = localStorage.getItem(WORD_SETTINGS_KEY);
    if (raw) saved = JSON.parse(raw);
  } catch {
    saved = null;
  }
  if (!saved || typeof saved !== "object") return;

  const setCheck = (id, value) => {
    const el = document.getElementById(id);
    if (el && typeof value === "boolean") el.checked = value;
  };
  const setNum = (id, value) => {
    const el = document.getElementById(id);
    if (el && Number.isFinite(Number(value))) el.value = String(value);
  };
  const setRadio = (name, value) => {
    const el = document.querySelector(`input[name="${name}"][value="${value}"]`);
    if (el) el.checked = true;
  };

  setRadio("word-mode", saved.mode === "batch" ? "batch" : "single");
  setCheck("word-only-ok", saved.onlyOk);
  setCheck("word-include-words-table", saved.includeTable);
  setNum("word-per-char", saved.perChar);
  setNum("word-per-bucket", saved.perBucket);
  setCheck("word-bucket-last", saved.bucketLast);
  setCheck("word-bucket-near", saved.bucketNear);
  setCheck("word-bucket-other", saved.bucketOther);
  setRadio("word-prefer", saved.prefer === "body" ? "body" : "table");
  setCheck("word-skip-mono", saved.skipMono);
  setCheck("word-with-notes", saved.withNotes);
}

function bindWordSettings() {
  const root = document.getElementById("panel-words");
  root?.addEventListener("change", (e) => {
    const t = e.target;
    if (!(t instanceof Element)) return;
    const id = t.id || "";
    const name = t.getAttribute("name") || "";
    const tracked =
      id.startsWith("word-") || name === "word-mode" || name === "word-prefer";
    if (!tracked) return;
    if (id === "word-char" || id === "word-batch-output" || id === "word-picked") return;
    if (id.startsWith("word-out-")) return;
    if (name === "word-mode") applyWordMode();
    saveWordSettings();
  });
}

function fillWordGrid(body, table) {
  const WR = wordResultApi();
  if (!WR) return;
  const put = (id, words) => {
    const el = document.getElementById(id);
    if (el) el.value = WR.joinWords(words);
  };
  put("word-out-body-last", body.last);
  put("word-out-body-near", body.near);
  put("word-out-body-other", body.other);
  put("word-out-table-last", table.last);
  put("word-out-table-near", table.near);
  put("word-out-table-other", table.other);
}

function bucketNotes(body, table) {
  const WR = wordResultApi();
  if (!WR) return [];
  return [
    WR.formatBucketNote("终点课·正文", body.last),
    WR.formatBucketNote("终点课·词语表", table.last),
    WR.formatBucketNote("前两课·正文", body.near),
    WR.formatBucketNote("前两课·词语表", table.near),
    WR.formatBucketNote("其他·正文", body.other),
    WR.formatBucketNote("其他·词语表", table.other),
  ].filter(Boolean);
}

function listsFromCell(id) {
  const WR = wordResultApi();
  if (!WR) return [];
  return WR.splitWords(document.getElementById(id)?.value || "");
}

/**
 * 校验目录范围与导出数据。失败时写提示并返回 null。
 * @returns {{ d: object, range: object, eb: string, et: string, onlyOk: boolean, inclTable: boolean, chunkHits: object[], tableHits: object[], scanned: number } | null}
 */
function prepareWordQuery() {
  const d = data();
  const sb = document.getElementById("word-start-book")?.value;
  const st = document.getElementById("word-start-toc")?.value;
  const eb = document.getElementById("word-end-book")?.value;
  const et = document.getElementById("word-end-toc")?.value;
  const range = normalizeLessonRange(d, sb, st, eb, et);
  if (!range) {
    showDataBanner("无法确定目录范围：请确认已导出 目录.json，且起点、终点的「课」有效。");
    clearWordOutputs();
    setWordStatus("");
    return null;
  }

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
    clearWordOutputs();
    setWordStatus("");
    return null;
  }
  if (!d.wordFreq || typeof d.wordFreq !== "object") {
    showDataBanner(
      "数据缺少 wordFreq（请重新运行 scripts/export_web_data.py 重新导出）以按全套教材词频排序。",
    );
    clearWordOutputs();
    setWordStatus("");
    return null;
  }

  const onlyOk = document.getElementById("word-only-ok")?.checked;
  const inclTable = document.getElementById("word-include-words-table")?.checked;
  const chunk = collectChunkTokens(range, !!onlyOk);
  return {
    d,
    range,
    eb,
    et,
    onlyOk: !!onlyOk,
    inclTable: !!inclTable,
    chunkHits: chunk.hits,
    tableHits: inclTable ? collectTableTokens(range) : [],
    scanned: chunk.scanned,
  };
}

function indexesFor(ctx, skipMono) {
  const WR = wordResultApi();
  if (!WR) return null;
  return {
    chunkIndex: WR.indexByChar(filterWordHits(ctx.chunkHits, skipMono)),
    tableIndex: WR.indexByChar(filterWordHits(ctx.tableHits, skipMono)),
    flat: buildFlatTocList(ctx.d),
  };
}

function bucketsForChar(indexes, ch, ctx, perBucket) {
  const body = capWordLists(
    bucketWordLists(indexes.chunkIndex.get(ch) || [], ctx.d, ctx.eb, ctx.et, indexes.flat),
    perBucket,
  );
  const table = capWordLists(
    bucketWordLists(indexes.tableIndex.get(ch) || [], ctx.d, ctx.eb, ctx.et, indexes.flat),
    perBucket,
  );
  return { body, table };
}

function refillPickedFromGrid() {
  const WR = wordResultApi();
  if (!WR) return;
  const ch =
    firstHanCharFromInput(document.getElementById("word-char")?.value || "") || lastSingleNeedle;
  if (!ch) {
    setWordStatus("请先检索一个字。");
    return;
  }
  const opts = readWordPickOptions();
  const body = {
    last: listsFromCell("word-out-body-last"),
    near: listsFromCell("word-out-body-near"),
    other: listsFromCell("word-out-body-other"),
  };
  const table = {
    last: listsFromCell("word-out-table-last"),
    near: listsFromCell("word-out-table-near"),
    other: listsFromCell("word-out-table-other"),
  };
  const picked = WR.pickWords({ body, table }, opts);
  const el = document.getElementById("word-picked");
  if (el) el.value = WR.formatPickedLine(ch, picked);
  const bucketNote =
    !opts.include.last && !opts.include.near && !opts.include.other
      ? "未勾选纳入分桶，选用为空。"
      : `已按当前格子重填选用（${picked.length} 个词）。`;
  setWordStatus(bucketNote);
}

function keepWordPickedOnly() {
  const WR = wordResultApi();
  const el = document.getElementById("word-batch-output");
  if (!WR || !el) return;
  el.value = WR.keepPickedLines(el.value);
  setWordStatus("已去掉参考行和空行。");
}

async function copyWordResult() {
  const batch = wordModeIsBatch();
  const el = document.getElementById(batch ? "word-batch-output" : "word-picked");
  let text = el?.value || "";
  if (batch && window.WordResult) text = window.WordResult.keepPickedLines(text);
  if (!text.trim()) {
    setWordStatus("没有可复制的选用。");
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    setWordStatus("已复制到剪贴板。");
    return;
  } catch {
    // 剪贴板权限不足时改用选区复制。
  }
  const helper = document.createElement("textarea");
  helper.value = text;
  helper.setAttribute("readonly", "");
  helper.style.position = "fixed";
  helper.style.left = "-9999px";
  document.body.appendChild(helper);
  helper.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  helper.remove();
  setWordStatus(ok ? "已复制到剪贴板。" : "复制失败，请在结果框中手动选择。");
}

function bootWordSettings() {
  loadWordSettings();
  applyWordMode();
  bindWordSettings();
  document.getElementById("word-refill-picked")?.addEventListener("click", refillPickedFromGrid);
  document.getElementById("word-keep-picked")?.addEventListener("click", keepWordPickedOnly);
  document.querySelectorAll(".word-copy").forEach((btn) => {
    btn.addEventListener("click", () => {
      copyWordResult();
    });
  });
}

function setupTabs() {
  const tabs = document.querySelectorAll(".tab");
  const panels = {
    chars: document.getElementById("panel-chars"),
    words: document.getElementById("panel-words"),
    lookup: document.getElementById("panel-lookup"),
    lexicon: document.getElementById("panel-lexicon"),
    print: document.getElementById("panel-print"),
  };
  tabs.forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-tab");
      tabs.forEach((b) => b.classList.toggle("active", b === btn));
      Object.entries(panels).forEach(([k, el]) => {
        if (el) el.classList.toggle("active", k === id);
      });
      if (id === "lexicon") renderLexicon();
      if (id === "print") {
        refreshPrintLessonPanel();
        if (window.initPrintSheet) window.initPrintSheet();
      }
    });
  });
}

/**
 * 课次字词勾选项（识字／写字按字；词语表按整词，便于写入输入框）。
 * @returns {{ text: string, pinyin: string }[]}
 */
function loadLessonPrintItems(d, book, tocId, kind) {
  if (!book || !tocId) return [];

  if (kind === "词语表") {
    const rows = d.wordByBook?.[book]?.["词语表"] || [];
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

  const rows = d.charByBook?.[book]?.[kind] || [];
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
    .filter((it) => it.text && isHanChar(it.text));
}

/** @deprecated */
function loadLessonCharItems(d, book, tocId, kind) {
  return loadLessonPrintItems(d, book, tocId, kind).map((it) => ({
    char: it.text,
    pinyin: it.pinyin,
  }));
}

/** 若当前课无字词，自动跳到本册第一个有数据的目录项。 */
function preferPrintTocWithContent() {
  const d = data();
  const book = document.getElementById("print-book")?.value;
  const kind = document.getElementById("print-kind")?.value || "写字表";
  const tocSel = document.getElementById("print-toc");
  if (!book || !tocSel) return;
  if (loadLessonPrintItems(d, book, tocSel.value, kind).length) return;
  for (const e of d.tocByBook?.[book] || []) {
    if (loadLessonPrintItems(d, book, e.id, kind).length) {
      tocSel.value = e.id;
      return;
    }
  }
}

function renderPrintLessonChecklist() {
  const wrap = document.getElementById("print-char-checklist");
  if (!wrap) return;
  const d = data();
  const book = document.getElementById("print-book")?.value;
  const tocId = document.getElementById("print-toc")?.value;
  const kind = document.getElementById("print-kind")?.value || "写字表";
  const items = loadLessonPrintItems(d, book, tocId, kind);

  wrap.replaceChildren();
  if (!items.length) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "本课暂无字词，请换课次或表类型。";
    wrap.appendChild(p);
    if (typeof window.updatePrintEstimate === "function") window.updatePrintEstimate();
    return;
  }

  const frag = document.createDocumentFragment();
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    const lab = document.createElement("label");
    lab.className = "print-char-check";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = true;
    cb.setAttribute("data-text", it.text);
    cb.setAttribute("data-pinyin", it.pinyin);
    cb.id = `print-ch-${i}`;
    lab.appendChild(cb);
    const span = document.createElement("span");
    span.className = "print-char-check-label";
    span.textContent = it.pinyin ? `${it.text}（${it.pinyin}）` : it.text;
    lab.appendChild(span);
    frag.appendChild(lab);
  }
  wrap.appendChild(frag);
  if (typeof window.updatePrintEstimate === "function") window.updatePrintEstimate();
}

function getCheckedPrintLessonItems() {
  /** @type {{ text: string, pinyin: string }[]} */
  const items = [];
  document
    .querySelectorAll("#print-char-checklist input[type=checkbox][data-text]:checked")
    .forEach((cb) => {
      items.push({
        text: cb.getAttribute("data-text") || "",
        pinyin: cb.getAttribute("data-pinyin") || "",
      });
    });
  return items;
}

function appendCheckedLessonToPrintInput() {
  const selected = getCheckedPrintLessonItems();
  if (!selected.length) {
    if (typeof window.setPrintFontStatus === "function") {
      window.setPrintFontStatus("请先勾选要加入的字词。");
    }
    return;
  }
  const ta = document.getElementById("print-input");
  if (!ta) return;
  const fragment = selected
    .map((it) => {
      const text = String(it.text || "").trim();
      if (!text) return "";
      const py = String(it.pinyin || "").trim();
      return py ? `${text}（${py}）` : text;
    })
    .filter(Boolean)
    .join(" ");
  const cur = ta.value.replace(/\s+$/, "");
  ta.value = cur ? `${cur} ${fragment}` : fragment;
  ta.dispatchEvent(new Event("input", { bubbles: true }));
  if (typeof window.updatePrintEstimate === "function") window.updatePrintEstimate();
  if (typeof window.setPrintFontStatus === "function") {
    window.setPrintFontStatus(`已加入 ${selected.length} 项，可继续勾选或编辑输入框。`);
  }
}

function refreshPrintLessonPanel() {
  const bookSel = document.getElementById("print-book");
  if (!bookSel) return;
  fillBookSelect("print-book");
  if (!bookSel.value && data()?.books?.[0]?.code) {
    bookSel.value = data().books[0].code;
  }
  fillTocSelect(bookSel.value, "print-toc");
  preferPrintTocWithContent();
  renderPrintLessonChecklist();
}

function bindPrintLessonControls() {
  const bookSel = document.getElementById("print-book");
  const tocSel = document.getElementById("print-toc");
  const kindSel = document.getElementById("print-kind");
  if (!bookSel || !tocSel) return;

  bookSel.addEventListener("change", () => {
    fillTocSelect(bookSel.value, "print-toc");
    preferPrintTocWithContent();
    renderPrintLessonChecklist();
  });
  tocSel.addEventListener("change", renderPrintLessonChecklist);
  kindSel?.addEventListener("change", () => {
    preferPrintTocWithContent();
    renderPrintLessonChecklist();
  });

  document.getElementById("print-select-all")?.addEventListener("click", () => {
    document
      .querySelectorAll("#print-char-checklist input[type=checkbox]")
      .forEach((cb) => {
        cb.checked = true;
      });
  });
  document.getElementById("print-select-none")?.addEventListener("click", () => {
    document
      .querySelectorAll("#print-char-checklist input[type=checkbox]")
      .forEach((cb) => {
        cb.checked = false;
      });
  });
  document.getElementById("print-append-input")?.addEventListener("click", appendCheckedLessonToPrintInput);
}

function renderLexicon() {
  const body = document.getElementById("lexicon-body");
  const bookSel = document.getElementById("lexicon-book");
  const kindSel = document.getElementById("lexicon-kind");
  if (!body || !bookSel || !kindSel) return;

  const d = data();
  const book = bookSel.value;
  const kind = kindSel.value;
  /** @type {unknown[]} */
  let rows = [];
  if (kind === "词语表") {
    rows = d.wordByBook?.[book]?.["词语表"] || [];
  } else {
    rows = d.charByBook?.[book]?.[kind] || [];
  }

  if (!rows.length) {
    body.replaceChildren();
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = `本册暂无「${kind}」数据，或该表在导出时为空。`;
    body.appendChild(p);
    return;
  }

  const frag = document.createDocumentFragment();
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    const lab = row.label || "";
    const wrap = document.createElement("section");
    wrap.className = "lex-block";

    const titleEl = document.createElement("span");
    titleEl.className = "lex-block-title";
    titleEl.textContent = lab || `行 ${(row.i ?? 0) + 1}`;
    wrap.appendChild(titleEl);

    const flow = document.createElement("div");
    flow.className =
      kind === "词语表" ? "lex-flow lex-flow--words" : "lex-flow lex-flow--chars";

    if (kind === "词语表") {
      const items =
        row.wordItems?.length > 0
          ? row.wordItems
          : (row.words || []).map((w) => ({ word: w, pinyin: "" }));
      for (const it of items) {
        const cell = document.createElement("span");
        cell.className = "lex-item";
        const py = (it.pinyin && String(it.pinyin).trim()) || "";
        if (py) {
          const pEl = document.createElement("span");
          pEl.className = "lex-item-py";
          pEl.textContent = py;
          cell.appendChild(pEl);
        }
        const wEl = document.createElement("span");
        wEl.className = "lex-item-han";
        wEl.textContent = it.word || "";
        cell.appendChild(wEl);
        flow.appendChild(cell);
      }
    } else {
      const items =
        row.charItems?.length > 0
          ? row.charItems
          : (row.chars || []).map((c) => ({ char: c, pinyin: "" }));
      for (const it of items) {
        const cell = document.createElement("span");
        cell.className = "lex-item";
        const py = (it.pinyin && String(it.pinyin).trim()) || "";
        if (py) {
          const pEl = document.createElement("span");
          pEl.className = "lex-item-py";
          pEl.textContent = py;
          cell.appendChild(pEl);
        }
        const cEl = document.createElement("span");
        cEl.className = "lex-item-han";
        cEl.textContent = it.char || "";
        cell.appendChild(cEl);
        flow.appendChild(cell);
      }
    }
    wrap.appendChild(flow);
    frag.appendChild(wrap);
  }
  body.replaceChildren(frag);
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
    opt.title = b.batch ? `${b.title || b.code}（${b.batch}）` : b.title || b.code;
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
  const useCiyu = document.getElementById("char-use-ciyu")?.checked;

  if (!useShizi && !useXiezi && !useCiyu) {
    showDataBanner("请至少勾选「识字」「写字」「词语」之一。");
    return;
  }

  const charKnownSet = charSetForLessonRange(range, { useShizi, useXiezi });
  const m = mode === "replace-unknown" ? "replace-unknown" : "replace-known";

  const result = useCiyu
    ? replaceWordThenChar(
        input,
        sortWordsLongestFirst(knownWordsInLessonRange(d, range)),
        charKnownSet,
        placeholder,
        m,
      )
    : replaceByKnownSet(input, charKnownSet, placeholder, m);

  const outEl = document.getElementById("char-output");
  if (outEl) outEl.value = result.text;

  const stats = document.getElementById("char-stats");
  if (stats) {
    stats.textContent = `汉字共 ${result.hanCount} 个；本次替换 ${result.replaced} 个；当前范围内所选来源去重后 ${result.knownSetSize} 字。`;
  }
  showDataBanner("");
}

function runSingleWordSearch(ctx, rawTarget, needle) {
  const WR = wordResultApi();
  if (!WR) return;
  const opts = readWordPickOptions();
  const indexes = indexesFor(ctx, opts.skipMono);
  if (!indexes) return;
  const { body, table } = bucketsForChar(indexes, needle, ctx, opts.perBucket);
  fillWordGrid(body, table);
  const picked = WR.pickWords({ body, table }, opts);
  const pickedEl = document.getElementById("word-picked");
  if (pickedEl) pickedEl.value = WR.formatPickedLine(needle, picked);
  lastSingleNeedle = needle;

  const chunkFor = indexes.chunkIndex.get(needle) || [];
  const tableFor = indexes.tableIndex.get(needle) || [];
  const uniqChunkWords = new Set(chunkFor.map((h) => h.w)).size;
  const uniqTableWords = new Set(tableFor.map((h) => h.w)).size;
  const usedNote =
    rawTarget.trim() !== needle && rawTarget.trim().length > 0 ? `（已用首字「${needle}」）` : "";
  const noBucket = !opts.include.last && !opts.include.near && !opts.include.other;
  const total = chunkFor.length + tableFor.length;
  if (total === 0) {
    setWordStatus(`所选范围内无匹配（可扩大目录范围，或取消「仅正文」）。${usedNote}`);
  } else {
    const bucketTip = noBucket ? "未勾选纳入分桶，选用为空。" : `选用 ${picked.length} 个。`;
    setWordStatus(
      `已在约 ${ctx.scanned} 个预分词中筛选：正文 ${chunkFor.length} 条（${uniqChunkWords} 个不同词），词语表 ${tableFor.length} 条（${uniqTableWords} 个不同词）。${bucketTip}${usedNote}`,
    );
  }
  showDataBanner("");
}

function runBatchWordSearch(ctx, chars) {
  const WR = wordResultApi();
  if (!WR) return;
  const opts = readWordPickOptions();
  const indexes = indexesFor(ctx, opts.skipMono);
  if (!indexes) return;
  const noBucket = !opts.include.last && !opts.include.near && !opts.include.other;
  let hitChars = 0;
  const blocks = chars.map((ch) => {
    const chunkFor = indexes.chunkIndex.get(ch) || [];
    const tableFor = indexes.tableIndex.get(ch) || [];
    if (chunkFor.length || tableFor.length) hitChars += 1;
    const { body, table } = bucketsForChar(indexes, ch, ctx, opts.perBucket);
    const notes = opts.withNotes ? bucketNotes(body, table) : [];
    if (opts.withNotes && !notes.length) notes.push("（无符合配置的词）");
    return {
      ch,
      picked: WR.pickWords({ body, table }, opts),
      notes,
    };
  });
  const out = document.getElementById("word-batch-output");
  if (out) out.value = WR.formatBatchText(blocks);
  const noteTip = opts.withNotes ? "参考行以 # 开头。" : "未附带分桶参考。";
  const bucketTip = noBucket ? "未勾选纳入分桶，选用为空。" : noteTip;
  setWordStatus(
    `共 ${chars.length} 个不重复的字，其中 ${hitChars} 个在范围内有词。选用已按配置填好，可直接改。${bucketTip}`,
  );
  showDataBanner("");
}

function runWordSearch() {
  if (!wordResultApi()) return;
  const batch = wordModeIsBatch();
  if (batch) {
    const chars = window.WordResult.hanCharsInOrder(document.getElementById("word-char")?.value || "");
    if (!chars.length) {
      showDataBanner("请输入至少一个汉字。");
      return;
    }
    const ctx = prepareWordQuery();
    if (!ctx) return;
    runBatchWordSearch(ctx, chars);
    return;
  }

  const rawTarget = document.getElementById("word-char")?.value || "";
  const needle = firstHanCharFromInput(rawTarget);
  if (!needle) {
    showDataBanner("请输入至少一个汉字（多字时只取第一个汉字参与检索）。");
    return;
  }
  const ctx = prepareWordQuery();
  if (!ctx) return;
  runSingleWordSearch(ctx, rawTarget, needle);
}

function init() {
  const r = rawData();
  if (!r || (!Array.isArray(r.books) && !Array.isArray(r.sets))) {
    showDataBanner(
      "未找到数据：请在项目根目录运行 python scripts/export_web_data.py，生成 web/generated/data.js 后刷新。",
    );
    setupTabs();
    return;
  }

  if (Array.isArray(r.sets) && r.sets.length) {
    activeSetId = r.defaultSetId || r.sets[0]?.id || null;
  }

  const d = data();
  if (!d || !Array.isArray(d.books) || d.books.length === 0) {
    showDataBanner(
      "当前教材套无可用分册数据。请确认已解析各批次并重新导出 data.js。",
    );
    setupTabs();
    fillSetSelect();
    document.getElementById("textbook-set")?.addEventListener("change", (e) => {
      activeSetId = e.target.value || null;
      applyActiveSet();
    });
    return;
  }

  if (!d.tocByBook || typeof d.tocByBook !== "object") {
    showDataBanner(
      "数据缺少 tocByBook（版本过旧）。请重新运行: python scripts/export_web_data.py",
    );
    setupTabs();
    return;
  }

  setupTabs();
  fillSetSelect();
  document.getElementById("textbook-set")?.addEventListener("change", (e) => {
    activeSetId = e.target.value || null;
    applyActiveSet();
  });
  bindBookTocPair("char-start");
  bindBookTocPair("char-end");
  bindBookTocPair("word-start");
  bindBookTocPair("word-end");
  bindPrintLessonControls();
  applyActiveSet();

  document.getElementById("char-run")?.addEventListener("click", runCharCheck);
  document.getElementById("word-run")?.addEventListener("click", runWordSearch);
  document.getElementById("lookup-run")?.addEventListener("click", runLookup);

  const lexBook = document.getElementById("lexicon-book");
  const lexKind = document.getElementById("lexicon-kind");
  lexBook?.addEventListener("change", renderLexicon);
  lexKind?.addEventListener("change", renderLexicon);
}

/**
 * 恢复打印页保存的册 / 课 / 表。不自动跳到「有内容的课」。
 * @param {{ book?: string, toc?: string, kind?: string }} sel
 */
function applyPrintLessonSelection(sel) {
  const bookSel = document.getElementById("print-book");
  const tocSel = document.getElementById("print-toc");
  const kindSel = document.getElementById("print-kind");
  if (!bookSel || !tocSel) return;
  if (sel?.book && [...bookSel.options].some((o) => o.value === sel.book)) {
    bookSel.value = sel.book;
  }
  fillTocSelect(bookSel.value, "print-toc");
  if (sel?.toc && [...tocSel.options].some((o) => o.value === sel.toc)) {
    tocSel.value = sel.toc;
  }
  if (kindSel && sel?.kind && [...kindSel.options].some((o) => o.value === sel.kind)) {
    kindSel.value = sel.kind;
  }
  renderPrintLessonChecklist();
}

/** 供打印书写纸模块读取当前成套视图（含 books / tocByBook / charByBook 等）。 */
window.getTextbookData = data;
window.refreshPrintLessonPanel = refreshPrintLessonPanel;
window.applyPrintLessonSelection = applyPrintLessonSelection;

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
  onEnter("lookup-input", runLookup);
}

init();
bindInputEnterShortcuts();
bootWordSettings();
