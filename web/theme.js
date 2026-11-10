// The look of every page (specification 7.4): light by default, or dark if this browser's player chose it.
// Loaded in the page's head, so the choice applies before anything is drawn.
"use strict";

const theme = {
  get() {
    try { return (JSON.parse(localStorage.getItem("nv:board") || "{}") || {}).theme === "dark" ? "dark" : "light"; } catch { return "light"; }
  },
  apply(name) {
    const root = document.documentElement;
    root.classList.toggle("theme-dark", name === "dark");
    root.classList.toggle("theme-light", name !== "dark");
  },
};
theme.apply(theme.get());
