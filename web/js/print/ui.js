import {
  parseManualInput,
  loadLessonCharItems,
  itemsToSingleGroup,
  estimateStats,
} from "./input.js";
import {
  FONT_PRESETS,
  supportsLocalFonts,
  setManualFontFile,
  getManualFontMeta,
  initialFontStatus,
  resolveFontBytes,
} from "./fonts.js";
import { generatePracticePdf, estimatePageCount } from "./pdf.js";

function data() {
  return window.TEXTBOOK_WEB_DATA;
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
  if (cur && [...sel.options].some((o) => o.value === cur)) sel.value = cur;
}

function bindBookToc(bookId, tocId) {
  const bookSel = document.getElementById(bookId);
  if (!bookSel) return;
  const sync = () => fillTocSelect(bookSel.value, tocId);
  bookSel.addEventListener("change", sync);
  sync();
}

function setFontStatus(msg) {
  const el = document.getElementById("print-font-status");
  if (el) el.textContent = msg;
}

function getInputMode() {
  return document.querySelector('input[name="print-input-mode"]:checked')?.value || "lesson";
}

function getSelectedLessonItems() {
  const wrap = document.getElementById("print-char-checklist");
  if (!wrap) return [];
  /** @type {import('./input.js').CharItem[]} */
  const items = [];
  wrap.querySelectorAll('input[type="checkbox"][data-char]:checked').forEach((cb) => {
    items.push({
      char: cb.getAttribute("data-char") || "",
      pinyin: cb.getAttribute("data-pinyin") || "",
    });
  });
  return items;
}

function renderLessonChecklist() {
  const wrap = document.getElementById("print-char-checklist");
  if (!wrap) return;
  const d = data();
  const book = document.getElementById("print-book")?.value;
  const tocId = document.getElementById("print-toc")?.value;
  const kind = document.getElementById("print-kind")?.value || "写字表";
  const items = loadLessonCharItems(d, book, tocId, kind);

  wrap.replaceChildren();
  if (!items.length) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "本课暂无字词，请换课次或表类型。";
    wrap.appendChild(p);
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
    cb.setAttribute("data-char", it.char);
    cb.setAttribute("data-pinyin", it.pinyin);
    cb.id = `print-ch-${i}`;
    lab.appendChild(cb);
    const span = document.createElement("span");
    span.className = "print-char-check-label";
    span.textContent = it.pinyin ? `${it.char}（${it.pinyin}）` : it.char;
    lab.appendChild(span);
    frag.appendChild(lab);
  }
  wrap.appendChild(frag);
  updateEstimate();
}

function collectGroups() {
  if (getInputMode() === "manual") {
    const hanzi = document.getElementById("print-manual-hanzi")?.value || "";
    const pinyin = document.getElementById("print-manual-pinyin")?.value || "";
    return parseManualInput(hanzi, pinyin);
  }
  return itemsToSingleGroup(getSelectedLessonItems());
}

function readConfig() {
  const layoutMode =
    document.querySelector('input[name="print-layout"]:checked')?.value || "continuous";
  return {
    fontChoice: document.getElementById("print-font")?.value || "kaiti",
    gridType: document.getElementById("print-grid")?.value || "mi",
    cellSizeCm: parseFloat(document.getElementById("print-cell-size")?.value || "1.2"),
    modelCount: parseInt(document.getElementById("print-model-count")?.value || "1", 10),
    traceCount: parseInt(document.getElementById("print-trace-count")?.value || "2", 10),
    blankCount: parseInt(document.getElementById("print-blank-count")?.value || "2", 10),
    traceColorHex: document.getElementById("print-trace-color")?.value || "#CC0000",
    traceOpacity: parseFloat(document.getElementById("print-trace-opacity")?.value || "0.7"),
    showPinyin: document.getElementById("print-show-pinyin")?.checked !== false,
    layoutMode,
    rowGapMm: parseFloat(document.getElementById("print-row-gap")?.value || "4"),
    groupGapMm: parseFloat(document.getElementById("print-group-gap")?.value || "10"),
  };
}

function updateEstimate() {
  const el = document.getElementById("print-estimate");
  if (!el) return;
  const groups = collectGroups();
  const cfg = readConfig();
  const { charCount, cellCount } = estimateStats(groups, cfg);
  if (!charCount) {
    el.textContent = "尚未选择字词。";
    return;
  }
  const pages = estimatePageCount(groups, cfg);
  el.textContent = `约 ${charCount} 字 · ${cellCount} 格 · ${pages} 页`;
}

function toggleInputPanels() {
  const mode = getInputMode();
  document.getElementById("print-panel-lesson")?.classList.toggle("hidden", mode !== "lesson");
  document.getElementById("print-panel-manual")?.classList.toggle("hidden", mode !== "manual");
  updateEstimate();
}

function updateFontFileWrap() {
  const details = document.getElementById("print-font-file-details");
  if (!details) return;
  if (!supportsLocalFonts()) {
    details.open = true;
  }
}

