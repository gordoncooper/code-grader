// Code Grading Suite: small helpers shared by the tool pages.
(function () {
  "use strict";
  // h("div", {class: "x", onclick: fn}, "text", child, [children]) — strings always become text, never HTML.
  function h(tag, props) {
    var el = document.createElement(tag);
    var kids = Array.prototype.slice.call(arguments, 2);
    if (props) Object.keys(props).forEach(function (k) {
      var v = props[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.slice(0, 2) === "on" && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (k === "dataset") Object.keys(v).forEach(function (d) { el.dataset[d] = v[d]; });
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, v);
    });
    (function add(list) {
      list.forEach(function (c) {
        if (c === null || c === undefined || c === false) return;
        if (Array.isArray(c)) add(c);
        else if (c instanceof Node) el.appendChild(c);
        else el.appendChild(document.createTextNode(String(c)));
      });
    })(kids);
    return el;
  }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function clear(el) { while (el && el.firstChild) el.removeChild(el.firstChild); return el; }

  function toast(msg) {
    var t = $(".toast") || ($("main") || document.body).appendChild(h("div", { class: "toast", role: "status" }));
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toast.t); toast.t = setTimeout(function () { t.classList.remove("show"); }, 1800);
  }
  function copyText(text) {
    function fallback() {
      var t = h("textarea", { style: "position:fixed;opacity:0" }); t.value = text; document.body.appendChild(t); t.select();
      try { document.execCommand("copy"); toast("Copied"); } catch (e) { toast("Press Ctrl/Cmd+C to copy"); }
      document.body.removeChild(t);
    }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(function () { toast("Copied"); }, fallback);
    else fallback();
  }
  function download(name, text, type) {
    var blob = text instanceof Blob ? text : new Blob([text], { type: type || "text/plain;charset=utf-8" });
    var a = h("a", { href: URL.createObjectURL(blob), download: name });
    document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }
  function readFile(file, asBytes) {
    return new Promise(function (resolve, reject) {
      var r = new FileReader();
      r.onload = function () { resolve(asBytes ? new Uint8Array(r.result) : r.result); };
      r.onerror = function () { reject(r.error); };
      if (asBytes) r.readAsArrayBuffer(file); else r.readAsText(file);
    });
  }
  var store = {
    get: function (k, d) { try { var v = localStorage.getItem("gk:" + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem("gk:" + k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ } }
  };
  function debounce(fn, ms) { var t; return function () { var a = arguments, s = this; clearTimeout(t); t = setTimeout(function () { fn.apply(s, a); }, ms); }; }

  // Engine status pill + friendly failure message.
  function bindEnginePill(el) {
    if (!el || !window.GK) return;
    GK.onStatus(function (s) {
      el.className = "engine-pill " + s.status;
      el.textContent = s.status === "ready" ? "Engine ready" : s.status === "failed" ? "Engine unavailable" : s.status === "loading" ? s.message : "Engine idle";
      el.title = s.message || "";
    });
  }
  function engineHelp(err) {
    var msg = (err && err.message) || String(err);
    return h("div", { class: "banner bad" },
      h("b", null, "The in-browser engine couldn't start. "), msg, " ",
      "This page runs the suite's Python code in your browser and loads the Python runtime from a CDN the first time. ",
      "Check your connection, or self-host the runtime (see ", h("a", { href: new URL("docs/DEPLOY.html#self-hosting-the-python-runtime", GK.site).href }, "Hosting guide"), ").");
  }

  // Drop zone: calls onFiles(FileList) for drops and picks. Keyboard and screen-reader users get the
  // real button inside it ([data-choose]); a click anywhere else in the zone does the same for the mouse.
  function dropZone(el, input, onFiles) {
    ["dragenter", "dragover"].forEach(function (ev) { el.addEventListener(ev, function (e) { e.preventDefault(); el.classList.add("over"); }); });
    ["dragleave", "drop"].forEach(function (ev) { el.addEventListener(ev, function (e) { e.preventDefault(); el.classList.remove("over"); }); });
    el.addEventListener("drop", function (e) { if (e.dataTransfer && e.dataTransfer.files.length) onFiles(Array.prototype.slice.call(e.dataTransfer.files)); });
    el.addEventListener("click", function (e) { if (e.target.tagName !== "A" && (e.target.tagName !== "BUTTON" || e.target.hasAttribute("data-choose"))) input.click(); });
    input.addEventListener("change", function () { var list = Array.prototype.slice.call(input.files); input.value = ""; if (list.length) onFiles(list); });
  }

  // Tabs (the WAI-ARIA tabs pattern): buttons with data-tab="id" switch panels with id="panel-id".
  // One tab is in the tab order; arrow keys, Home and End move between tabs.
  function tabKeys(container, getButtons) {
    container.setAttribute("role", "tablist");
    container.addEventListener("keydown", function (e) {
      var btns = getButtons().filter(function (b) { return !b.hidden; });
      var i = btns.indexOf(document.activeElement);
      if (i < 0) return;
      var j = e.key === "ArrowRight" || e.key === "ArrowDown" ? (i + 1) % btns.length
            : e.key === "ArrowLeft" || e.key === "ArrowUp" ? (i - 1 + btns.length) % btns.length
            : e.key === "Home" ? 0 : e.key === "End" ? btns.length - 1 : -1;
      if (j < 0) return;
      e.preventDefault();
      btns[j].focus();
      btns[j].click();
    });
  }
  function tabs(container, onChange) {
    var btns = $$("button[data-tab]", container);
    var uid = container.id || "tabs";
    btns.forEach(function (b) {
      var p = document.getElementById("panel-" + b.dataset.tab);
      b.setAttribute("role", "tab");
      b.id = b.id || uid + "-" + b.dataset.tab;
      if (p) { b.setAttribute("aria-controls", p.id); p.setAttribute("role", "tabpanel"); p.setAttribute("aria-labelledby", b.id); p.tabIndex = 0; }
      b.addEventListener("click", function () { select(b.dataset.tab); });
    });
    function select(id) {
      btns.forEach(function (b) {
        var on = b.dataset.tab === id;
        b.setAttribute("aria-selected", on);
        b.tabIndex = on ? 0 : -1;
        var p = document.getElementById("panel-" + b.dataset.tab);
        if (p) p.hidden = !on;
      });
      if (onChange) onChange(id);
    }
    tabKeys(container, function () { return btns; });
    return { select: select };
  }

  // Glossary help: every element with data-term="gate" gets a "?" button that shows the glossary's
  // definition (window.GLOSSARY, generated from rubric/glossary.json), the same words as GLOSSARY.md.
  var termSeq = 0;
  function terms(root) {
    if (!window.GLOSSARY) return;
    $$("[data-term]", root).forEach(function (el) {
      if (el.querySelector(":scope > .term-help")) return;
      var name = el.dataset.term, def = window.GLOSSARY[name];
      if (!def) return;
      var id = "term-" + (++termSeq);
      var box = h("div", { class: "term-pop", id: id, role: "note" }, h("b", null, name), " ", inline(def));
      var btn = h("button", { type: "button", class: "term-help", "aria-label": "What is " + (/^[aeiou]/i.test(name) ? "an " : "a ") + name + "?",
                              "aria-expanded": "false", "aria-controls": id }, "?");
      box.hidden = true;
      btn.addEventListener("click", function (e) {
        e.preventDefault(); e.stopPropagation();
        var open = box.hidden;
        $$(".term-pop").forEach(function (b) { b.hidden = true; });
        $$(".term-help").forEach(function (b) { b.setAttribute("aria-expanded", "false"); });
        box.hidden = !open; btn.setAttribute("aria-expanded", String(open));
      });
      el.appendChild(btn);
      el.insertAdjacentElement("afterend", box);
    });
  }
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") $$(".term-pop:not([hidden])").forEach(function (b) { b.hidden = true; var t = $("[aria-controls='" + b.id + "']"); if (t) { t.setAttribute("aria-expanded", "false"); t.focus(); } });
  });
  document.addEventListener("click", function (e) {
    if (!e.target.closest(".term-pop")) $$(".term-pop:not([hidden])").forEach(function (b) { b.hidden = true; var t = $("[aria-controls='" + b.id + "']"); if (t) t.setAttribute("aria-expanded", "false"); });
  });
  document.addEventListener("DOMContentLoaded", function () { terms(document); });

  // `code` spans in report text (questions, actions) as <code>; everything else stays plain text.
  function inline(text) {
    return String(text == null ? "" : text).split(/`([^`]+)`/).map(function (part, i) { return i % 2 ? h("code", null, part) : part; });
  }
  window.UI = { h: h, $: $, $$: $$, inline: inline, clear: clear, toast: toast, copyText: copyText, download: download, readFile: readFile,
                store: store, debounce: debounce, bindEnginePill: bindEnginePill, engineHelp: engineHelp, dropZone: dropZone, tabs: tabs, tabKeys: tabKeys, terms: terms };
})();
