import {
  parsePrintInput,
  estimateStats,
} from "./input.js";
import {
  supportsLocalFonts,
  setManualFontFile,
  setManualPinyinFontFile,
  initialFontStatus,
  formatFontReport,
} from "./fonts.js";
import { generatePracticePdf, estimatePageCount } from "./pdf.js";
import { attachLineNumbers, refreshLineNumbers } from "../line-numbers.js";
import { PRINT_DEFAULTS, loadPrintSettings, savePrintSettings } from "./settings.js";

/** 与 app.js 成套视图对齐；无桥接时退回顶层 data.js。 */
function data() {
  if (typeof window.getTextbookData === "function") {
    return window.getTextbookData();
  }
  return window.TEXTBOOK_WEB_DATA;
}

function setFontStatus(msg) {
  const el = document.getElementById("print-font-status");
  if (el) el.textContent = msg;
}

window.setPrintFontStatus = setFontStatus;

function currentFlow() {
  return (
    document.querySelector('input[name="print-flow"]:checked')?.value || "group"
  );
}

function collectGroups() {
  const raw = document.getElementById("print-input")?.value || "";
  return parsePrintInput(raw, { spacesAsCells: currentFlow() === "group-line" });
}

/** 输入排版：空格的可见占位符（□ U+25A1；楷体等中文字体普遍有字形，␣ 常缺字） */
const SPACE_DISPLAY = "□";

/** 输入排版：把普通空格显示为「□」，便于看见占格位置 */
function revealSpacesInInput() {
  const ta = document.getElementById("print-input");
  if (!ta) return;
  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  const next = ta.value
    .replace(/ /g, SPACE_DISPLAY)
    .replace(/\u00a0/g, SPACE_DISPLAY)
    .replace(/\u3000/g, SPACE_DISPLAY)
    // 旧版开框符 ␣ 一并归一，避免混用
    .replace(/␣/g, SPACE_DISPLAY);
  if (next !== ta.value) {
    ta.value = next;
    if (typeof start === "number") {
      ta.setSelectionRange(start, end);
    }
  }
  refreshLineNumbers(ta);
}

/** 离开输入排版：把占位符还原为空格，供其他版式按空格分组 */
function concealSpacesInInput() {
  const ta = document.getElementById("print-input");
  if (!ta) return;
  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  const next = ta.value.replace(/[□␣]/g, " ");
  if (next !== ta.value) {
    ta.value = next;
    if (typeof start === "number") {
      ta.setSelectionRange(start, end);
    }
  }
  refreshLineNumbers(ta);
}

function syncSpaceDisplayForFlow() {
  const ta = document.getElementById("print-input");
  const hint = document.getElementById("print-space-hint");
  const isGroupLine = currentFlow() === "group-line";
  if (isGroupLine) {
    revealSpacesInInput();
    ta?.classList.add("print-input-show-spaces");
    if (hint) hint.hidden = false;
  } else {
    concealSpacesInInput();
    ta?.classList.remove("print-input-show-spaces");
    if (hint) hint.hidden = true;
  }
}

function onPrintInputEdit() {
  if (currentFlow() === "group-line") {
    revealSpacesInInput();
  }
  updateEstimate();
}

function readConfig() {
  const layoutMode = currentFlow();
  const writeDirection =
    document.querySelector('input[name="print-direction"]:checked')?.value || "horizontal";
  const num = (id, fallback) => {
    const v = parseFloat(document.getElementById(id)?.value ?? "");
    return Number.isFinite(v) ? v : fallback;
  };
  return {
    paperSize: document.getElementById("print-paper")?.value || "a4-portrait",
    fontChoice: document.getElementById("print-font")?.value || "auto",
    pinyinFontChoice: document.getElementById("print-pinyin-font")?.value || "auto",
    gridType: document.getElementById("print-grid")?.value || "tian",
    cellSizeCm: num("print-cell-size", 1.5),
    charFillRatio: num("print-char-fill", 0.85),
    modelCount: parseInt(document.getElementById("print-model-count")?.value || "1", 10),
    traceCount: parseInt(document.getElementById("print-trace-count")?.value || "2", 10),
    blankCount: parseInt(document.getElementById("print-blank-count")?.value || "2", 10),
    traceColorHex: document.getElementById("print-trace-color")?.value || "#CC0000",
    traceOpacity: num("print-trace-opacity", 0.7),
    showPinyin: document.getElementById("print-show-pinyin")?.checked !== false,
    layoutMode,
    writeDirection,
    rowGapMm: num("print-row-gap", 0),
    groupGapMm: num("print-group-gap", 2),
    marginTopMm: num("print-margin-top", 15),
    marginBottomMm: num("print-margin-bottom", 15),
    marginLeftMm: num("print-margin-left", 15),
    marginRightMm: num("print-margin-right", 15),
    overflowMm: num("print-overflow-mm", 5),
  };
}

