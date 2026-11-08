// Credits page: shows docs/credits.md. Understands the Markdown that file needs: # headings,
// "- " lists, paragraphs (separated by a blank line), [text](address) links and bare addresses.
"use strict";

const LINK = /\[([^\]]+)\]\((https?:[^)\s]+)\)|(https?:\/\/[^\s)]+)/g;

function inline(node, text) {  // text and links as DOM nodes, so nothing in the file can act as HTML
  let at = 0;
  for (const match of text.matchAll(LINK)) {
    node.append(text.slice(at, match.index));
    const a = document.createElement("a");
    a.href = match[2] || match[3];
    a.textContent = match[1] || match[3];
    a.target = "_blank";
    a.rel = "noopener";
    node.append(a);
    at = match.index + match[0].length;
  }
  node.append(text.slice(at));
  return node;
}

function render(markdown, box) {
  let paragraph = null, list = null;
  for (const raw of markdown.split(/\r?\n/)) {
    const line = raw.trim();
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (!line || heading) { paragraph = null; list = null; }
    if (heading) {
      box.append(inline(document.createElement(`h${heading[1].length}`), heading[2]));
    } else if (line.startsWith("- ")) {
      paragraph = null;
      if (!list) { list = document.createElement("ul"); box.append(list); }
      list.append(inline(document.createElement("li"), line.slice(2)));
    } else if (line) {
      list = null;
      if (paragraph) paragraph.append(" ");
      else { paragraph = document.createElement("p"); box.append(paragraph); }
      inline(paragraph, line);
    }
  }
}

fetch("/api/credits")
  .then((response) => { if (!response.ok) throw new Error(response.statusText); return response.text(); })
  .then((text) => render(text, document.getElementById("credits")))
  .catch((e) => {
    const bar = document.getElementById("error");
    bar.textContent = `The credits could not be loaded: ${e.message}`;
    bar.style.display = "block";
  });