async function onGeneratePdf() {
  const btn = document.getElementById("print-generate");
  if (btn) btn.disabled = true;
  try {
    const groups = collectGroups();
    if (!groups.length || !groups.some((g) => g.items.length)) {
      setFontStatus("请先选择或输入字词。");
      return;
    }

    const cfg = readConfig();
    setFontStatus("正在加载字体…");

    try {
      const resolved = await resolveFontBytes(cfg.fontChoice);
      if (resolved.source === "system") {
        setFontStatus(`已就绪：${resolved.label}（系统）`);
      } else {
        setFontStatus(`已指定字体文件：${resolved.label}`);
      }
    } catch (err) {
      const code = err?.message || "";
      if (code === "NO_LOCAL_FONT_API") {
        setFontStatus("请指定楷体 .ttf 文件，或改用 Chrome / Edge。");
        return;
      }
      if (code === "FONT_PERMISSION_DENIED") {
        setFontStatus("未获字体访问权限，请指定字体文件后重试。");
        return;
      }
      if (code === "FONT_NOT_FOUND") {
        const preset = FONT_PRESETS[cfg.fontChoice];
        setFontStatus(`未找到「${preset?.label || cfg.fontChoice}」，请指定字体文件或换选其他字体。`);
        return;
      }
      setFontStatus("字体加载失败，请换用 .ttf 格式重试。");
      return;
    }

    setFontStatus("正在生成 PDF…");
    const blob = await generatePracticePdf(groups, cfg);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `字词练习_${formatLocalDate(new Date())}.pdf`;
    a.click();
    URL.revokeObjectURL(url);

    const manual = getManualFontMeta();
    if (manual) setFontStatus(`已指定字体文件：${manual.name}`);
    else {
      const msg = initialFontStatus(cfg.fontChoice);
      setFontStatus(msg.startsWith("将尝试") ? msg.replace("将尝试读取", "已就绪：") : msg);
    }
  } catch (err) {
    console.error(err);
    setFontStatus(err?.message === "EMPTY_CONTENT" ? "内容为空。" : "生成失败，请检查字词与字体。");
  } finally {
    if (btn) btn.disabled = false;
  }
}

function formatLocalDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

let printSheetInitialized = false;

export function initPrintSheet() {
  const d = data();
  if (!d?.books?.length) return;
  if (printSheetInitialized) {
    updateEstimate();
    return;
  }
  printSheetInitialized = true;

  fillBookSelect("print-book");
  bindBookToc("print-book", "print-toc");

  const firstBook = d.books[0]?.code;
  if (firstBook) {
    const bookSel = document.getElementById("print-book");
    if (bookSel) bookSel.value = firstBook;
    fillTocSelect(firstBook, "print-toc");
  }

  document.getElementById("print-book")?.addEventListener("change", renderLessonChecklist);
  document.getElementById("print-toc")?.addEventListener("change", renderLessonChecklist);
  document.getElementById("print-kind")?.addEventListener("change", renderLessonChecklist);

  document.querySelectorAll('input[name="print-input-mode"]').forEach((el) => {
    el.addEventListener("change", toggleInputPanels);
  });

  document.getElementById("print-select-all")?.addEventListener("click", () => {
    document
      .querySelectorAll("#print-char-checklist input[type=checkbox]")
      .forEach((cb) => {
        cb.checked = true;
      });
    updateEstimate();
  });
  document.getElementById("print-select-none")?.addEventListener("click", () => {
    document
      .querySelectorAll("#print-char-checklist input[type=checkbox]")
      .forEach((cb) => {
        cb.checked = false;
      });
    updateEstimate();
  });

  document.getElementById("print-char-checklist")?.addEventListener("change", updateEstimate);
  document.getElementById("print-manual-hanzi")?.addEventListener("input", updateEstimate);
  document.getElementById("print-manual-pinyin")?.addEventListener("input", updateEstimate);

  [
    "print-grid",
    "print-cell-size",
    "print-model-count",
    "print-trace-count",
    "print-blank-count",
    "print-show-pinyin",
    "print-row-gap",
    "print-group-gap",
  ].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", updateEstimate);
    document.getElementById(id)?.addEventListener("change", updateEstimate);
  });
  document.querySelectorAll('input[name="print-layout"]').forEach((el) => {
    el.addEventListener("change", updateEstimate);
  });

  document.querySelectorAll("[data-print-size]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const val = btn.getAttribute("data-print-size");
      const slider = document.getElementById("print-cell-size");
      const sizeReadout = document.getElementById("print-cell-size-val");
      if (slider && val) {
        slider.value = val;
        if (sizeReadout) sizeReadout.textContent = val;
        updateEstimate();
      }
    });
  });

  document.getElementById("print-font")?.addEventListener("change", () => {
    const choice = document.getElementById("print-font")?.value || "kaiti";
    setFontStatus(initialFontStatus(choice));
  });

  document.getElementById("print-font-file")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await setManualFontFile(file);
    setFontStatus(`已指定字体文件：${file.name}`);
  });

  document.getElementById("print-generate")?.addEventListener("click", onGeneratePdf);

  renderLessonChecklist();
  toggleInputPanels();
  updateFontFileWrap();
  setFontStatus(initialFontStatus(document.getElementById("print-font")?.value || "kaiti"));

  const sizeSlider = document.getElementById("print-cell-size");
  const sizeReadout = document.getElementById("print-cell-size-val");
  const syncSizeReadout = () => {
    if (sizeReadout && sizeSlider) sizeReadout.textContent = sizeSlider.value;
  };
  sizeSlider?.addEventListener("input", syncSizeReadout);
  syncSizeReadout();
}

window.initPrintSheet = initPrintSheet;
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => initPrintSheet());
} else {
  initPrintSheet();
}
