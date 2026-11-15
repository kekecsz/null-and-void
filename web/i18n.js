// Translations of the screens (specification 7.6). English is the source and the default: the code
// writes its texts in English, and t() looks each one up in the chosen language's file
// (web/i18n/<code>.js). A text without a translation shows in English, so a new or changed text
// never breaks a page; it only waits to be translated.
// Loaded in the page's head, before the language files.
"use strict";

const I18N = {
  languages: { en: "English" },
  catalogs: {},
  names: {},     // the scenario's names in the chosen language, from the game's view
  chosen: null,
  // A language file registers itself: I18N.add("hu", "Magyar", { "English text": "translation", ... })
  add(code, name, catalog) {
    this.languages[code] = name;
    this.catalogs[code] = catalog;
  },
  get lang() {
    if (this.chosen === null) {
      let saved = "en";
      try { saved = localStorage.getItem("nv:lang") || "en"; } catch { /* private window */ }
      this.chosen = saved in this.languages ? saved : "en";
    }
    return this.chosen;
  },
  choose(code) {
    try { localStorage.setItem("nv:lang", code); } catch { /* private window */ }
    location.reload();  // every text is drawn again in the new language
  },
  // The scenario's names (states, parameters, title) for the chosen language, from the game's view.
  useScenario(translations) {
    this.names = (translations || {})[this.lang] || {};
  },
  // The page's own HTML: every text and placeholder/title that the catalog knows is translated.
  translatePage(root) {
    const catalog = this.catalogs[this.lang];
    document.documentElement.lang = this.lang;
    if (!catalog) return;
    const walker = document.createTreeWalker(root || document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const text = node.nodeValue.trim();
      if (text && catalog[text]) node.nodeValue = node.nodeValue.replace(text, catalog[text]);
    }
    for (const el of document.querySelectorAll("[placeholder], [title], [data-subtitle]")) {
      for (const attr of ["placeholder", "title", "data-subtitle"]) {
        const text = el.getAttribute(attr);
        if (text && catalog[text]) el.setAttribute(attr, catalog[text]);
      }
    }
  },
  // A language menu in the page header (an element with id "lang-choice").
  initChoice() {
    const select = document.getElementById("lang-choice");
    if (!select) return;
    select.innerHTML = "";
    for (const [code, name] of Object.entries(this.languages)) select.add(new Option(name, code, false, code === this.lang));
    select.onchange = () => this.choose(select.value);
  },
};

// The text in the chosen language; {name} placeholders are filled in from params.
function t(text, params) {
  const catalog = I18N.catalogs[I18N.lang];
  let out = (catalog && catalog[text]) || text;
  if (params) out = out.replace(/\{(\w+)\}/g, (whole, name) => (name in params ? String(params[name]) : whole));
  return out;
}

// A name from the scenario (a state, input parameter, world outcome or the title).
const tn = (name) => (name && I18N.names[name]) || name;
