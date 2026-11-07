// Code Grading Suite: "Set up a project" page.
(function () {
  "use strict";
  var h = UI.h, $ = UI.$, $$ = UI.$$;
  var KNOWN = ["project", "answers", "zones", "targets", "weights", "gates", "review"];
  var info = null;          // questions, presets, catalog… from gradekit
  var lastCfg = null;       // effective config from the last build
  var lastToml = "";
  var state = blank();
  var extras = {};          // dispositions, decisions, components and anything else we don't edit

  function blank() {
    return { project: { name: "", preset: "default" }, answers: {}, zones: [],
             targets: { mode: "proportional", overrides: {} }, weights: { overrides: {} },
             gates: { extra: [] }, review: {} };
  }
  function benchmarkName(id) {
    var b = info && info.catalog.benchmarks.find(function (x) { return x.id === id; });
    return b ? b.name : id;
  }

  // ------------------------------------------------------------------ rendering the form
  function renderPresets() {
    var box = UI.clear($("#presets"));
    Object.keys(info.presets).forEach(function (name) {
      var p = info.presets[name];
      var input = h("input", { type: "radio", name: "preset", value: name });
      input.checked = state.project.preset === name;
      input.addEventListener("change", function () { applyPreset(name, true); });
      box.appendChild(h("label", { class: "choice" }, input, h("b", null, name.replace(/_/g, " ")), h("span", null, p.description || "")));
    });
  }

  function presetAnswer(q) {
    var p = info.presets[state.project.preset] || {};
    var a = (p.answers || {})[q];
    return a !== undefined ? a : info.questions[q].default;
  }

  function applyPreset(name, announce) {
    state.project.preset = name;
    Object.keys(info.questions).forEach(function (q) { state.answers[q] = presetAnswer(q); });
    renderQuestions();
    if (announce) UI.toast("Answers set from the " + name.replace(/_/g, " ") + " preset");
    refresh();
  }

  function effectChips(opt) {
    var chips = [];
    Object.keys(opt.effects || {}).forEach(function (id) {
      var d = opt.effects[id];
      chips.push(h("span", { class: "chip " + (d > 0 ? "up" : "down"), title: benchmarkName(id) }, id + " " + (d > 0 ? "+" : "") + d));
    });
    (opt.gates || []).forEach(function (id) { chips.push(h("span", { class: "chip gate", title: benchmarkName(id) + " becomes a gate" }, id + " gate")); });
    if (!chips.length) chips.push(h("span", { class: "chip" }, "no change"));
    return chips;
  }

  function renderQuestions() {
    var box = UI.clear($("#questions"));
    Object.keys(info.questions).forEach(function (q) {
      var qd = info.questions[q];
      var sel = h("select", { "aria-label": qd.prompt });
      Object.keys(qd.options).forEach(function (o) {
        var opt = h("option", { value: o }, qd.options[o].label || o);
        if (state.answers[q] === o) opt.selected = true;
        sel.appendChild(opt);
      });
      var effects = h("div", { class: "effects" }, effectChips(qd.options[state.answers[q]] || {}));
      var note = h("div", { class: "from-preset" });
      function updateNote() {
        var pa = presetAnswer(q);
        note.textContent = state.answers[q] === pa ? "From the preset" : "Changed (preset: " + (qd.options[pa] ? qd.options[pa].label : pa) + ")";
      }
      updateNote();
      sel.addEventListener("change", function () {
        state.answers[q] = sel.value;
        UI.clear(effects); effectChips(qd.options[sel.value]).forEach(function (c) { effects.appendChild(c); });
        updateNote(); refresh();
      });
      box.appendChild(h("div", { class: "q" }, h("div", { class: "qtext" }, h("b", null, qd.prompt), effects), h("div", null, sel, note)));
    });
  }

  var zoneSeq = 0;
  function renderZones() {
    var box = UI.clear($("#zones"));
    if (!state.zones.length) {
      box.appendChild(h("p", { class: "kbd-note" }, "No zones yet: all code counts as normal. Most projects mark at least their money, auth or data-writing code as hot."));
      return;
    }
    state.zones.forEach(function (z, i) {
      var name = h("input", { type: "text", placeholder: "payments", "aria-label": "Zone name", value: z.name || "" });
      var paths = h("textarea", { rows: "2", placeholder: "src/payments/**", "aria-label": "Paths, one per line" });
      paths.value = (z.paths || []).join("\n");
      var why = h("input", { type: "text", class: "why", placeholder: "Why: e.g. moves money", "aria-label": "Why", value: z.why || "" });
      var group = "crit-" + (++zoneSeq);
      var seg = h("div", { class: "seg", role: "radiogroup", "aria-label": "Criticality" }, ["hot", "normal", "cold"].map(function (c) {
        var r = h("input", { type: "radio", name: group, value: c }); r.checked = (z.criticality || "hot") === c;
        r.addEventListener("change", function () { z.criticality = c; refresh(); });
        return h("label", null, r, h("span", null, c));
      }));
      name.addEventListener("input", function () { z.name = name.value; refresh(); });
      paths.addEventListener("input", function () { z.paths = paths.value.split(/\n|,/).map(function (s) { return s.trim(); }).filter(Boolean); refresh(); });
      why.addEventListener("input", function () { z.why = why.value; refresh(); });
      var del = h("button", { type: "button", class: "icon-btn", "aria-label": "Remove zone", title: "Remove" }, "×");
      del.addEventListener("click", function () { state.zones.splice(i, 1); renderZones(); refresh(); });
      box.appendChild(h("div", { class: "zone-row" }, name, paths, seg, del, why));
    });
  }

  function benchmarkSelect(selected, label) {
    var sel = h("select", { "aria-label": label || "Benchmark" });
    info.catalog.benchmarks.forEach(function (b) {
      var o = h("option", { value: b.id }, b.id + " · " + b.name); if (b.id === selected) o.selected = true; sel.appendChild(o);
    });
    return sel;
  }

  function renderOverrides() {
    var wbox = UI.clear($("#w-overrides"));
    Object.keys(state.weights.overrides).forEach(function (id) {
      var ov = state.weights.overrides[id];
      var sel = benchmarkSelect(id, "Benchmark to override");
      var w = h("select", { "aria-label": "Weight" }, [0, 1, 2, 3].map(function (n) { var o = h("option", { value: n }, n === 0 ? "0 (doesn't count)" : String(n)); if (ov.weight === n) o.selected = true; return o; }));
      var reason = h("input", { type: "text", placeholder: "Reason (required)", value: ov.reason || "", "aria-label": "Reason" });
      var del = h("button", { type: "button", class: "icon-btn", "aria-label": "Remove override" }, "×");
      sel.addEventListener("change", function () { var v = state.weights.overrides[id]; delete state.weights.overrides[id]; state.weights.overrides[sel.value] = v; renderOverrides(); refresh(); });
      w.addEventListener("change", function () { ov.weight = parseInt(w.value, 10); refresh(); });
      reason.addEventListener("input", function () { ov.reason = reason.value; refresh(); });
      del.addEventListener("click", function () { delete state.weights.overrides[id]; renderOverrides(); refresh(); });
      wbox.appendChild(h("div", { class: "row-btns", style: "margin:6px 0" }, h("div", { style: "flex:2;min-width:180px" }, sel), h("div", { style: "width:150px" }, w), h("div", { style: "flex:3;min-width:180px" }, reason), del));
    });
    var tbox = UI.clear($("#t-overrides"));
    Object.keys(state.targets.overrides || {}).forEach(function (id) {
      var sel = benchmarkSelect(id, "Benchmark");
      var v = h("input", { type: "number", min: "1", max: "10", value: state.targets.overrides[id], "aria-label": "Target", style: "width:90px" });
      var del = h("button", { type: "button", class: "icon-btn", "aria-label": "Remove target override" }, "×");
      sel.addEventListener("change", function () { var x = state.targets.overrides[id]; delete state.targets.overrides[id]; state.targets.overrides[sel.value] = x; renderOverrides(); refresh(); });
      v.addEventListener("input", function () { var n = parseInt(v.value, 10); if (n >= 1 && n <= 10) { state.targets.overrides[id] = n; refresh(); } });
      del.addEventListener("click", function () { delete state.targets.overrides[id]; renderOverrides(); refresh(); });
      tbox.appendChild(h("div", { class: "row-btns", style: "margin:6px 0" }, h("div", { style: "flex:1;min-width:200px" }, sel), v, del));
    });
    var gsel = UI.clear($("#extra-gate"));
    gsel.appendChild(h("option", { value: "" }, "Add a gate…"));
    info.catalog.benchmarks.forEach(function (b) {
      if ((state.gates.extra || []).indexOf(b.id) < 0) gsel.appendChild(h("option", { value: b.id }, b.id + " · " + b.name));
    });
    var gbox = UI.clear($("#extra-gates"));
    (state.gates.extra || []).forEach(function (id) {
      var x = h("button", { type: "button", class: "chip gate", title: "Remove", "aria-label": "Remove gate " + id }, id + " ×");
      x.addEventListener("click", function () { state.gates.extra = state.gates.extra.filter(function (g) { return g !== id; }); renderOverrides(); refresh(); });
      gbox.appendChild(x);
    });
  }

  function syncFieldsFromState() {
    $$("[data-proj]").forEach(function (el) { el.value = state.project[el.dataset.proj] || ""; });
    $("#f-oos").value = (state.project.out_of_scope || []).join("\n");
    var mode = state.targets.mode || "proportional";
    $("#t-mode").value = mode.indexOf("level:") === 0 ? "level" : mode;
    $("#t-level-wrap").hidden = mode.indexOf("level:") !== 0;
    if (mode.indexOf("level:") === 0) $("#t-level").value = mode.split(":")[1];
    $("#agent-decisions").checked = !!(state.review && state.review.allow_agent_decisions);
  }

  function renderAll() {
    renderPresets(); renderQuestions(); renderZones(); renderOverrides(); syncFieldsFromState();
  }

  // ------------------------------------------------------------------ building + preview
  function projectData() {
    var d = JSON.parse(JSON.stringify(state));
    var proj = d.project;
    Object.keys(proj).forEach(function (k) { if (proj[k] === "" || (Array.isArray(proj[k]) && !proj[k].length && k !== "out_of_scope")) delete proj[k]; });
    if (!proj.name) proj.name = "my-project";
    d.zones = d.zones.filter(function (z) { return (z.paths || []).length; }).map(function (z) {
      var o = { name: z.name || "zone", paths: z.paths, criticality: z.criticality || "hot" }; if (z.why) o.why = z.why;
      Object.keys(z).forEach(function (k) { if (!(k in o) && ["name", "paths", "criticality", "why"].indexOf(k) < 0) o[k] = z[k]; });
      return o;
    });
    if (!Object.keys(d.targets.overrides || {}).length) delete d.targets.overrides;
    if (!Object.keys(d.weights.overrides || {}).length) delete d.weights.overrides;
    if (!(d.gates.extra || []).length) delete d.gates.extra;
    if (!Object.keys(d.gates).length) delete d.gates;
    if (!d.review || !d.review.allow_agent_decisions) delete d.review;
    Object.keys(extras).forEach(function (k) { d[k] = extras[k]; });
    return d;
  }

  var seq = 0;
  var refresh = UI.debounce(async function () {
    var my = ++seq;
    try {
      var res = await GK.call("build", { project: projectData(), org_toml: $("#org-toml").value || null });
      if (my !== seq) return;
      lastToml = res.toml; lastCfg = res.config;
      $("#toml-out").textContent = res.toml;
      var st = UI.clear($("#build-status"));
      var pv = UI.clear($("#pv-status"));
      if (res.config_error) {
        st.appendChild(h("div", { class: "banner bad" }, h("b", null, "Fix these before using the file:"), h("pre", { style: "margin:6px 0 0;white-space:pre-wrap;background:none;border:0;padding:0" }, res.config_error)));
        pv.appendChild(h("span", { class: "badge bad" }, "Has errors"));
      } else {
        pv.appendChild(h("span", { class: "badge ok" }, "Valid"));
        pv.appendChild(h("span", null, " · config ", h("code", null, res.config.hash), " · preset ", res.config.preset));
        (res.config.warnings || []).forEach(function (w) { st.appendChild(h("div", { class: "banner warn" }, w)); });
      }
      renderPreview();
      store.save();
    } catch (err) {
      showEngineError(err);
    }
  }, 250);

  function renderPreview() {
    var gbox = UI.clear($("#pv-gates"));
    var wbox = UI.clear($("#pv-weights"));
    if (!lastCfg) { gbox.appendChild(h("span", { class: "kbd-note" }, "—")); return; }
    lastCfg.gates.benchmarks.forEach(function (id) {
      gbox.appendChild(h("span", { class: "chip gate", title: benchmarkName(id) + " — " + lastCfg.gates.why[id].join(", ") }, id));
    });
    var pillars = {};
    info.catalog.benchmarks.forEach(function (b) { (pillars[b.pillar] = pillars[b.pillar] || []).push(b.id); });
    Object.keys(pillars).forEach(function (p) {
      var cells = pillars[p].map(function (id) {
        var w = lastCfg.weights[id];
        var mark = w.override ? "*" : w.weight > w.base ? "↑" : w.weight < w.base ? "↓" : "";
        var gate = lastCfg.gates.benchmarks.indexOf(id) >= 0;
        var b = h("button", { type: "button", class: "wcell w" + w.weight + (gate ? " isgate" : ""), title: id + " " + w.name + ": weight " + w.weight + (gate ? " (gate)" : "") }, id + " " + w.weight + mark);
        b.addEventListener("click", function () { explain(id); });
        return b;
      });
      wbox.appendChild(h("div", { class: "prow" }, h("b", null, p), h("div", { class: "cells" }, cells)));
    });
    if (explain.current) explain(explain.current);
  }

  function explain(id) {
    explain.current = id;
    var w = lastCfg && lastCfg.weights[id];
    var box = UI.clear($("#pv-explain"));
    if (!w) return;
    var rows = [h("tr", null, h("td", null, "Base weight"), h("td", null, String(w.base)))];
    w.trace.forEach(function (t) { rows.push(h("tr", null, h("td", null, "because " + t.because.replace("=", " = ")), h("td", null, (t.delta > 0 ? "+" : "") + t.delta))); });
    if (w.clamped) rows.push(h("tr", null, h("td", null, "kept within 1–3"), h("td", null, "→ " + Math.max(1, Math.min(3, w.raw)))));
    if (w.override) rows.push(h("tr", null, h("td", null, "override: " + w.override.reason), h("td", null, "→ " + w.override.weight)));
    rows.push(h("tr", null, h("th", null, "Final weight"), h("th", null, String(w.weight))));
    var gate = lastCfg.gates.why[id];
    box.appendChild(h("div", { class: "explain" }, h("b", null, id + " · " + w.name), h("table", null, rows),
      gate ? h("div", { style: "margin-top:6px" }, h("span", { class: "chip gate" }, "gate"), " because " + gate.join(", ")) : null));
  }

  function showEngineError(err) {
    var box = UI.clear($("#engine-error"));
    if (err && err.gk) { box.appendChild(h("div", { class: "banner bad" }, err.message)); return; }
    box.appendChild(UI.engineHelp(err));
    $("#toml-out").textContent = "The engine isn't available, so the file can't be generated here.";
  }

  // ------------------------------------------------------------------ loading an existing file
  async function loadToml(text, name) {
    try {
      var res = await GK.call("parse", { toml: text, name: name || "project.toml" });
      var d = res.project;
      var fresh = blank();
      fresh.project = Object.assign(fresh.project, d.project || {});
      fresh.answers = d.answers || {};
      fresh.zones = d.zones || [];
      fresh.targets = Object.assign({ mode: "proportional", overrides: {} }, d.targets || {});
      fresh.weights = Object.assign({ overrides: {} }, d.weights || {});
      fresh.gates = Object.assign({ extra: [] }, d.gates || {});
      fresh.review = d.review || {};
      extras = {};
      Object.keys(d).forEach(function (k) { if (KNOWN.indexOf(k) < 0) extras[k] = d[k]; });
      state = fresh;
      if (!info.presets[state.project.preset]) state.project.preset = "default";
      Object.keys(info.questions).forEach(function (q) { if (!(q in state.answers)) state.answers[q] = presetAnswer(q); });
      renderAll(); refresh();
      var kept = Object.keys(extras).map(function (k) { return k + " (" + (Array.isArray(extras[k]) ? extras[k].length : 1) + ")"; });
      UI.toast("Loaded" + (kept.length ? "; kept " + kept.join(", ") : ""));
    } catch (err) {
      UI.toast("Couldn't load it: " + err.message);
      UI.clear($("#build-status")).appendChild(h("div", { class: "banner bad" }, err.message));
    }
  }

  // Remember the form between visits (this browser only).
  var store = {
    save: function () { UI.store.set("setup", { state: state, extras: extras, org: $("#org-toml").value }); },
    load: function () { return UI.store.get("setup", null); }
  };

  // ------------------------------------------------------------------ wiring
  async function init() {
    UI.bindEnginePill($("#engine-pill"));
    UI.tabs($("#where-tabs")).select("inrepo");
    $$("input[name=start]").forEach(function (r) { r.addEventListener("change", function () { $("#load-existing").hidden = r.value !== "edit" || !r.checked; }); });
    UI.dropZone($("#toml-drop"), $("#toml-file"), async function (files) { loadToml(await UI.readFile(files[0]), files[0].name); });
    $("#toml-load").addEventListener("click", function () { if ($("#toml-paste").value.trim()) loadToml($("#toml-paste").value); });
    $$("[data-proj]").forEach(function (el) { el.addEventListener("input", function () { state.project[el.dataset.proj] = el.value; refresh(); }); });
    $("#f-oos").addEventListener("input", function () { state.project.out_of_scope = $("#f-oos").value.split("\n").map(function (s) { return s.trim(); }).filter(Boolean); refresh(); });
    $("#add-hot").addEventListener("click", function () { state.zones.push({ name: "", paths: [], criticality: "hot" }); renderZones(); });
    $("#add-cold").addEventListener("click", function () { state.zones.push({ name: "", paths: [], criticality: "cold" }); renderZones(); });
    $("#add-wover").addEventListener("click", function () {
      var id = info.catalog.benchmarks.map(function (b) { return b.id; }).find(function (x) { return !(x in state.weights.overrides); });
      state.weights.overrides[id] = { weight: 3, reason: "" }; renderOverrides(); refresh();
    });
    $("#add-tover").addEventListener("click", function () {
      state.targets.overrides = state.targets.overrides || {};
      var id = info.catalog.benchmarks.map(function (b) { return b.id; }).find(function (x) { return !(x in state.targets.overrides); });
      state.targets.overrides[id] = 10; renderOverrides(); refresh();
    });
    $("#extra-gate").addEventListener("change", function (e) { if (e.target.value) { state.gates.extra = (state.gates.extra || []).concat([e.target.value]); renderOverrides(); refresh(); } });
    $("#t-mode").addEventListener("change", function () {
      var m = $("#t-mode").value; $("#t-level-wrap").hidden = m !== "level";
      state.targets.mode = m === "level" ? "level:" + $("#t-level").value : m; refresh();
    });
    $("#t-level").addEventListener("change", function () { state.targets.mode = "level:" + $("#t-level").value; refresh(); });
    $("#agent-decisions").addEventListener("change", function (e) { state.review = state.review || {}; state.review.allow_agent_decisions = e.target.checked; refresh(); });
    $("#org-toml").addEventListener("input", UI.debounce(async function () { await loadInfo(); renderAll(); refresh(); }, 600));
    $("#dl-toml").addEventListener("click", function () { if (lastToml) UI.download("project.toml", lastToml); });
    $("#copy-toml").addEventListener("click", function () { if (lastToml) UI.copyText(lastToml); });
    $("#zone-test").addEventListener("input", UI.debounce(async function () {
      var path = $("#zone-test").value.trim(); var out = $("#zone-test-out");
      if (!path) { out.textContent = ""; return; }
      try {
        var r = (await GK.call("zone_test", { project: projectData(), org_toml: $("#org-toml").value || null, paths: [path] })).results[0];
        UI.clear(out).appendChild(h("span", null, h("span", { class: "badge " + (r.criticality === "hot" ? "hot" : r.criticality === "cold" ? "cold" : "") }, r.criticality), r.zone ? " via zone “" + r.zone + "”" : " (no zone matched)"));
      } catch (err) { out.textContent = err.message; }
    }, 250));

    var saved = store.load();
    try {
      await loadInfo(saved && saved.org);
    } catch (err) { showEngineError(err); return; }
    if (saved && saved.state) {
      state = saved.state; extras = saved.extras || {}; $("#org-toml").value = saved.org || "";
      Object.keys(info.questions).forEach(function (q) { if (!(q in state.answers)) state.answers[q] = presetAnswer(q); });
    } else {
      applyPreset("default", false);
    }
    $("#codeowners").textContent = info.codeowners_hint;
    $("#dl-readme").addEventListener("click", function () { UI.download("README.md", info.grading_readme); });
    renderAll(); refresh();
    var reset = h("button", { type: "button", class: "btn", style: "margin-left:auto" }, "Start over");
    reset.addEventListener("click", function () { if (confirmReset()) { state = blank(); extras = {}; $("#org-toml").value = ""; applyPreset("default", false); renderAll(); refresh(); } });
    $("#setup-form .card .seg").parentNode.appendChild(h("div", { class: "row-btns", style: "margin-top:12px" }, h("span", { class: "kbd-note" }, "Your answers are remembered in this browser."), reset));
  }
  function confirmReset() { return window.confirm ? window.confirm("Clear the form and start over?") : true; }

  async function loadInfo(org) {
    info = await GK.call("info", { org_toml: (org !== undefined ? org : $("#org-toml").value) || null });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
