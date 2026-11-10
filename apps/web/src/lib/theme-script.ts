// Server-safe part of the theme (no React): the storage key and the pre-paint script.
export const THEME_KEY = "buildai-theme";

/** Inline, dependency-free: sets data-theme before the first paint. */
export const themeScript = `(function(){try{var c=localStorage.getItem("${THEME_KEY}");var d=c==="dark"||(c!=="light"&&window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.dataset.theme=d?"dark":"light";}catch(e){document.documentElement.dataset.theme="light";}})();`;