function updateEstimate() {
  const el = document.getElementById("print-estimate");
  if (!el) return;
  const groups = collectGroups();
  const cfg = readConfig();
  const { charCount, cellCount } = estimateStats(groups, cfg);
  if (!charCount) {
    el.textContent = "尚未输入字词。";
    return;
  }
  const pages = estimatePageCount(groups, cfg);
  el.textContent = `约 ${groups.length} 组 · ${charCount} 字 · ${cellCount} 格 · ${pages} 页`;
}

window.updatePrintEstimate = updateEstimate;

function updateFontFileWrap() {
  const details = document.getElementById("print-font-file-details");
  if (!details) return;
  if (!supportsLocalFonts()) {
    details.open = true;
  }
}

function pdfFileName() {
  return `字词练习_${formatLocalDate(new Date())}.pdf`;
}

function setGenerating(on) {
  generating = on;
  for (const id of ["print-generate", "print-preview-btn"]) {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = on;
  }
}

function explainFontError(err) {
  const code = err?.message || "";
  if (code === "NO_LOCAL_FONT_API") {
    return "当前浏览器不能读取系统字体。请用 Chrome / Edge，或指定字体文件。";
  }
  if (code === "FONT_PERMISSION_DENIED") {
    return "未允许访问本机字体。请在浏览器提示中点允许；若之前拒绝过，可在地址栏的网站设置里重新允许，或指定字体文件。";
  }
  if (code === "FONT_NOT_FOUND") {
    return "本机没有可用的范字字体。请安装楷体，或指定一个 .ttf 文件。";
  }
  if (code === "FONT_EMBED_FAILED") {
    return "指定的字体文件无法嵌入，请换用 .ttf。";
  }
  if (code === "FONTKIT_MISSING") return "字体组件未加载，请刷新页面。";
  if (code === "EMPTY_CONTENT") return "内容为空。";
  return "生成失败，请检查字词与字体。";
}

/** @returns {Promise<{ blob: Blob, cfg: object, fontReport: object } | null>} */
async function createPracticePdf() {
  const groups = collectGroups();
  if (!groups.length || !groups.some((g) => g.items.length)) {
    setFontStatus("请先加入或输入字词。");
    return null;
  }
  const cfg = readConfig();
  setFontStatus("正在加载字体…");
  const { blob, fontReport } = await generatePracticePdf(groups, cfg);
  return { blob, cfg, fontReport };
}

function downloadBlob(blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = pdfFileName();
  a.click();
  URL.revokeObjectURL(url);
}

let previewBlobUrl = "";
let generating = false;

function showPreview(blob) {
  const frame = document.getElementById("print-preview-frame");
  const overlay = document.getElementById("print-preview");
  const tab = document.getElementById("print-preview-tab");
  if (frame) frame.src = "about:blank";
  if (previewBlobUrl) URL.revokeObjectURL(previewBlobUrl);
  previewBlobUrl = URL.createObjectURL(blob);
  if (frame) frame.src = previewBlobUrl;
  if (tab) tab.href = previewBlobUrl;
  const meta = document.getElementById("print-preview-meta");
  if (meta) meta.textContent = document.getElementById("print-estimate")?.textContent || "";
  overlay?.classList.remove("hidden");
  document.body.classList.add("print-preview-open");
  document.getElementById("print-preview-close")?.focus();
}

