/**
 * 范字与拼音字体。
 * 默认按本机已安装字体自动选用，不必先手选；下拉和「指定文件」仍可覆盖。
 * 拼音优先 Wukong Pinyin Sans ExtraLight，其后为华文细黑、微软雅黑、Noto Sans。
 * 范字优先楷体，其后为其他楷体，再退到细黑／雅黑。
 */

/** @typedef {{ family?: string, fullName?: string, postscriptName?: string, style?: string, blob: () => Promise<Blob> }} LocalFont */

const HAN_CHAIN = [
  { id: "kaiti", label: "楷体", test: isPlainKai },
  { id: "kaiti_gb2312", label: "楷体_GB2312", test: isKaiGb2312 },
  { id: "stkaiti", label: "华文楷体", test: isStKaiti },
  { id: "stxihei", label: "华文细黑", test: isStXihei },
  { id: "yahei", label: "微软雅黑", test: isYaHei },
  { id: "noto-sc", label: "Noto Sans SC", test: isNotoSansSc },
];

const PINYIN_CHAIN = [
  { id: "wukong-extralight", label: "Wukong Pinyin Sans ExtraLight", test: isWukongExtraLight },
  { id: "wukong", label: "Wukong Pinyin Sans", test: isWukongOther },
  { id: "stxihei", label: "华文细黑", test: isStXihei },
  { id: "yahei", label: "微软雅黑", test: isYaHei },
  { id: "noto-light", label: "Noto Sans Light", test: isNotoSansLight },
  { id: "noto", label: "Noto Sans", test: isNotoSansRegular },
];

/** 供界面下拉使用（不含仅作自动后备的中间项）。 */
export const HAN_FONT_OPTIONS = [
  { id: "auto", label: "自动" },
  { id: "kaiti", label: "楷体" },
  { id: "kaiti_gb2312", label: "楷体_GB2312" },
  { id: "stkaiti", label: "华文楷体" },
];

export const PINYIN_FONT_OPTIONS = [
  { id: "auto", label: "自动" },
  { id: "wukong-extralight", label: "Wukong 拼音 ExtraLight" },
  { id: "stxihei", label: "华文细黑" },
  { id: "yahei", label: "微软雅黑" },
  { id: "noto", label: "Noto Sans" },
];

/** @type {Record<string, { label: string, cssFamily: string, postscriptNames: string[] }>} */
export const FONT_PRESETS = {
  kaiti_gb2312: {
    label: "楷体_GB2312",
    cssFamily: '"楷体_GB2312", "KaiTi_GB2312", "楷体", "KaiTi", serif',
    postscriptNames: ["KaiTi_GB2312"],
  },
  kaiti: {
    label: "楷体",
    cssFamily: '"楷体", "KaiTi", "SimKai", serif',
    postscriptNames: ["KaiTi", "SimKai"],
  },
  stkaiti: {
    label: "华文楷体",
    cssFamily: '"华文楷体", "STKaiti", serif',
    postscriptNames: ["STKaiti"],
  },
};

/** 拼音固定字号（pt） */
export const PINYIN_FONT_SIZE_PT = 10.5;

/** 拼音基线相对字框上沿的间距（pt），需留出降部以免压格线 */
export const PINYIN_GAP_FROM_CELL_PT = 5;

/** @type {Map<string, ArrayBuffer>} */
const bufferCache = new Map();

/** @type {{ name: string, buffer: ArrayBuffer } | null} */
let manualHan = null;

/** @type {{ name: string, buffer: ArrayBuffer } | null} */
let manualPinyin = null;

/** @type {Promise<LocalFont[]> | null} */
let localFontList = null;

function norm(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[\s_\-./]+/g, "");
}

/** @param {LocalFont} font */
function blobName(font) {
  return norm([font.family, font.fullName, font.postscriptName, font.style].filter(Boolean).join(" "));
}

/** @param {LocalFont} font */
function stylePenalty(font) {
  const text = blobName(font);
  if (/bold|black|heavy/.test(text)) return 2;
  if (/light|thin|extralight/.test(text)) return 1;
  return 0;
}

/** @param {LocalFont} font */
function isKaiGb2312(font) {
  const name = blobName(font);
  return name.includes("gb2312") && (name.includes("kaiti") || name.includes("楷体"));
}

/** @param {LocalFont} font */
function isPlainKai(font) {
  const name = blobName(font);
  const family = norm(font.family);
  if (name.includes("gb2312") || name.includes("stkaiti") || name.includes("华文") || name.includes("stxihei")) {
    return false;
  }
  return family === "kaiti" || family === "楷体" || family === "simkai" || name === "kaiti";
}

