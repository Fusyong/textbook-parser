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

/** @type {Map<string, ArrayBuffer>} */
const cache = new Map();

/** @type {{ name: string, buffer: ArrayBuffer } | null} */
let manualFont = null;

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
 * @param {FontChoice} choice
 * @returns {string}
 */
export function initialFontStatus(choice) {
  const preset = FONT_PRESETS[choice] || FONT_PRESETS.kaiti;
  if (manualFont) return `已指定字体文件：${manualFont.name}`;
  if (!supportsLocalFonts()) return "当前浏览器无法自动读取系统字体，请指定楷体 .ttf 文件。";
  return `将尝试读取系统「${preset.label}」`;
}
