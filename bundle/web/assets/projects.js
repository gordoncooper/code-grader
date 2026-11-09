// Code Grading Suite: the Projects page. Reads a grading repo's projects/index.json (written by `gradekit index`)
// and shows every project (H3), what's waiting on whom (H5), trends and a benchmark heatmap (U5), and every
// pending decision across projects (H4). The numbers all come from gradekit; this page only draws them.
(function () {
  "use strict";
  var h = UI.h, $ = UI.$;
  var IDX = null, SRC = null, PRS = null, NAMES = null, selected = null;
  var answers = {};   // project → action_id → {choice, answer}
  var tabs = null;
  var STAGES = ["set up", "grade", "decide", "improve", "check", "done"];
  var want = null;   // a deep link's view: {tab, project}, applied once the index is loaded

  // ------------------------------------------------------------------ links (U6)
  // This page: ?repo=&ref= (or ?sample=1) and #tab=&project=. Review: the same source, a project, a report, a view.
  function sourceQuery() {
    var q = new URLSearchParams();
    if (SRC && SRC.kind === "github") { q.set("repo", SRC.at.owner + "/" + SRC.at.repo); q.set("ref", SRC.at.ref); }
    else if (SRC && SRC.kind === "sample") q.set("sample", "1");
    return q;
  }
  function remember(view) {
    var q = sourceQuery().toString(), hv = new URLSearchParams();
    Object.keys(view).forEach(function (k) { if (view[k]) hv.set(k, view[k]); });
    try { history.replaceState(null, "", location.pathname + (q ? "?" + q : "") + (hv.toString() ? "#" + hv : "")); } catch (e) { /* file:// */ }
  }
  // A link into Review for a project (and a report and a view), or null when the index came from a file.
  function reviewHref(name, folder, view) {
    if (!SRC || SRC.kind === "file") return null;
    var q = sourceQuery(); q.set("project", name);
    if (folder) q.set("report", folder);
    var hv = new URLSearchParams(); Object.keys(view || {}).forEach(function (k) { if (view[k]) hv.set(k, view[k]); });
    return "review.html?" + q + (hv.toString() ? "#" + hv : "");
  }
  var PILLARS = ["A", "B", "C", "D", "E", "F", "X"];

  // ------------------------------------------------------------------ loading
  function status(kind, o) { return kind ? UI.show($("#pj-status"), kind, o) : UI.clear($("#pj-status")); }

  function accept(index, src) {
    if (!index || !Array.isArray(index.projects)) throw new Error("this isn't a grading repo index: it has no \"projects\" list (make one with `gradekit index`)");
    IDX = index; SRC = src; answers = {};
    selected = (index.projects[0] || {}).name || null;
    status(null);
    $("#pj-results").hidden = false;
    var v = want || {}; want = null;
    if (v.project && project(v.project)) selected = v.project;
    render();
    var tab = ["all", "decisions", "project"].indexOf(v.tab) >= 0 ? v.tab : "all";
    tabs.select(tab);
    remember({ tab: tab, project: tab === "project" ? selected : null });
  }

  async function loadRepo() {
    var p = UI.gh.parseRepo($("#pj-repo").value);
    if (!p) { status("error", { title: "Enter the grading repo", message: "As owner/repo or a github.com URL." }); return; }
    UI.store.set("pj", { repo: $("#pj-repo").value, ref: $("#pj-ref").value });
    status("loading", { title: "Loading " + p.owner + "/" + p.repo + "…", skeleton: 3 });
    try {
      var at = await UI.gh.at(p.owner, p.repo, $("#pj-ref").value.trim() || (p.kind === "tree" ? decodeURIComponent(p.rest) : ""));
      var text;
      try { text = await UI.gh.getText(at.raw("projects/index.json")); }
      catch (e) {
        if (e.status === 404) throw new Error("projects/index.json isn't in " + p.owner + "/" + p.repo + " on " + at.ref + ". CI writes it once a report is merged (`gradekit index`); run that command to make it now.");
        throw e;
      }
      PRS = null;
      UI.gh.getJSON("https://api.github.com/repos/" + p.owner + "/" + p.repo + "/pulls?state=open&per_page=100")
        .then(function (list) { PRS = list; if (IDX) renderProject(); }, function () { PRS = []; });
      accept(JSON.parse(text), { kind: "github", at: at, label: p.owner + "/" + p.repo + " @ " + at.ref });
    } catch (err) { status("error", { title: "Couldn't load the index", message: err.message, retry: loadRepo }); }
  }

  async function loadFile(files) {
    try { accept(JSON.parse(await UI.readFile(files[0])), { kind: "file", label: files[0].name }); }
    catch (err) { status("error", { title: "Couldn't read " + files[0].name, message: err.message }); }
  }

  async function loadSample() {
    status("loading", { title: "Loading the sample grading repo…" });
    try {
      var r = await fetch(new URL("suite/examples/grading-repo/projects/index.json", GK.site).href);
      if (!r.ok) throw new Error("the sample isn't on this site (" + r.status + ")");
      accept(await r.json(), { kind: "sample", label: "the sample grading repo" });
      UI.tour.done("projects");
    } catch (err) { status("error", { title: "Couldn't load the sample", message: err.message, retry: loadSample }); }
  }

  // Benchmark names for the heatmap, from the kit's catalog on this site (the IDs work without it).
  async function names() {
    if (NAMES) return NAMES;
    try {
      var c = await (await fetch(new URL("suite/rubric/catalog.json", GK.site).href)).json();
      NAMES = {}; c.benchmarks.forEach(function (b) { NAMES[b.id] = b.name; });
    } catch (e) { NAMES = {}; }
    return NAMES;
  }

  // ------------------------------------------------------------------ charts
  var tip = null;
  function showTip(text, x, y) {
    tip = tip || document.body.appendChild(h("div", { class: "chart-tip", role: "tooltip" }));
    tip.textContent = text; tip.hidden = false;
    tip.style.left = Math.min(x + 12, window.innerWidth - tip.offsetWidth - 8) + "px";
    tip.style.top = (y - 34) + "px";
  }
  function hideTip() { if (tip) tip.hidden = true; }

  // A line of scores (0–10) over reports. points: [{value, label}]. Hover or focus a point for its value.
  function lineChart(points, o) {
    o = o || {};
    var W = o.w || 220, H = o.h || 70, pad = o.pad == null ? 6 : o.pad, left = o.grid ? 16 : pad;
    var vals = points.map(function (p) { return p.value; }).filter(function (v) { return v != null; });
    // A sparkline shows the shape of its own range (at least 2 points tall); a chart with a grid keeps 0–10.
    var lo = o.grid ? 0 : Math.max(0, Math.min.apply(null, vals) - 1), hi = o.grid ? 10 : Math.min(10, Math.max.apply(null, vals) + 1);
    if (hi - lo < 2) { lo = Math.max(0, hi - 2); hi = lo + 2; }
    var xs = function (i) { return points.length < 2 ? (left + W - pad) / 2 : left + i * (W - left - pad) / (points.length - 1); };
    var ys = function (v) { return H - pad - ((v - lo) / (hi - lo)) * (H - 2 * pad); };
    var kids = [];
    if (o.grid) [0, 5, 10].forEach(function (g) {
      kids.push(UI.svg("line", { class: "grid", x1: left, x2: W, y1: ys(g), y2: ys(g) }));
      kids.push(UI.svg("text", { x: 0, y: ys(g) + 3 }, String(g)));
    });
    if (o.target != null) kids.push(UI.svg("line", { class: "target", x1: left, x2: W, y1: ys(o.target), y2: ys(o.target) }));
    var pts = points.map(function (p, i) { return p.value == null ? null : [xs(i), ys(p.value)]; });
    var d = "", pen = false;
    pts.forEach(function (q) { if (!q) { pen = false; return; } d += (pen ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1); pen = true; });
    if (d) kids.push(UI.svg("path", { class: "line", d: d }));
    points.forEach(function (p, i) {
      if (!pts[i]) return;
      var text = p.label + ": " + p.value;
      var last = i === points.length - 1;
      if (o.interactive) {
        var hit = UI.svg("circle", { class: "hit", cx: pts[i][0], cy: pts[i][1], r: 10, tabindex: 0, role: "img", "aria-label": text,
          onmouseenter: function (e) { showTip(text, e.clientX, e.clientY); }, onmousemove: function (e) { showTip(text, e.clientX, e.clientY); },
          onmouseleave: hideTip, onfocus: function () { var r = hit.getBoundingClientRect(); showTip(text, r.right, r.top); }, onblur: hideTip });
        kids.push(hit);
      }
      if (o.interactive || last) kids.push(UI.svg("circle", { class: "dot", cx: pts[i][0], cy: pts[i][1], r: last ? 4 : 3 }));
    });
    return UI.svg("svg", { class: "chart", viewBox: "0 0 " + W + " " + H, role: o.interactive ? "group" : null,
                           "aria-label": o.label || null, "aria-hidden": o.interactive ? null : "true" }, kids);
  }

  // ------------------------------------------------------------------ helpers
  function full(p) { return (p.history || []).filter(function (r) { return r.mode !== "pr"; }); }
  function levelBadge(l) { return UI.badge(l || "–", l === "L0" ? "bad" : l === "L1" ? "warn" : l ? "ok" : null); }
  function stageBadge(c) { return UI.badge((c && c.stage) || "–", c && c.stage === "decide" ? "warn" : c && c.stage === "done" ? "ok" : "info"); }
  function plural(n, w) { return n + " " + w + (n === 1 ? "" : "s"); }
  function project(name) { return IDX.projects.filter(function (p) { return p.name === name; })[0]; }
  function choose(name) { selected = name; renderProject(); tabs.select("project"); remember({ tab: "project", project: name }); }

  // ------------------------------------------------------------------ all projects (H3)
  function renderAll() {
    var box = UI.clear($("#panel-all"));
    var ps = IDX.projects.slice();
    if (!ps.length) { box.appendChild(UI.state("empty", { title: "No projects yet", message: "Add one with Set up a project; its first report puts it here.", action: { label: "Set up a project", href: "setup.html" } })); return; }
    var order = { decide: 0, grade: 1, check: 2, improve: 3, done: 4 };
    ps.sort(function (a, b) { return (order[(a.cycle || {}).stage] - order[(b.cycle || {}).stage]) || a.name.localeCompare(b.name); });
    var waiting = ps.reduce(function (n, p) { return n + (p.pending_decisions || []).length; }, 0);
    var graded = ps.filter(function (p) { return p.latest; });
    box.appendChild(h("p", { class: "kbd-note" }, "From " + SRC.label + (IDX.suite_version ? " · index by suite " + IDX.suite_version : "") + ". Projects that need a person come first."));
    box.appendChild(h("div", { class: "stats-row" },
      h("div", { class: "stat" }, h("div", { class: "k" }, "Projects"), h("div", { class: "v" }, String(ps.length)), h("div", { class: "s" }, graded.length + " graded")),
      h("div", { class: "stat" }, h("div", { class: "k" }, "Decisions waiting"), h("div", { class: "v" }, String(waiting)), h("div", { class: "s" }, "across " + plural(ps.filter(function (p) { return (p.pending_decisions || []).length; }).length, "project"))),
      h("div", { class: "stat" }, h("div", { class: "k", dataset: { term: "maturity level" } }, "Production-ready"), h("div", { class: "v" }, String(graded.filter(function (p) { return /^L[34]$/.test(p.latest.level || ""); }).length)), h("div", { class: "s" }, "at L3 or L4")),
      spendStat(ps)));
    box.appendChild(UI.table({ cls: "proj-table", caption: "Every project", rows: ps, columns: [
      { label: "Project", cell: function (p) {
          var rv = reviewHref(p.name);
          return h("span", null, h("button", { type: "button", class: "link name", onclick: function () { choose(p.name); } }, p.name),
                   rv ? h("a", { class: "btn sm ml-2", href: rv, "aria-label": "Review " + p.name }, "Review") : null);
        } },
      { label: "Overall", cls: "num", cell: function (p) { return p.latest && p.latest.overall != null ? String(p.latest.overall) : "–"; } },
      { label: "Level", cell: function (p) { return p.latest ? levelBadge(p.latest.level) : UI.badge("not graded"); } },
      { label: "Trend", cls: "spark", cell: function (p) {
          var f = full(p);
          if (f.length < 2) return h("span", { class: "kbd-note" }, f.length ? "one report" : "–");
          return h("span", null, lineChart(f.map(function (r) { return { value: r.overall, label: r.date }; }), { w: 120, h: 32, pad: 4 }),
                   h("span", { class: "sr-only" }, "Overall " + f.map(function (r) { return r.overall; }).join(", then ")));
        } },
      { label: "Stage", cell: function (p) { return stageBadge(p.cycle); } },
      { label: "Waiting on", cell: function (p) {
          var w = (p.cycle || {}).waiting_on || [];
          return w.length ? h("span", { class: "small" }, w.map(function (x) { return x.who + ": " + x.what; }).join("; ")) : h("span", { class: "kbd-note" }, "nothing");
        } },
      { label: "Graded", cell: function (p) {
          var sch = UI.scheduleOf(p), last = full(p).slice(-1)[0], u = last && UI.usageParts(last.usage);
          return h("div", { class: "small" }, p.latest ? p.latest.date : "–",
            u && u.length ? h("span", { class: "kbd-note" }, " · " + u.filter(function (x) { return !/tokens/.test(x); }).join(" · ")) : null,
            sch ? h("div", null, sch.due ? UI.badge("due" + (sch.onlyIfChanged ? " if the code changed" : ""), "warn") : h("span", { class: "kbd-note" }, "next " + sch.next)) : null);
        } }
    ] }));
    var problems = ps.filter(function (p) { return (p.problems || []).length; });
    problems.forEach(function (p) { box.appendChild(UI.banner("warn", h("b", null, p.name + ": "), p.problems.join("; "))); });
  }

  // Agent time and cost over the last 30 days, from every report that recorded them.
  function spendStat(ps) {
    var since = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10), runs = [];
    ps.forEach(function (p) { (p.history || []).forEach(function (r) { if (r.date >= since) runs.push(r.usage || {}); }); });
    var t = UI.usageTotals(runs);
    return h("div", { class: "stat" }, h("div", { class: "k" }, "Agent time, 30 days"),
      h("div", { class: "v" }, t.timed ? UI.fmtMinutes(t.minutes) : "–"),
      h("div", { class: "s" }, !t.runs ? "no reports in 30 days" : [plural(t.runs, "report"), t.priced ? UI.fmtCost(t.cost) + (t.priced < t.runs ? " (" + t.priced + " priced)" : "") : "cost not recorded",
                                  t.timed && t.timed < t.runs ? t.timed + " timed" : null].filter(Boolean).join(" · ")));
  }

  // Time and cost of every run of one project (N3).
  function costCard(p) {
    var runs = (p.history || []).slice().reverse();
    var card = UI.card({ title: "Time and cost", small: true, cls: "mt-4",
      hint: "What each grading run took, as its report recorded it (run.usage). Graders record minutes automatically; tokens and cost when their tools report them." });
    if (!runs.some(function (r) { return r.usage; })) {
      card.appendChild(UI.state("empty", { title: "Not recorded yet", message: "Reports from 5.0 graders record how long they took. Older reports don't." }));
      return card;
    }
    var grades = runs.filter(function (r) { return r.mode !== "pr"; }), t = UI.usageTotals(grades.map(function (r) { return r.usage; }));
    if (t.timed) card.appendChild(h("p", { class: "small" }, "A full grade takes about ", h("b", null, UI.fmtMinutes(t.minutes / t.timed)),
      t.priced ? h("span", null, " and costs about ", h("b", null, UI.fmtCost(t.cost / t.priced))) : null, " (average of " + plural(t.timed, "full grade") + ")."));
    card.appendChild(UI.table({ caption: "Time and cost by report", rows: runs, columns: [
      { label: "Report", cell: function (r) { return r.date + " · " + r.commit + (r.mode === "pr" ? " (PR check)" : ""); } },
      { label: "Model", cell: function (r) { return r.model ? h("code", null, r.model) : "–"; } },
      { label: "Time", cls: "num", cell: function (r) { return UI.fmtMinutes((r.usage || {}).minutes) || "–"; } },
      { label: "Tokens", cls: "num", cell: function (r) { var u = r.usage || {}; return UI.usageParts({ tokens_in: u.tokens_in, tokens_out: u.tokens_out })[0] || "–"; } },
      { label: "Cost", cls: "num", cell: function (r) { return UI.fmtCost((r.usage || {}).cost_usd) || "–"; } }
    ] }));
    return card;
  }

  // ------------------------------------------------------------------ one project: cycle (H5), trends and heatmap (U5)
  function prsFor(name) {
    if (!PRS) return null;
    var re = new RegExp("^(report|decisions|migrate|disputes|orders)/" + name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "/");
    return PRS.filter(function (pr) { return pr.head && re.test(pr.head.ref); });
  }

  async function renderProject() {
    var box = UI.clear($("#panel-project"));
    if (!IDX || !IDX.projects.length) { box.appendChild(UI.state("empty", { title: "No projects yet" })); return; }
    var pick = h("select", { "aria-label": "Project", class: "w-auto ml-2", onchange: function () { selected = pick.value; renderProject(); remember({ tab: "project", project: selected }); } },
      IDX.projects.map(function (p) { return h("option", { value: p.name, selected: p.name === selected }, p.name); }));
    var p = project(selected) || IDX.projects[0];
    var rv = reviewHref(p.name);
    box.appendChild(h("div", { class: "row-btns" }, h("label", { class: "label" }, "Project", pick), rv ? h("a", { class: "btn sm ml-auto", href: rv }, "Open in Review") : null));
    var f = full(p);

    // the cycle
    var stage = (p.cycle || {}).stage, at = STAGES.indexOf(stage);
    var cyc = UI.card({ title: "Where it stands", small: true },
      h("ol", { class: "cycle-steps", "aria-label": "The cycle" }, STAGES.map(function (s, i) {
        return h("li", { class: i === at ? "now" : i < at ? "done" : null, "aria-current": i === at ? "step" : null }, s);
      })),
      ((p.cycle || {}).waiting_on || []).length
        ? h("ul", { class: "waiting" }, p.cycle.waiting_on.map(function (w) { return h("li", null, h("b", null, w.who + ": "), w.what); }))
        : h("p", { class: "kbd-note mt-2" }, "Nothing is waiting: every benchmark is at its target."));
    var prs = prsFor(p.name);
    if (SRC.kind === "github") {
      cyc.appendChild(h("h3", { class: "sub-h" }, "Open pull requests"));
      if (prs === null) cyc.appendChild(UI.state("loading", { title: "Looking up pull requests…" }));
      else if (!prs.length) cyc.appendChild(h("p", { class: "kbd-note" }, "None for this project."));
      else cyc.appendChild(h("ul", { class: "list-tight" }, prs.map(function (pr) { return h("li", null, h("a", { href: pr.html_url }, "#" + pr.number + " " + pr.title), " ", h("code", null, pr.head.ref)); })));
    } else {
      cyc.appendChild(h("p", { class: "kbd-note mt-2" }, "Load the index from a GitHub grading repo to see its open pull requests. On another host, look for branches named report/" + p.name + "/… and decisions/" + p.name + "/…"));
    }
    var sch = UI.scheduleOf(p);
    cyc.appendChild(h("p", { class: "kbd-note mt-2" }, sch
      ? "Graded every " + plural(sch.every, "day") + (sch.onlyIfChanged ? " when the code has changed" : "") + ": " +
        (sch.due ? "due now. The grading CI's scheduled job writes a work order." : "next on " + sch.next + ".")
      : "No schedule: grades happen when someone asks. Set one under [schedule] in project.toml."));
    box.appendChild(cyc);
    box.appendChild(costCard(p));

    if (!f.length) { box.appendChild(UI.state("empty", { title: "No full report yet", message: "The first grade puts its scores here." })); return; }

    // trends: overall and one small chart per pillar, same 0–10 scale
    var trend = UI.card({ title: "Trends", small: true, hint: f.length < 2 ? "One report so far: the lines start with the next one." : "Scores over " + f.length + " full reports, oldest first. Hover or tab to a point for its value." , cls: "mt-4" });
    var multiples = h("div", { class: "multiples" });
    function multiple(title, values) {
      var last = values.filter(function (v) { return v.value != null; }).slice(-1)[0];
      multiples.appendChild(h("div", { class: "multiple" }, h("h3", null, title, h("b", null, last ? String(last.value) : "–")),
        lineChart(values, { grid: true, interactive: true, label: title + ": " + values.map(function (v) { return v.label + " " + (v.value == null ? "–" : v.value); }).join(", ") })));
    }
    multiple("Overall", f.map(function (r) { return { value: r.overall, label: r.date }; }));
    PILLARS.forEach(function (pl) {
      if (!f.some(function (r) { return r.pillars && r.pillars[pl] != null; })) return;
      multiple("Pillar " + pl, f.map(function (r) { return { value: (r.pillars || {})[pl], label: r.date }; }));
    });
    trend.appendChild(multiples);
    trend.appendChild(h("h3", { class: "sub-h" }, "Maturity"));
    trend.appendChild(h("div", { class: "levels" }, f.map(function (r) { return h("span", null, levelBadge(r.level), " ", h("span", { class: "kbd-note" }, r.date)); })));
    var tbl = h("details", { class: "mt-3" }, h("summary", null, "Show the numbers"),
      UI.table({ caption: "Overall and pillar scores by report", rows: f, columns: [{ label: "Report", cell: function (r) { return r.date + " · " + r.commit; } },
        { label: "Overall", cell: function (r) { return r.overall == null ? "–" : String(r.overall); } },
        { label: "Level", cell: function (r) { return r.level || "–"; } }].concat(PILLARS.map(function (pl) {
          return { label: pl, cell: function (r) { var v = (r.pillars || {})[pl]; return v == null ? "–" : String(v); } };
        })) }));
    trend.appendChild(tbl);
    box.appendChild(trend);

    // the heatmap: benchmarks × reports
    var nm = await names();
    var ids = Object.keys(f[f.length - 1].scores || {});
    if (!ids.length) { box.appendChild(UI.card({ title: "Every benchmark", small: true, cls: "mt-4" }, UI.state("empty", { title: "This index has no benchmark scores", message: "Rebuild it with a 5.0 kit (`gradekit index`) to see them." }))); return; }
    var rows = [];
    PILLARS.forEach(function (pl) {
      var mine = ids.filter(function (id) { return id.charAt(0) === pl; });
      if (!mine.length) return;
      rows.push(h("tr", null, h("th", { scope: "rowgroup", colspan: String(f.length + 1), class: "bench" }, "Pillar " + pl)));
      mine.forEach(function (id) {
        rows.push(h("tr", null, h("th", { scope: "row", class: "bench" }, h("code", null, id), nm[id] ? " " + nm[id] : ""),
          f.map(function (r) {
            var v = (r.scores || {})[id];
            var num = typeof v === "number";
            var label = num ? String(v) : (v === "n/a" ? "n/a" : "–"), href = num ? reviewHref(p.name, r.folder, { bench: id }) : null;
            return h("td", { class: num ? "s" + Math.max(1, Math.min(10, Math.round(v))) : null,
                             title: id + (nm[id] ? " " + nm[id] : "") + " · " + r.date + ": " + (v == null ? "not scored" : v) },
                     href ? h("a", { class: "cell-link", href: href, "aria-label": id + " in the report of " + r.date + ": " + v + ". Open in Review" }, label) : label);
          })));
      });
    });
    var legend = h("div", { class: "heat-legend", "aria-hidden": "true" }, "Score ",
      [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(function (n) { return h("i", { class: "s" + n }, String(n)); }));
    box.appendChild(UI.card({ title: "Every benchmark", small: true, cls: "mt-4", hint: "Each column is a full report, oldest first. Darker means a higher score; n/a means not applicable." },
      legend,
      h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Benchmark scores by report" }, h("table", { class: "heat" },
        h("caption", { class: "sr-only" }, "Benchmark scores by report"),
        h("thead", null, h("tr", null, h("th", { scope: "col" }, "Benchmark"), f.map(function (r) { return h("th", { scope: "col" }, r.date); }))),
        h("tbody", null, rows)))));
  }

  // ------------------------------------------------------------------ decisions inbox (H4)
  function renderDecisions() {
    var box = UI.clear($("#panel-decisions"));
    var ps = IDX.projects.filter(function (p) { return (p.pending_decisions || []).length; });
    var n = ps.reduce(function (k, p) { return k + p.pending_decisions.length; }, 0);
    var cnt = $("#pj-dec-count"); cnt.hidden = !n; cnt.textContent = String(n);
    if (!ps.length) { box.appendChild(UI.state("empty", { title: "No decisions waiting", message: "When a report asks a person to decide something, it shows up here." })); return; }
    var who = h("input", { type: "text", placeholder: "you@example.com", value: UI.store.get("decider", ""), class: "maxw-sm" });
    who.addEventListener("input", function () { UI.store.set("decider", who.value.trim()); });
    box.appendChild(h("p", { class: "hint muted" }, "Some fixes need a person's call: they change behavior, drop a feature, or touch a public interface. Improving agents skip them until they're approved. Answer what you can; each project's answers become its decisions.json."));
    box.appendChild(UI.field({ label: "Your name or email", control: who, help: "Recorded with each answer." }));
    ps.forEach(function (p) {
      answers[p.name] = answers[p.name] || {};
      var out = h("div", { class: "mt-3" });
      var card = UI.card({ title: p.name, small: true, cls: "inbox-project", hint: plural(p.pending_decisions.length, "decision") + " from the report of " + (p.latest ? p.latest.date : "?") + "." });
      p.pending_decisions.forEach(function (d) {
        var a = answers[p.name][d.action_id] = answers[p.name][d.action_id] || { choice: "later", answer: "" };
        var txt = h("textarea", { rows: "2", placeholder: "Optional: your answer or conditions", "aria-label": "Answer to " + d.action_id });
        txt.value = a.answer;
        txt.addEventListener("input", function () { a.answer = txt.value; });
        var seg = UI.seg("dec-" + p.name + "-" + d.action_id, [{ value: "approve", label: "Approve" }, { value: "decline", label: "Decline" }, { value: "later", label: "Later" }],
          a.choice, function (v) { a.choice = v; }, "Answer to " + d.action_id);
        card.appendChild(h("div", { class: "decision" },
          h("div", { class: "meta" }, d.benchmark_id ? UI.chip(d.benchmark_id) : null, " ", h("code", null, d.action_id)),
          h("p", { class: "q" }, UI.inline(d.question || "")),
          d.action ? h("p", { class: "act" }, "If approved: ", UI.inline(d.action)) : null,
          seg, h("div", { class: "mt-2" }, txt)));
      });
      card.appendChild(h("div", { class: "row-btns mt-3" }, h("button", { type: "button", class: "btn primary", onclick: function () { save(p, out); } }, "Save answers for " + p.name)));
      card.appendChild(out);
      box.appendChild(card);
    });
  }

  async function save(p, out) {
    var date = new Date().toISOString().slice(0, 10), who = UI.store.get("decider", "") || "<your name>";
    var chosen = p.pending_decisions.filter(function (d) { return answers[p.name][d.action_id].choice !== "later"; });
    if (!chosen.length) { UI.show(out, "empty", { title: "Nothing to save yet", message: "Choose Approve or Decline on at least one question." }); return; }
    var decisions = chosen.map(function (d) {
      var a = answers[p.name][d.action_id];
      var e = { action_id: d.action_id, question: d.question, approved: a.choice === "approve" };
      if (a.answer.trim()) e.answer = a.answer.trim();
      e.decided_by = who; e.date = date;
      return e;
    });
    UI.show(out, "loading", { title: "Writing decisions.json…", message: "The first time, this starts the engine." });
    var existing = null;
    if (SRC.kind === "github") {
      try { existing = await UI.gh.getText(SRC.at.raw("projects/" + p.name + "/decisions.json")); }
      catch (e) { if (e.status === 404) existing = ""; }
    }
    var gh = SRC.kind === "github" ? SRC.at : null;
    var open = (prsFor(p.name) || []).filter(function (pr) { return /^report\//.test(pr.head.ref); })[0];
    await UI.saveDecisions(out, { project: p.name, decisions: decisions, existing: existing,
                                  repo: gh ? gh.owner + "/" + gh.repo : null, branch: open ? open.head.ref : null });
  }

  // ------------------------------------------------------------------
  function render() { renderAll(); renderDecisions(); renderProject(); UI.terms($("#pj-results")); }

  document.addEventListener("DOMContentLoaded", function () {
    UI.tabs($("#load-tabs")).select("repo");
    tabs = UI.tabs($("#pj-tabs"));
    UI.palette.add(function () {
      if (!IDX) return [{ group: "This page", label: "Open the sample grading repo", run: loadSample }];
      var out = [["all", "All projects"], ["decisions", "Decisions waiting"], ["project", "One project"]].map(function (t) {
        return { group: "This page", label: "Go to " + t[1], keywords: "tab", run: function () { tabs.select(t[0]); remember({ tab: t[0], project: t[0] === "project" ? selected : null }); } };
      });
      IDX.projects.forEach(function (p) {
        out.push({ group: "Projects", label: p.name, hint: [p.latest ? (p.latest.overall == null ? "–" : p.latest.overall) + " · " + p.latest.level : "not graded", (p.cycle || {}).stage].filter(Boolean).join(" · "),
                   keywords: "project " + (p.description || ""), run: function () { choose(p.name); } });
      });
      return out;
    });
    $("#pj-tabs").addEventListener("click", function (e) {
      var t = e.target.closest("button[data-tab]"); if (t) remember({ tab: t.dataset.tab, project: t.dataset.tab === "project" ? selected : null });
    });
    var saved = UI.store.get("pj", null);
    if (saved) { $("#pj-repo").value = saved.repo || ""; $("#pj-ref").value = saved.ref || ""; }
    $("#pj-load").addEventListener("click", loadRepo);
    $("#pj-repo").addEventListener("keydown", function (e) { if (e.key === "Enter") loadRepo(); });
    UI.dropZone($("#pj-drop"), $("#pj-file"), loadFile);
    $("#pj-sample").addEventListener("click", loadSample);
    var q = new URLSearchParams(location.search), hv = new URLSearchParams(location.hash.slice(1));
    want = { tab: hv.get("tab"), project: hv.get("project") };
    if (q.get("repo")) { $("#pj-repo").value = q.get("repo"); $("#pj-ref").value = q.get("ref") || ""; loadRepo(); }
    else if (q.get("sample")) loadSample();
  });
})();