/** @param {LocalFont} font */
function isStKaiti(font) {
  const name = blobName(font);
  return name.includes("stkaiti") || name.includes("华文楷体");
}

/** @param {LocalFont} font */
function isStXihei(font) {
  const name = blobName(font);
  return name.includes("stxihei") || name.includes("华文细黑");
}

/** @param {LocalFont} font */
function isYaHei(font) {
  const name = blobName(font);
  if (!(name.includes("microsoftyahei") || name.includes("微软雅黑"))) return false;
  if (/light|bold|black|heavy/.test(name)) return false;
  return true;
}

/** @param {LocalFont} font */
function isNotoSansSc(font) {
  const name = blobName(font);
  return name.includes("notosanssc") || name.includes("notosanscjksc");
}

/** @param {LocalFont} font */
function isWukongExtraLight(font) {
  const name = blobName(font);
  return name.includes("wukong") && name.includes("pinyin") && name.includes("extralight");
}

/** @param {LocalFont} font */
function isWukongOther(font) {
  const name = blobName(font);
  return name.includes("wukong") && name.includes("pinyin") && !name.includes("extralight");
}

/** 只认「Noto Sans」本身，不把 Noto Sans SC / CJK / Arabic 算进来。 */
function isPlainNotoFamily(font) {
  const family = norm(font.family);
  return family === "notosans" || family === "notosanslight";
}

/** @param {LocalFont} font */
function isNotoSansLight(font) {
  if (!isPlainNotoFamily(font)) return false;
  const name = blobName(font);
  if (/condensed|italic|extralight/.test(name)) return false;
  return norm(font.family) === "notosanslight" || name.includes("light");
}

/** @param {LocalFont} font */
function isNotoSansRegular(font) {
  if (norm(font.family) !== "notosans") return false;
  const name = blobName(font);
  return !/light|bold|italic|condensed|black|medium|thin/.test(name);
}

/**
 * pdf-lib 直接嵌入 .ttc 会失败。集合字体先取出一个常规字面再交给它。
 */
export function fontkitWithCollections() {
  const fk = window.fontkit;
  if (!fk) throw new Error("FONTKIT_MISSING");
  return {
    create(buffer, postscriptName) {
      const opened = postscriptName ? fk.create(buffer, postscriptName) : fk.create(buffer);
      if (opened?.fonts?.length) {
        const face =
          opened.fonts.find((item) => !/bold|light|black|heavy/i.test(item.postscriptName || "")) ||
          opened.fonts[0];
        return fk.create(buffer, face.postscriptName);
      }
      return opened;
    },
  };
}

export function supportsLocalFonts() {
  return typeof window !== "undefined" && "queryLocalFonts" in window;
}

export function setManualFontFile(file) {
  if (!file) {
    manualHan = null;
    return Promise.resolve(null);
  }
  return file.arrayBuffer().then((buffer) => {
    manualHan = { name: file.name, buffer };
    return manualHan;
  });
}

export function setManualPinyinFontFile(file) {
  if (!file) {
    manualPinyin = null;
    return Promise.resolve(null);
  }
  return file.arrayBuffer().then((buffer) => {
    manualPinyin = { name: file.name, buffer };
    return manualPinyin;
  });
}

export function getManualFontMeta() {
  return manualHan ? { name: manualHan.name } : null;
}

export function getManualPinyinMeta() {
  return manualPinyin ? { name: manualPinyin.name } : null;
}

async function listLocalFonts() {
  if (!supportsLocalFonts()) throw new Error("NO_LOCAL_FONT_API");
  if (!localFontList) {
    localFontList = window.queryLocalFonts().catch((err) => {
      localFontList = null;
      if (err?.name === "NotAllowedError" || err?.name === "SecurityError") {
        throw new Error("FONT_PERMISSION_DENIED");
      }
      throw err;
    });
  }
  return localFontList;
}

/** @param {LocalFont} font */
async function fontBuffer(font) {
  const key = font.postscriptName || font.fullName || font.family || "";
  const cached = bufferCache.get(key);
  if (cached) return cached;
  const buffer = await (await font.blob()).arrayBuffer();
  bufferCache.set(key, buffer);
  return buffer;
}

/**
 * @param {{ id: string, label: string, test: (font: LocalFont) => boolean }[]} chain
 * @param {string} choice
 */
function orderChain(chain, choice) {
  if (!choice || choice === "auto") return chain;
  const picked = chain.find((item) => item.id === choice);
  if (!picked) return chain;
  return [picked, ...chain.filter((item) => item.id !== choice)];
}

