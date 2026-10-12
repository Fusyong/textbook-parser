/**
 * 组词结果的纯文本格式（不依赖页面）。
 *
 * 批量结果：每个字一块，块之间空一行。
 * - 首行：字 + 制表符 + 选用词（词与词之间是全角空格）。这行给用户改、删。
 * - 以 # 开头的行：分桶参考，不参与「只留选用」。
 */
const WordResult = (() => {
  const HAN_RE = /\p{Script=Han}/u;
  const WORD_SEP = "\u3000";
  const WORD_SPLIT_RE = /[ \t\n\r\u00a0\u3000]+/;
  /** 参考行过长时只展示前若干词，其余以 … 表示 */
  const BUCKET_NOTE_CAP = 40;

  function isHanChar(ch) {
    return HAN_RE.test(ch);
  }

  /** 按出现顺序提取不重复的汉字。 */
  function hanCharsInOrder(text) {
    const out = [];
    const seen = new Set();
    for (const ch of String(text || "")) {
      if (!isHanChar(ch) || seen.has(ch)) continue;
      seen.add(ch);
      out.push(ch);
    }
    return out;
  }

  function splitWords(text) {
    return String(text || "")
      .split(WORD_SPLIT_RE)
      .map((s) => s.trim())
      .filter((s) => s && s !== "…");
  }

  function joinWords(words) {
    return (words || []).join(WORD_SEP);
  }

  /**
   * 按分桶优先级从已排序的词表里取选用词。
   * 同一桶内 sources 的顺序由 prefer 决定；桶顺序固定为终点课、前两课、其他。
   * @param {{ body?: Record<string, string[]>, table?: Record<string, string[]> }} sources
   * @param {{ limit?: number, include?: Record<string, boolean>, prefer?: string, skipMono?: boolean }} opts
   */
  function pickWords(sources, opts) {
    const limit = Number(opts?.limit);
    if (!Number.isFinite(limit) || limit <= 0) return [];
    const include = opts?.include || {};
    const order = opts?.prefer === "body" ? ["body", "table"] : ["table", "body"];
    const seen = new Set();
    const chosen = [];

    const take = (word) => {
      if (!word || seen.has(word)) return false;
      if (opts?.skipMono && [...String(word)].length < 2) return false;
      seen.add(word);
      chosen.push(word);
      return chosen.length >= limit;
    };

    for (const key of ["last", "near", "other"]) {
      if (include[key] === false) continue;
      for (const src of order) {
        const list = sources?.[src]?.[key];
        if (!Array.isArray(list)) continue;
        for (const word of list) {
          if (take(word)) return chosen;
        }
      }
    }
    return chosen;
  }

  function formatPickedLine(ch, words) {
    return `${ch}\t${joinWords(words)}`;
  }

  function formatBucketNote(label, words, cap = BUCKET_NOTE_CAP) {
    if (!words?.length) return "";
    const limit = cap > 0 ? cap : words.length;
    const shown = words.slice(0, limit);
    const more = words.length > shown.length ? `${WORD_SEP}…` : "";
    return `${label}：${joinWords(shown)}${more}`;
  }

  /**
   * @param {{ ch: string, picked?: string[], notes?: string[] }[]} blocks
   */
  function formatBatchText(blocks) {
    return (blocks || [])
      .map((block) => {
        const lines = [formatPickedLine(block.ch, block.picked || [])];
        for (const note of block.notes || []) {
          if (note) lines.push(`# ${note}`);
        }
        return lines.join("\n");
      })
      .join("\n\n");
  }

  /** 去掉空行和以 # 开头的参考行，留下可继续删改的选用行。 */
  function keepPickedLines(text) {
    return String(text || "")
      .split(/\r?\n/)
      .filter((line) => {
        const t = line.trim();
        return t && !t.startsWith("#");
      })
      .join("\n");
  }

  /**
   * 把命中按词中的汉字倒排，便于批量查询。
   * @param {{ w: string }[]} hits
   * @returns {Map<string, { w: string }[]>}
   */
  function indexByChar(hits) {
    const map = new Map();
    for (const hit of hits || []) {
      const word = hit && hit.w;
      if (!word) continue;
      const seen = new Set();
      for (const ch of String(word)) {
        if (!isHanChar(ch) || seen.has(ch)) continue;
        seen.add(ch);
        const list = map.get(ch);
        if (list) list.push(hit);
        else map.set(ch, [hit]);
      }
    }
    return map;
  }

  return {
    WORD_SEP,
    BUCKET_NOTE_CAP,
    isHanChar,
    hanCharsInOrder,
    splitWords,
    joinWords,
    pickWords,
    formatPickedLine,
    formatBucketNote,
    formatBatchText,
    keepPickedLines,
    indexByChar,
  };
})();

if (typeof window !== "undefined") window.WordResult = WordResult;
if (typeof module !== "undefined" && module.exports) module.exports = WordResult;
