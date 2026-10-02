import {
  parsePrintInput,
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
import { attachLineNumbers, refreshLineNumbers } from "../line-numbers.js";

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
    fontChoice: document.getElementById("print-font")?.value || "kaiti",
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

async function onGeneratePdf() {
  const btn = document.getElementById("print-generate");
  if (btn) btn.disabled = true;
  try {
    const groups = collectGroups();
    if (!groups.length || !groups.some((g) => g.items.length)) {
      setFontStatus("请先加入或输入字词。");
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

  if (typeof window.refreshPrintLessonPanel === "function") {
    window.refreshPrintLessonPanel();
  }

  document.getElementById("print-input")?.addEventListener("input", onPrintInputEdit);

  [
    "print-paper",
    "print-grid",
    "print-cell-size",
    "print-char-fill",
    "print-model-count",
    "print-trace-count",
    "print-blank-count",
    "print-show-pinyin",
    "print-row-gap",
    "print-group-gap",
    "print-margin-top",
    "print-margin-bottom",
    "print-margin-left",
    "print-margin-right",
    "print-overflow-mm",
  ].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", updateEstimate);
    document.getElementById(id)?.addEventListener("change", updateEstimate);
  });
  document.querySelectorAll('input[name="print-flow"]').forEach((el) => {
    el.addEventListener("change", () => {
      syncSpaceDisplayForFlow();
      updateEstimate();
    });
  });
  document.querySelectorAll('input[name="print-direction"]').forEach((el) => {
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

  updateFontFileWrap();
  setFontStatus(initialFontStatus(document.getElementById("print-font")?.value || "kaiti"));
  bootLineNumbers();
  syncSpaceDisplayForFlow();
  updateEstimate();

  const sizeSlider = document.getElementById("print-cell-size");
  const sizeReadout = document.getElementById("print-cell-size-val");
  const syncSizeReadout = () => {
    if (sizeReadout && sizeSlider) sizeReadout.textContent = sizeSlider.value;
  };
  sizeSlider?.addEventListener("input", syncSizeReadout);
  syncSizeReadout();

  const overflowSlider = document.getElementById("print-overflow-mm");
  const overflowReadout = document.getElementById("print-overflow-mm-val");
  const syncOverflowReadout = () => {
    if (overflowReadout && overflowSlider) {
      overflowReadout.textContent = overflowSlider.value;
    }
  };
  overflowSlider?.addEventListener("input", syncOverflowReadout);
  syncOverflowReadout();
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