/**
 * @param {{ id: string, label: string, test: (font: LocalFont) => boolean }[]} chain
 * @param {string} choice
 * @param {(buffer: ArrayBuffer) => Promise<unknown>} embed
 * @param {{ name: string, buffer: ArrayBuffer } | null} manual
 */
async function resolveFromChain(chain, choice, embed, manual) {
  if (manual?.buffer) {
    try {
      const font = await embed(manual.buffer);
      return { font, label: manual.name, source: "manual", fallbackFrom: "" };
    } catch {
      throw new Error("FONT_EMBED_FAILED");
    }
  }

  const fonts = await listLocalFonts();
  const requested = chain.find((item) => item.id === choice);
  for (const candidate of orderChain(chain, choice)) {
    const hits = fonts.filter((font) => candidate.test(font));
    hits.sort((a, b) => stylePenalty(a) - stylePenalty(b));
    const hit = hits[0];
    if (!hit) continue;
    try {
      const embedded = await embed(await fontBuffer(hit));
      return {
        font: embedded,
        label: candidate.label,
        source: "system",
        fallbackFrom: requested && candidate.id !== requested.id ? requested.label : "",
      };
    } catch {
      continue;
    }
  }
  return null;
}

/**
 * @param {string} choice
 * @param {(buffer: ArrayBuffer) => Promise<unknown>} embed
 */
export async function resolveHanFont(choice, embed) {
  const resolved = await resolveFromChain(HAN_CHAIN, choice || "auto", embed, manualHan);
  if (!resolved) throw new Error("FONT_NOT_FOUND");
  return resolved;
}

/**
 * 找不到拼音字体时返回 null，调用方改用范字字体。
 * @param {string} choice
 * @param {(buffer: ArrayBuffer) => Promise<unknown>} embed
 */
export async function resolvePinyinFont(choice, embed) {
  try {
    return await resolveFromChain(PINYIN_CHAIN, choice || "auto", embed, manualPinyin);
  } catch (err) {
    // 范字已经可用时，读不到本机拼音字体就改用范字，不让整份练习纸失败。
    if (err?.message === "FONT_PERMISSION_DENIED" || err?.message === "NO_LOCAL_FONT_API") return null;
    throw err;
  }
}

/**
 * @param {string} [hanChoice]
 * @param {string} [pinyinChoice]
 */
export function initialFontStatus(hanChoice = "auto", pinyinChoice = "auto") {
  if (manualHan || manualPinyin) {
    const parts = [];
    if (manualHan) parts.push(`范字文件：${manualHan.name}`);
    if (manualPinyin) parts.push(`拼音文件：${manualPinyin.name}`);
    return `已指定${parts.join("；")}（仅本次浏览有效）`;
  }
  if (!supportsLocalFonts()) {
    return "当前浏览器不能读取系统字体。请用 Chrome / Edge 打开，或指定字体文件。";
  }
  const han =
    !hanChoice || hanChoice === "auto"
      ? "范字自动用楷体（没有则用其他楷体、华文细黑或微软雅黑）"
      : `范字优先「${HAN_CHAIN.find((item) => item.id === hanChoice)?.label || hanChoice}」`;
  const pinyin =
    !pinyinChoice || pinyinChoice === "auto"
      ? "拼音自动用 Wukong ExtraLight，其次华文细黑、微软雅黑、Noto Sans"
      : `拼音优先「${PINYIN_CHAIN.find((item) => item.id === pinyinChoice)?.label || pinyinChoice}」`;
  return `${han}；${pinyin}。首次生成请允许访问本地字体。`;
}

/**
 * @param {{ hanLabel?: string, hanFallback?: string, hanSource?: string, pinyinLabel?: string, pinyinFallback?: string } | null | undefined} report
 */
export function formatFontReport(report) {
  if (!report) return "";
  const han = report.hanFallback
    ? `未找到「${report.hanFallback}」，范字改用「${report.hanLabel}」`
    : `范字：${report.hanLabel || "未定"}`;
  const hanTail = report.hanSource === "manual" ? "（指定文件）" : "";
  if (report.pinyinHidden) return `${han}${hanTail}`;
  let pinyin = "拼音：改用范字字体";
  if (report.pinyinLabel) {
    pinyin = report.pinyinFallback
      ? `未找到「${report.pinyinFallback}」，拼音改用「${report.pinyinLabel}」`
      : `拼音：${report.pinyinLabel}`;
  }
  return `${han}${hanTail}；${pinyin}`;
}