function hidePreview() {
  document.getElementById("print-preview")?.classList.add("hidden");
  document.body.classList.remove("print-preview-open");
  const frame = document.getElementById("print-preview-frame");
  if (frame) frame.src = "about:blank";
  document.getElementById("print-preview-btn")?.focus();
}

function downloadPreview() {
  if (!previewBlobUrl) return;
  const a = document.createElement("a");
  a.href = previewBlobUrl;
  a.download = pdfFileName();
  a.click();
}

async function onPreview() {
  if (generating) return;
  setGenerating(true);
  try {
    const result = await createPracticePdf();
    if (!result) return;
    showPreview(result.blob);
    setFontStatus(`已在本页打开预览。${formatFontReport(result.fontReport)}。若画面空白，可用「在新标签页打开」。`);
  } catch (err) {
    console.error(err);
    setFontStatus(explainFontError(err));
  } finally {
    setGenerating(false);
  }
}

async function onGeneratePdf() {
  if (generating) return;
  setGenerating(true);
  try {
    const result = await createPracticePdf();
    if (!result) return;
    downloadBlob(result.blob);
    setFontStatus(formatFontReport(result.fontReport));
  } catch (err) {
    console.error(err);
    setFontStatus(explainFontError(err));
  } finally {
    setGenerating(false);
  }
}

function setSelectValue(id, value) {
  const el = document.getElementById(id);
  if (!el || value == null || value === "") return;
  const want = String(value);
  if ([...el.options].some((o) => o.value === want)) el.value = want;
}

function setNumberValue(id, value) {
  const el = document.getElementById(id);
  if (!el || value == null || value === "") return;
  const n = Number(value);
  if (!Number.isFinite(n)) return;
  el.value = String(n);
}

function setCheckedValue(id, value) {
  const el = document.getElementById(id);
  if (el && typeof value === "boolean") el.checked = value;
}

function setRadioValue(name, value) {
  if (value == null || value === "") return;
  const el = document.querySelector(`input[name="${name}"][value="${CSS.escape(String(value))}"]`);
  if (el) el.checked = true;
}

function applyPrintControls(s) {
  if (!s) return;
  setSelectValue("print-paper", s.paperSize);
  setSelectValue("print-grid", s.gridType);
  setSelectValue("print-font", s.fontChoice);
  setSelectValue("print-pinyin-font", s.pinyinFontChoice);
  setSelectValue("print-model-count", s.modelCount);
  setSelectValue("print-trace-count", s.traceCount);
  setSelectValue("print-blank-count", s.blankCount);
  setNumberValue("print-cell-size", s.cellSizeCm);
  setNumberValue("print-char-fill", s.charFillRatio);
  setNumberValue("print-trace-opacity", s.traceOpacity);
  setNumberValue("print-row-gap", s.rowGapMm);
  setNumberValue("print-group-gap", s.groupGapMm);
  setNumberValue("print-margin-top", s.marginTopMm);
  setNumberValue("print-margin-bottom", s.marginBottomMm);
  setNumberValue("print-margin-left", s.marginLeftMm);
  setNumberValue("print-margin-right", s.marginRightMm);
  setNumberValue("print-overflow-mm", s.overflowMm);
  if (typeof s.traceColorHex === "string" && /^#[0-9a-fA-F]{6}$/.test(s.traceColorHex)) {
    const color = document.getElementById("print-trace-color");
    if (color) color.value = s.traceColorHex;
  }
  setCheckedValue("print-show-pinyin", s.showPinyin);
  setRadioValue("print-flow", s.layoutMode);
  setRadioValue("print-direction", s.writeDirection);
}

function collectPrintSettings() {
  return {
    ...readConfig(),
    book: document.getElementById("print-book")?.value || "",
    toc: document.getElementById("print-toc")?.value || "",
    kind: document.getElementById("print-kind")?.value || "",
  };
}

function persistPrintSettings() {
  savePrintSettings(collectPrintSettings());
}

function syncPrintReadouts() {
  const sizeSlider = document.getElementById("print-cell-size");
  const sizeReadout = document.getElementById("print-cell-size-val");
  if (sizeSlider && sizeReadout) sizeReadout.textContent = sizeSlider.value;
  const overflowSlider = document.getElementById("print-overflow-mm");
  const overflowReadout = document.getElementById("print-overflow-mm-val");
  if (overflowSlider && overflowReadout) overflowReadout.textContent = overflowSlider.value;
}

