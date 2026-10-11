/** 打印书写纸的版式选项。只存可序列化的设置，不含输入正文和字体文件。 */

const PRINT_SETTINGS_KEY = "textbook-parser.print-settings.v1";

/** 与页面控件的初始值一致，供「恢复默认」使用。 */
export const PRINT_DEFAULTS = {
  paperSize: "a4-portrait",
  fontChoice: "auto",
  pinyinFontChoice: "auto",
  gridType: "tian",
  cellSizeCm: 1.5,
  charFillRatio: 0.85,
  modelCount: 1,
  traceCount: 2,
  blankCount: 2,
  traceColorHex: "#cc0000",
  traceOpacity: 0.7,
  showPinyin: true,
  layoutMode: "group",
  writeDirection: "horizontal",
  rowGapMm: 0,
  groupGapMm: 2,
  marginTopMm: 15,
  marginBottomMm: 15,
  marginLeftMm: 15,
  marginRightMm: 15,
  overflowMm: 5,
};

export function loadPrintSettings() {
  try {
    const raw = localStorage.getItem(PRINT_SETTINGS_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    return data;
  } catch {
    return null;
  }
}

export function savePrintSettings(data) {
  try {
    localStorage.setItem(PRINT_SETTINGS_KEY, JSON.stringify(data));
  } catch {
    // 隐私模式或存储配额不足时静默跳过，不影响生成。
  }
}
