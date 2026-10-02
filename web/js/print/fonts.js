/** @typedef {'kaiti_gb2312'|'kaiti'|'stkaiti'} FontChoice */

/** @type {Record<FontChoice, { label: string, cssFamily: string, postscriptNames: string[] }>} */
export const FONT_PRESETS = {
  kaiti_gb2312: {
    label: "楷体_GB2312",
    cssFamily: '"楷体_GB2312", "KaiTi_GB2312", "楷体", "KaiTi", serif',
    postscriptNames: ["KaiTi_GB2312", "KaiTi", "SimKai"],
  },
  kaiti: {
    label: "楷体",
    cssFamily: '"楷体", "KaiTi", "SimKai", serif',
    postscriptNames: ["KaiTi", "SimKai", "KaiTi_GB2312"],
  },
  stkaiti: {
    label: "华文楷体",
    cssFamily: '"华文楷体", "STKaiti", "STXihei", serif',
    postscriptNames: ["STKaiti", "STXihei"],
  },
};

/** 拼音固定字号（pt） */
export const PINYIN_FONT_SIZE_PT = 10.5;

/** 拼音基线相对字框上沿的间距（pt），需留出降部以免压格线 */
export const PINYIN_GAP_FROM_CELL_PT = 5;

/**
 * 拼音字体优先级（按 family / fullName / style 模糊匹配）。
 * @type {{ label: string, match: (f: { family?: string, fullName?: string, postscriptName?: string, style?: string }) => boolean }[]}
 */
export const PINYIN_FONT_PREFS = [
  {
    label: "Wukong Pinyin Sans ExtraLight",
    match: (f) => {
      const blob = normFontBlob(f);
      return blob.includes("wukong") && blob.includes("pinyin") && blob.includes("extralight");
    },
  },
  {
    label: "Noto Sans Light",
    match: (f) => {
      const family = (f.family || "").toLowerCase().replace(/\s+/g, "");
      const style = (f.style || "").toLowerCase().replace(/\s+/g, "");
      const full = (f.fullName || "").toLowerCase().replace(/\s+/g, "");
      const ps = (f.postscriptName || "").toLowerCase().replace(/\s+/g, "");
      if (family === "notosanslight" || full.includes("notosanslight")) return true;
      if (family === "notosans" && (style === "light" || full.includes("light") || ps.includes("light"))) {
        return !full.includes("extralight") && !style.includes("extralight");
      }
      return false;
    },
  },
  {
    label: "Noto Sans",
    match: (f) => {
      const family = (f.family || "").toLowerCase().replace(/\s+/g, "");
      const style = (f.style || "").toLowerCase().replace(/\s+/g, "");
      const full = (f.fullName || "").toLowerCase().replace(/\s+/g, "");
      const ps = (f.postscriptName || "").toLowerCase().replace(/\s+/g, "");
      if (family !== "notosans") return false;
      if (style.includes("light") || full.includes("light") || ps.includes("light")) return false;
      if (style.includes("bold") || style.includes("black") || style.includes("medium")) return false;
      return !style || style === "regular" || style === "roman" || full.endsWith("regular") || ps.endsWith("regular");
    },
  },
];

/** @type {Map<string, ArrayBuffer>} */
const cache = new Map();

/** @type {{ name: string, buffer: ArrayBuffer } | null} */
let manualFont = null;

/** @param {{ family?: string, fullName?: string, postscriptName?: string, style?: string }} f */
function normFontBlob(f) {
  return [f.family, f.fullName, f.postscriptName, f.style]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
    .replace(/[\s_-]+/g, "");
}

export function supportsLocalFonts() {
  return typeof window !== "undefined" && "queryLocalFonts" in window;
}

export function setManualFontFile(file) {
  if (!file) {
    manualFont = null;
    return Promise.resolve(null);
  }
  return file.arrayBuffer().then((buffer) => {
    manualFont = { name: file.name, buffer };
    cache.set(`manual:${file.name}`, buffer);
    return manualFont;
  });
}

export function getManualFontMeta() {
  return manualFont ? { name: manualFont.name } : null;
}

/**
 * @param {FontChoice} choice
 * @returns {Promise<{ buffer: ArrayBuffer, source: string, label: string }>}
 */
export async function resolveFontBytes(choice) {
  const preset = FONT_PRESETS[choice] || FONT_PRESETS.kaiti;
  const cacheKey = `preset:${choice}`;

  if (manualFont?.buffer) {
    return { buffer: manualFont.buffer, source: "manual", label: manualFont.name };
  }

  if (cache.has(cacheKey)) {
    return { buffer: cache.get(cacheKey), source: "system", label: preset.label };
  }

  if (!supportsLocalFonts()) {
    throw new Error("NO_LOCAL_FONT_API");
  }

  let fonts;
  try {
    fonts = await window.queryLocalFonts({ postscriptNames: preset.postscriptNames });
  } catch (err) {
    if (err?.name === "NotAllowedError" || err?.name === "SecurityError") {
      throw new Error("FONT_PERMISSION_DENIED");
    }
    throw err;
  }

  /** @type {FontData | undefined} */
  let hit = fonts.find((f) => preset.postscriptNames.includes(f.postscriptName));
  if (!hit) {
    hit = fonts.find((f) =>
      preset.postscriptNames.some(
        (n) => f.family?.includes(n) || f.fullName?.includes(n) || f.postscriptName?.includes(n),
      ),
    );
  }
  if (!hit) {
    const all = await window.queryLocalFonts();
    const lower = preset.label.replace(/_/g, "");
    hit = all.find(
      (f) =>
        f.fullName?.includes(preset.label) ||
        f.family?.includes(preset.label) ||
        f.fullName?.replace(/\s/g, "").includes(lower),
    );
  }

  if (!hit) throw new Error("FONT_NOT_FOUND");

  const blob = await hit.blob();
  const buffer = await blob.arrayBuffer();
  cache.set(cacheKey, buffer);
  return { buffer, source: "system", label: preset.label };
}

/**
 * 按优先级解析拼音字体；找不到则返回 null（调用方应改用汉字字体，勿用 Helvetica）。
 * @returns {Promise<{ buffer: ArrayBuffer, label: string } | null>}
 */
export async function resolvePinyinFontBytes() {
  const cacheKey = "pinyin:preferred";
  if (cache.has(cacheKey)) {
    const meta = cache.get(`${cacheKey}:label`);
    return {
      buffer: cache.get(cacheKey),
      label: typeof meta === "string" ? meta : "pinyin",
    };
  }

  if (!supportsLocalFonts()) return null;

  let fonts;
  try {
    fonts = await window.queryLocalFonts();
  } catch (err) {
    if (err?.name === "NotAllowedError" || err?.name === "SecurityError") {
      return null;
    }
    throw err;
  }

  for (const pref of PINYIN_FONT_PREFS) {
    const hit = fonts.find((f) => pref.match(f));
    if (!hit) continue;
    const blob = await hit.blob();
    const buffer = await blob.arrayBuffer();
    cache.set(cacheKey, buffer);
    cache.set(`${cacheKey}:label`, pref.label);
    return { buffer, label: pref.label };
  }

  return null;
}

/**
 * @param {FontChoice} choice
 * @returns {string}
 */
export function initialFontStatus(choice) {
  const preset = FONT_PRESETS[choice] || FONT_PRESETS.kaiti;
  if (manualFont) return `已指定字体文件：${manualFont.name}`;
  if (!supportsLocalFonts()) return "当前浏览器无法自动读取系统字体，请指定楷体 .ttf 文件。";
  return `将尝试读取系统「${preset.label}」`;
}