function onPrintOptionChanged() {
  syncPrintReadouts();
  persistPrintSettings();
  updateEstimate();
}

function applySavedPrintSettings() {
  const saved = loadPrintSettings();
  if (!saved) return;
  applyPrintControls(saved);
  if (typeof window.applyPrintLessonSelection === "function") {
    window.applyPrintLessonSelection({
      book: saved.book,
      toc: saved.toc,
      kind: saved.kind,
    });
  }
  syncSpaceDisplayForFlow();
  syncPrintReadouts();
}

function resetPrintSettings() {
  applyPrintControls(PRINT_DEFAULTS);
  syncSpaceDisplayForFlow();
  syncPrintReadouts();
  persistPrintSettings();
  updateEstimate();
  setFontStatus("已恢复默认版式。");
}

function formatLocalDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

let printSheetInitialized = false;

export function initPrintSheet() {
  if (printSheetInitialized) {
    updateEstimate();
    return;
  }
  printSheetInitialized = true;

  if (data()?.books?.length && typeof window.refreshPrintLessonPanel === "function") {
    window.refreshPrintLessonPanel();
  }

  document.getElementById("print-input")?.addEventListener("input", onPrintInputEdit);

  const options = document.querySelector(".print-options");
  options?.addEventListener("input", onPrintOptionChanged);
  options?.addEventListener("change", (e) => {
    if (e.target instanceof Element && e.target.getAttribute("name") === "print-flow") {
      syncSpaceDisplayForFlow();
    }
    onPrintOptionChanged();
  });
  for (const id of ["print-book", "print-toc", "print-kind"]) {
    document.getElementById(id)?.addEventListener("change", persistPrintSettings);
  }
  document.querySelectorAll("[data-print-size]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const val = btn.getAttribute("data-print-size");
      const slider = document.getElementById("print-cell-size");
      if (slider && val) {
        slider.value = val;
        onPrintOptionChanged();
      }
    });
  });

  const refreshFontPlan = () => {
    setFontStatus(
      initialFontStatus(
        document.getElementById("print-font")?.value || "auto",
        document.getElementById("print-pinyin-font")?.value || "auto",
      ),
    );
  };
  document.getElementById("print-font")?.addEventListener("change", refreshFontPlan);
  document.getElementById("print-pinyin-font")?.addEventListener("change", refreshFontPlan);

  document.getElementById("print-font-file")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await setManualFontFile(file);
    setFontStatus(`已指定范字文件：${file.name}（仅本次浏览有效）`);
  });
  document.getElementById("print-pinyin-file")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await setManualPinyinFontFile(file);
    setFontStatus(`已指定拼音文件：${file.name}（仅本次浏览有效）`);
  });

  document.getElementById("print-generate")?.addEventListener("click", onGeneratePdf);
  document.getElementById("print-preview-btn")?.addEventListener("click", onPreview);
  document.getElementById("print-reset")?.addEventListener("click", resetPrintSettings);
  document.getElementById("print-preview-close")?.addEventListener("click", hidePreview);
  document.getElementById("print-preview-download")?.addEventListener("click", downloadPreview);
  document.getElementById("print-preview-tab")?.addEventListener("click", (e) => {
    if (!previewBlobUrl) e.preventDefault();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const overlay = document.getElementById("print-preview");
    if (!overlay || overlay.classList.contains("hidden")) return;
    hidePreview();
  });

  applySavedPrintSettings();
  updateFontFileWrap();
  setFontStatus(
    initialFontStatus(
      document.getElementById("print-font")?.value || "auto",
      document.getElementById("print-pinyin-font")?.value || "auto",
    ),
  );
  bootLineNumbers();
  updateEstimate();
}

window.initPrintSheet = initPrintSheet;

function bootLineNumbers() {
  attachLineNumbers(document.getElementById("print-input"));
  attachLineNumbers(document.getElementById("char-input"));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    bootLineNumbers();
    initPrintSheet();
  });
} else {
  bootLineNumbers();
  initPrintSheet();
}
