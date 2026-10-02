/**
 * 为 textarea 左侧挂行号栏，随内容与滚动同步。
 * 若外层已有 .lined-editor > .lined-editor-gutter，则只绑定同步。
 * @param {HTMLTextAreaElement | null | undefined} textarea
 */
export function attachLineNumbers(textarea) {
  if (!textarea || textarea.dataset.lineNumbers === "1") return;

  let shell = textarea.closest(".lined-editor");
  /** @type {HTMLPreElement | null} */
  let gutter = shell?.querySelector(".lined-editor-gutter") || null;

  if (!shell || !gutter) {
    shell = document.createElement("div");
    shell.className = "lined-editor";
    gutter = document.createElement("pre");
    gutter.className = "lined-editor-gutter";
    gutter.setAttribute("aria-hidden", "true");
    const parent = textarea.parentNode;
    if (!parent) return;
    parent.insertBefore(shell, textarea);
    shell.appendChild(gutter);
    shell.appendChild(textarea);
  }

  textarea.dataset.lineNumbers = "1";

  const syncGutter = () => {
    const n = Math.max(1, String(textarea.value).split("\n").length);
    let text = "";
    for (let i = 1; i <= n; i++) {
      text += (i === 1 ? "" : "\n") + i;
    }
    gutter.textContent = text;
  };

  const syncScroll = () => {
    gutter.scrollTop = textarea.scrollTop;
  };

  textarea.addEventListener("input", syncGutter);
  textarea.addEventListener("scroll", syncScroll);
  textarea.addEventListener("lineditor:refresh", syncGutter);

  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => {
      syncGutter();
      syncScroll();
    }).observe(textarea);
  }

  syncGutter();
}

/** @param {HTMLTextAreaElement | null | undefined} textarea */
export function refreshLineNumbers(textarea) {
  textarea?.dispatchEvent(new Event("lineditor:refresh"));
}
