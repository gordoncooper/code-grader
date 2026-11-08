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
    var t = $(".toast") || document.body.appendChild(h("div", { class: "toast", role: "status" }));
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

  // Drop zone: calls onFiles(FileList) for drops and picks.
  function dropZone(el, input, onFiles) {
    ["dragenter", "dragover"].forEach(function (ev) { el.addEventListener(ev, function (e) { e.preventDefault(); el.classList.add("over"); }); });
    ["dragleave", "drop"].forEach(function (ev) { el.addEventListener(ev, function (e) { e.preventDefault(); el.classList.remove("over"); }); });
    el.addEventListener("drop", function (e) { if (e.dataTransfer && e.dataTransfer.files.length) onFiles(Array.prototype.slice.call(e.dataTransfer.files)); });
    el.addEventListener("click", function (e) { if (e.target.tagName !== "A" && e.target.tagName !== "BUTTON") input.click(); });
    el.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
    input.addEventListener("change", function () { var list = Array.prototype.slice.call(input.files); input.value = ""; if (list.length) onFiles(list); });
  }

  // Tabs: buttons with data-tab="id" switch panels with id="panel-id".
  function tabs(container, onChange) {
    var btns = $$("button[data-tab]", container);
    function select(id) {
      btns.forEach(function (b) { var on = b.dataset.tab === id; b.setAttribute("aria-selected", on); var p = document.getElementById("panel-" + b.dataset.tab); if (p) p.hidden = !on; });
      if (onChange) onChange(id);
    }
    btns.forEach(function (b) { b.setAttribute("role", "tab"); b.addEventListener("click", function () { select(b.dataset.tab); }); });
    return { select: select };
  }

  // `code` spans in report text (questions, actions) as <code>; everything else stays plain text.
  function inline(text) {
    return String(text == null ? "" : text).split(/`([^`]+)`/).map(function (part, i) { return i % 2 ? h("code", null, part) : part; });
  }
  window.UI = { h: h, $: $, $$: $$, inline: inline, clear: clear, toast: toast, copyText: copyText, download: download, readFile: readFile,
                store: store, debounce: debounce, bindEnginePill: bindEnginePill, engineHelp: engineHelp, dropZone: dropZone, tabs: tabs };
})();
