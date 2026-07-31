// Apply the persisted/system theme before the stylesheet and application render.
// This file is external so it remains compatible with the gateway's strict
// `script-src 'self'` Content Security Policy.
(function applyInitialTheme() {
  try {
    var stored = localStorage.getItem("agentforge.theme");
    var theme =
      stored === "light" || stored === "dark"
        ? stored
        : window.matchMedia("(prefers-color-scheme: light)").matches
          ? "light"
          : "dark";
    document.documentElement.setAttribute("data-theme", theme);
  } catch {
    document.documentElement.setAttribute("data-theme", "dark");
  }
})();
