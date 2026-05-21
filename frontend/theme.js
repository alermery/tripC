// 主题管理：使用 localStorage.xc_theme 持久化日间/夜间模式，并在页面加载时尽早写入 body data-theme。

const XC_THEME_KEY = "xc_theme";
const XC_THEME_DARK = "dark";
const XC_THEME_LIGHT = "light";

function getStoredTheme() {
  const saved = localStorage.getItem(XC_THEME_KEY);
  return saved === XC_THEME_DARK ? XC_THEME_DARK : XC_THEME_LIGHT;
}

function applyTheme(theme) {
  const next = theme === XC_THEME_DARK ? XC_THEME_DARK : XC_THEME_LIGHT;
  document.body.dataset.theme = next;
  localStorage.setItem(XC_THEME_KEY, next);
  window.dispatchEvent(new CustomEvent("xc-theme-change", { detail: { theme: next } }));
  return next;
}

function toggleTheme() {
  return applyTheme(getStoredTheme() === XC_THEME_DARK ? XC_THEME_LIGHT : XC_THEME_DARK);
}

function initTheme() {
  applyTheme(getStoredTheme());
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initTheme, { once: true });
} else {
  initTheme();
}
