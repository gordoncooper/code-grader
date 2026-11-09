// Code Grading Suite: "Review a report" page.
(function () {
  "use strict";
  var h = UI.h, $ = UI.$, $$ = UI.$$;
  var ROLES = { report: "Report to review", previous: "Earlier report (compare)", run: "Another run (consensus)",
                project: "project.toml", decisions: "decisions.json", dispositions: "dispositions.json",
                org: "org.toml", zip: "Code archive (.zip, for citations)", ignore: "Ignore" };
  var TIERS = ["Fix first", "Unblocks the next level", "Below target", "Optional"];
  var files = [];     // {id, name, role, text, bytes, json, fromSource}
  var pendingPicker = null;  // "pick a project" banner, kept across renderFiles() until a project is chosen
  var source = null;  // a project loaded as a whole: {label, project, meta, history: [{folder, get(), runs()}]}
  var sel = { report: -1, compare: -1 };
  var info = null;    // catalog etc.
  var R = null;       // current analysis
  var answers = {};   // action_id -> {choice, answer}
  var fileSeq = 0;
  var resultTabs = null;
  // Deep links (U6): ?repo=&ref=&project=&report=&compare= pick the source and reports; #tab=&bench=&finding= the view.
  var want = { report: null, compare: null, view: null };
  var rubric = null;    // rubric anchors, from the kit on this site
  var histCache = {};   // folder → report, for per-benchmark history
  async function engineInfo() { if (!info) info = await GK.call("info", {}); return info; }

  function projectName() {
    return (source && source.project) || (R && R.report && R.report.run && R.report.run.project) || "<project>";
  }

  // ------------------------------------------------------------------ loose files
  // What each loose file is (report, earlier report, run, project.toml…) is decided by the engine
  // (gradekit classify_files), the same rule everywhere. A role the person picks is kept.
  function addFile(name, content, isBytes, role, fromSource) {
    var f = { id: ++fileSeq, name: name, fromSource: !!fromSource, chosen: !!role, role: role || "ignore" };
    if (isBytes) f.bytes = content; else f.text = content;
    if (!isBytes && /\.json$/i.test(name)) { try { f.json = JSON.parse(content); } catch (e) { f.error = "not valid JSON"; } }
    files.push(f);
    return f;
  }
  async function classifyFiles() {
    var loose = files.filter(function (f) { return !f.fromSource; });
    if (!loose.some(function (f) { return !f.chosen; })) return;
    var res = await GK.call("classify", { files: loose.map(function (f) {
      return { name: f.name, json: f.json || null, error: f.error || null, role: f.chosen ? f.role : null };
    }) });
    loose.forEach(function (f, i) { f.role = res.roles[i]; });
  }
  function byRole(role) { return files.filter(function (f) { return f.role === role; }); }

  function renderFiles() {
    var box = UI.clear($("#filelist"));
    if (pendingPicker) box.appendChild(pendingPicker);
    if (source) box.appendChild(h("div", { class: "filerow" }, h("div", { class: "name" }, h("b", null, source.project), h("small", null, source.history.length + " report(s) · " + source.label)), h("span", { class: "kbd-note" }, "Whole project"), h("span")));
    files.forEach(function (f) {
      if (f.fromSource && f.role !== "zip") return;
      var sel = h("select", { "aria-label": "Use " + f.name + " as" });
      Object.keys(ROLES).forEach(function (r) { var o = h("option", { value: r }, ROLES[r]); if (r === f.role) o.selected = true; sel.appendChild(o); });
      sel.addEventListener("change", function () { f.role = sel.value; f.chosen = true; updateAnalyzeButton(); });
      var del = h("button", { type: "button", class: "icon-btn", "aria-label": "Remove " + f.name }, "×");
      del.addEventListener("click", function () { files = files.filter(function (x) { return x !== f; }); renderFiles(); });
      var meta = f.error ? f.error : f.json && f.json.run ? "commit " + String(f.json.run.commit || "?").slice(0, 10) + (f.json.run.date ? " · " + f.json.run.date : "") : f.bytes ? Math.round(f.bytes.length / 1024) + " KB" : "";
      box.appendChild(h("div", { class: "filerow" }, h("div", { class: "name" }, f.name, h("small", null, meta)), sel, del));
    });
    updateAnalyzeButton();
  }
  function updateAnalyzeButton() { $("#analyze").disabled = !(source && source.history.length) && !files.some(function (f) { return f.role === "report"; }); }

  // ------------------------------------------------------------------ whole projects (folder, zip, GitHub, sample)
  // entries: [{path, text: async () => string}] — grouped into projects like gradekit's scan_paths().
  // Which projects a folder, zip or repo holds is decided by the engine (gradekit scan_layout) from the
  // paths alone; files are read only once a project is chosen.
  async function scanEntries(entries) {
    var byPath = {};
    entries.forEach(function (e) { byPath[e.path] = e; });
    var res = await GK.call("scan_layout", { paths: Object.keys(byPath) });
    return res.projects.map(function (p) {
      var side = {}, reports = {};
      Object.keys(p.side).forEach(function (k) { side[k] = byPath[p.side[k]]; });
      Object.keys(p.reports).forEach(function (f) {
        reports[f] = { report: byPath[p.reports[f].report], runs: p.reports[f].runs.map(function (x) { return byPath[x]; }) };
      });
      return { name: p.name, key: p.root, side: side, reports: reports, org: p.org ? byPath[p.org] : null };
    });
  }

  // Oldest first, by the engine's rule (gradekit order_report_folders). It names the folders whose
  // run.date it needs (reports from the same day); only those are read.
  async function orderFolders(folders, runDate) {
    var res = await GK.call("order_reports", { folders: folders });
    if (!res.need_run_dates.length) return res.ordered;
    var dates = {};
    for (var i = 0; i < res.need_run_dates.length; i++) dates[res.need_run_dates[i]] = await runDate(res.need_run_dates[i]);
    return (await GK.call("order_reports", { folders: folders, run_dates: dates })).ordered;
  }

  async function useProject(p, label, meta) {
    pendingPicker = null;
    files = files.filter(function (f) { return !f.fromSource && ["project", "decisions", "dispositions", "org", "report", "previous", "run"].indexOf(f.role) < 0; });
    var SIDE = (await engineInfo()).side_files;
    for (var fname in p.side) addFile(fname, await p.side[fname].text(), false, SIDE[fname], true);
    if (p.org) addFile("org.toml", await p.org.text(), false, "org", true);
    var folders = await orderFolders(Object.keys(p.reports).filter(function (f) { return p.reports[f].report; }), function (f) {
      return p.reports[f].report.text().then(function (t) { try { return String((JSON.parse(t).run || {}).date || ""); } catch (e) { return ""; } }, function () { return ""; });
    });
    source = { label: label, project: p.name, meta: meta || {}, history: folders.map(function (f) {
      var r = p.reports[f];
      return { folder: f, get: async function () { return JSON.parse(await r.report.text()); },
               runs: async function () { var out = []; for (var i = 0; i < r.runs.length; i++) out.push(JSON.parse(await r.runs[i].text())); return out; } };
    }) };
    sel.report = source.history.length - 1; sel.compare = source.history.length - 2;
    var at = function (folder) { return source.history.map(function (x) { return x.folder; }).indexOf(folder); };
    if (want.report && at(want.report) >= 0) { sel.report = at(want.report); sel.compare = sel.report - 1; }
    if (want.compare && at(want.compare) >= 0) sel.compare = at(want.compare);
    else if (want.compare === "none") sel.compare = -1;
    want.report = want.compare = null;
    histCache = {};
    renderFiles();
    if (source.history.length) await analyze();   // finish before more dropped files (e.g. a code zip) are added
    else UI.toast("Loaded " + p.name + ": no reports yet");
  }

  async function chooseProject(projects, label, meta) {
    if (!projects.length) { UI.toast("No project found there: expected project.toml or reports/<date>/report.json"); return; }
    if (projects.length === 1) return useProject(projects[0], label, meta);
    var pick = h("select", { "aria-label": "Project" }, projects.map(function (p, i) { return h("option", { value: i }, p.name + " (" + Object.keys(p.reports).length + " reports)"); }));
    var go = h("button", { type: "button", class: "btn primary" }, "Load project");
    go.addEventListener("click", function () { useProject(projects[parseInt(pick.value, 10)], label, meta); });
    pendingPicker = UI.banner("info", "This contains several projects. Pick one: ", pick, " ", go);
    renderFiles();
  }

  async function onFiles(list) {
    var loose = [];
    for (var i = 0; i < list.length; i++) {
      var file = list[i];
      if (/\.zip$/i.test(file.name)) {
        var bytes = await UI.readFile(file, true);
        try {
          var path = await GK.putFile(bytes, ".zip");
          var scan = await GK.call("scan_zip", { zip_path: path });
          if (scan.kind === "grading") {
            var projects = Object.keys(scan.projects).map(function (name) { return zipProject(name, scan.projects[name]); });
            await chooseProject(projects, file.name);
            continue;
          }
        } catch (err) { UI.clear($("#engine-error")).appendChild(err.gk ? UI.banner("bad", err.message) : UI.engineHelp(err)); }
        addFile(file.name, bytes, true, "zip");
      } else {
        loose.push(file);
      }
    }
    for (var j = 0; j < loose.length; j++) addFile(loose[j].name, await UI.readFile(loose[j]));
    if (loose.length) {
      try { await classifyFiles(); }
      catch (err) { UI.clear($("#engine-error")).appendChild(err.gk ? UI.banner("bad", err.message) : UI.engineHelp(err)); }
    }
    renderFiles();
    if (loose.length && files.some(function (f) { return f.role === "report"; })) analyze();
    else if (R) analyze();
  }
  function zipProject(name, p) {
    var text = function (t) { return { text: async function () { return t; } }; };
    var side = {};
    if (p.project_toml) side["project.toml"] = text(p.project_toml);
    if (p.decisions_json) side["decisions.json"] = text(p.decisions_json);
    if (p.dispositions_json) side["dispositions.json"] = text(p.dispositions_json);
    var reports = {};
    p.reports.forEach(function (r) { reports[r.folder] = { report: text(r.report), runs: (r.runs || []).map(text) }; });
    return { name: name, side: side, reports: reports, org: p.org_toml ? text(p.org_toml) : null };
  }

  async function onFolder(list) {
    var entries = Array.prototype.map.call(list, function (f) {
      return { path: f.webkitRelativePath || f.name, text: function () { return UI.readFile(f); } };
    }).filter(function (e) { return /\.(json|toml)$/.test(e.path) || /(^|\/)tools\/gradekit\.py$/.test(e.path); });
    var top = (entries[0] && entries[0].path.split("/")[0]) || "folder";
    try { await chooseProject(await scanEntries(entries), "folder " + top); }
    catch (err) { UI.clear($("#engine-error")).appendChild(err.gk ? UI.banner("bad", err.message) : UI.engineHelp(err)); }
  }

  // ------------------------------------------------------------------ GitHub (public grading repos)
  var parseRepo = UI.gh.parseRepo, getJSON = UI.gh.getJSON, getText = UI.gh.getText;   // shared with Projects (common.js)

  async function loadGitHub() {
    var st = UI.clear($("#gh-status"));
    var say = function (msg, cls) { UI.clear(st).appendChild(UI.banner(cls || "info", msg)).classList.add("mt-3"); };
    var busy = function (msg) { UI.show(st, "loading", { title: msg }).classList.add("mt-3"); };
    var p = parseRepo($("#gh-repo").value);
    if (!p) { say("Enter the grading repo as owner/repo or a github.com URL.", "warn"); return; }
    var ref = $("#gh-ref").value.trim(), project = $("#gh-project").value.trim();
    var owner = p.owner, repo = p.repo;
    UI.store.set("gh", { repo: $("#gh-repo").value, project: project });
    try {
      busy("Looking up the repository…");
      if (p.kind === "tree" && !ref) ref = decodeURIComponent(p.rest);
      if (p.kind === "pull") {
        var pr = await getJSON("https://api.github.com/repos/" + owner + "/" + repo + "/pulls/" + parseInt(p.rest, 10));
        owner = pr.head.repo.owner.login; repo = pr.head.repo.name; ref = pr.head.ref;
        $("#gh-ref").value = ref;
        var m = ref.match(/^(?:report|decisions)\/([^\/]+)\//);
        if (m && !project) { project = m[1]; $("#gh-project").value = project; }
      }
      var repoAt = await UI.gh.at(owner, repo, ref);   // everything at one commit: a consistent snapshot
      ref = repoAt.ref;
      var sha = repoAt.sha, api = repoAt.api, raw = repoAt.raw;
      if (!project) {
        // projects/index.json (written by `gradekit index` in CI) lists them with their scores; else list the folder.
        var index = null;
        try { index = JSON.parse(await getText(raw("projects/index.json"))); } catch (e) { /* optional */ }
        var listed = null;
        if (!index) { try { listed = await getJSON(api("projects")); } catch (e) { if (e.status !== 404) throw e; } }
        var entries = index ? index.projects : (listed || []).filter(function (x) { return x.type === "dir"; }).map(function (x) { return { name: x.name }; });
        var label = function (p) {
          if (!p.latest) return p.history ? p.name + " (no report yet)" : p.name;
          var n = (p.pending_decisions || []).length;
          return p.name + " (" + p.latest.overall + ", " + p.latest.level + (n ? ", " + n + " decision" + (n > 1 ? "s" : "") + " waiting" : "") + ")";
        };
        var dl = UI.clear($("#gh-projects")); entries.forEach(function (p) { dl.appendChild(h("option", { value: p.name, label: label(p) })); });
        if (entries.length === 1) { project = entries[0].name; $("#gh-project").value = project; }
        else {
          say(entries.length ? h("span", null, "Pick a project:", h("ul", { class: "project-index" }, entries.map(function (p) {
                var b = h("button", { type: "button", class: "link" }, p.name);
                b.addEventListener("click", function () { $("#gh-project").value = p.name; loadGitHub(); });
                return h("li", null, b, label(p).slice(p.name.length));
              })))
            : (index || listed) ? "There are no projects in projects/ yet. Add one with Set up a project." : "No projects/ folder found in this repo.", entries.length ? "info" : "warn");
          return;
        }
      }
      busy("Loading " + project + "…");
      var base = "projects/" + project + "/";
      var listing = [];
      try { listing = await getJSON(api(base + "reports")); } catch (e) { if (e.status !== 404) throw e; }
      var folders = listing.filter(function (x) { return x.type === "dir"; }).map(function (x) { return x.name; });
      var side = {}, SIDE = (await engineInfo()).side_files;
      for (var fname in SIDE) {
        if (fname === "org.toml") continue;
        try { var t = await getText(raw(base + fname)); side[fname] = { text: (function (t) { return async function () { return t; }; })(t) }; } catch (e) { /* optional */ }
      }
      var org = null;
      try { var ot = await getText(raw("org.toml")); org = { text: async function () { return ot; } }; } catch (e) { /* optional */ }
      if (!side["project.toml"] && !folders.length) { say("Nothing found at projects/" + project + "/ on " + ref + ". Check the project name.", "warn"); return; }
      var reports = {};
      folders.forEach(function (f) {
        reports[f] = {
          report: { text: function () { return getText(raw(base + "reports/" + f + "/report.json")); } },
          lazyRuns: function () {
            // List the report folder first, so a missing runs/ folder doesn't cost a 404.
            return getJSON(api(base + "reports/" + f)).then(function (l) {
              if (!l.some(function (x) { return x.name === "runs" && x.type === "dir"; })) return [];
              return getJSON(api(base + "reports/" + f + "/runs")).then(function (r) { return r.filter(function (x) { return /\.json$/.test(x.name); }).map(function (x) { return { text: function () { return getText(x.download_url); } }; }); });
            }).catch(function () { return []; });
          }
        };
      });
      var proj = { name: project, side: side, org: org, reports: {} };
      folders.forEach(function (f) { proj.reports[f] = { report: reports[f].report, runs: [] }; });
      await useProject(proj, owner + "/" + repo + " @ " + ref, { owner: owner, repo: repo, ref: ref });
      source.history.forEach(function (hst) { hst.runs = async function () { var l = await reports[hst.folder].lazyRuns(); var out = []; for (var i = 0; i < l.length; i++) out.push(JSON.parse(await l[i].text())); return out; }; });
      say("Loaded " + project + " from " + owner + "/" + repo + " @ " + ref + (sha ? " (" + sha.slice(0, 7) + ")" : "") + ": " + folders.length + " report(s)" + (side["decisions.json"] ? ", decisions" : "") + (side["dispositions.json"] ? ", accepted findings" : "") + ".", "info");
    } catch (err) {
      say(err.limited ? err.message + "." : "Couldn't load from GitHub: " + err.message + ". Check that the repo is public and the project name is right, or download it and use Open files instead.", "bad");
    }
  }

  async function loadSample() {
    try {
      var manifest = await (await fetch(new URL("manifest.json", GK.site).href)).json();
      var prefix = "suite/examples/grading-repo/";
      var entries = manifest.files.filter(function (f) { return f.path.indexOf(prefix) === 0 && /\.(json|toml)$/.test(f.path); }).map(function (f) {
        return { path: f.path.slice(prefix.length), text: function () { return getText(new URL(f.path, GK.site).href); } };
      });
      await chooseProject(await scanEntries(entries), "the sample grading repo", { sample: true });
    } catch (err) { UI.toast("Couldn't load the sample: " + err.message); }
  }

  // ------------------------------------------------------------------ analysis
  async function analyze() {
    UI.clear($("#engine-error"));
    var status = $("#review-status");
    $("#analyze").disabled = true; $("#analyze").textContent = "Reviewing…";
    UI.show(status, "loading", { title: "Reviewing the report…", message: "Checking it against the project's settings; the first run also starts the engine.", skeleton: 3 });
    try {
      var current, prev = null, runs = [];
      if (source && source.history.length) {
        var hr = source.history[sel.report];
        current = await hr.get();
        runs = await hr.runs();
        if (sel.compare >= 0 && sel.compare !== sel.report) prev = await source.history[sel.compare].get();
        histCache[hr.folder] = current;
      }
      var looseReport = byRole("report")[0];
      if (!current && looseReport) current = looseReport.json;
      if (!current) return;
      if (!prev && byRole("previous")[0]) prev = byRole("previous")[0].json;
      runs = runs.concat(byRole("run").map(function (r) { return r.json; }));
      var text = function (role) { var f = byRole(role)[0]; return f ? f.text : null; };
      var base = { project_toml: text("project"), org_toml: text("org"), decisions_json: text("decisions"), dispositions_json: text("dispositions") };
      await engineInfo();
      var consensus = null;
      if (runs.length) {
        var all = (current.benchmarks ? [current] : []).concat(runs);
        if (all.length >= 2) { consensus = await GK.call("consensus", Object.assign({ runs: all }, base)); current = consensus.report; }
      }
      var check = await GK.call("check", Object.assign({ report: current }, base));
      var diff = prev ? (await GK.call("compare", Object.assign({ old: prev, new: current }, base))).diff : null;
      var verify = null, zip = byRole("zip")[0];
      var context = {};
      if (zip) {
        var path = await GK.putFile(zip.bytes, ".zip");
        verify = await GK.call("verify_zip", { report: current, zip_path: path });
        var locs = codeLocations(current);   // the lines around each quote, for the code viewer
        if (locs.length) (await GK.call("code_context", { zip_path: path, locations: locs })).locations.forEach(function (c, i) { if (!c.error) context[locKey(locs[i])] = c; });
      }
      R = { report: current, check: check, diff: diff, verify: verify, consensus: consensus, project: byRole("project")[0], context: context };
      answers = {};
      UI.clear(status);
      renderHistory();
      render();
    } catch (err) {
      if (err.gk) UI.clear(status).appendChild(UI.failed(err, { title: "Couldn't review these files", retry: analyze }));
      else { UI.clear(status); UI.clear($("#engine-error")).appendChild(UI.engineHelp(err)); }
    } finally {
      if (status.querySelector("[data-state=loading]")) UI.clear(status);
      $("#analyze").textContent = "Review"; updateAnalyzeButton();
    }
  }

  function renderHistory() {
    var bar = $("#history-bar");
    bar.hidden = !(source && source.history.length);
    if (bar.hidden) return;
    $("#history-project").textContent = source.project;
    var pr = UI.clear($("#pick-report")), pc = UI.clear($("#pick-compare"));
    source.history.forEach(function (hst, i) {
      var o = h("option", { value: i }, hst.folder + (i === source.history.length - 1 ? " (latest)" : "")); if (i === sel.report) o.selected = true; pr.appendChild(o);
    });
    pc.appendChild(h("option", { value: -1 }, "Nothing"));
    source.history.forEach(function (hst, i) { if (i !== sel.report) { var o = h("option", { value: i }, hst.folder); if (i === sel.compare) o.selected = true; pc.appendChild(o); } });
  }

  // ------------------------------------------------------------------ helpers
  function bname(id) { var b = info.catalog.benchmarks.find(function (x) { return x.id === id; }); return b ? b.name : id; }
  function pname(p) { return (info.catalog.pillars[p] || {}).name || p; }
  function zoneBadge(c) { return h("span", { class: "badge " + (c === "hot" ? "hot" : c === "cold" ? "cold" : "") }, c || "normal"); }
  function sevBadge(s) { return h("span", { class: "badge " + (s === "critical" ? "bad" : s === "major" ? "warn" : "") }, s); }
  function statusBadge(d) {
    if (!d) return null;
    return h("span", { class: "badge " + (d.status === "approved" ? "ok" : d.status === "declined" ? "bad" : "warn") }, d.status);
  }
  function withheldBadge(f) {
    if (!f || !f.sensitive) return null;
    var withheld = (f.evidence || []).every(function (e) { return e.type === "withheld"; });
    return withheld ? h("span", { class: "badge", title: "Security details are kept out of the public report" }, "details withheld")
                    : h("span", { class: "badge warn", title: "Its details must be withheld before this report goes in a public repo" }, "sensitive");
  }
  function section(title, sub) { return h("div", { class: "section-head" }, h("h2", null, title), sub ? h("p", null, sub) : null); }
  function locKey(e) { return e.file + "|" + (e.lines || "") + "|" + (e.quote || ""); }
  function codeLocations(report) {
    var out = [], seen = {};
    function add(evs) { (evs || []).forEach(function (e) { if (e.type === "code" && !seen[locKey(e)]) { seen[locKey(e)] = 1; out.push({ file: e.file, lines: e.lines, quote: e.quote }); } }); }
    (report.findings || []).forEach(function (f) { add(f.evidence); });
    (report.benchmarks || []).forEach(function (b) {
      (b.strengths || []).forEach(function (x) { add(x.evidence); });
      (b.enforcement || []).forEach(function (x) { add(x.type ? [x] : x.evidence); });
    });
    return out;
  }
  function codeRepo() { return R && R.check.config && R.check.config.project ? R.check.config.project.code_repo : null; }
  function evidenceList(evs) {
    return h("ul", { class: "evidence" }, (evs || []).map(function (e) {
      if (e.type === "code") {
        var ctx = R && R.context ? R.context[locKey(e)] : null;
        return h("li", null, e.note ? h("span", null, e.note) : null,
          UI.codeBlock({ file: e.file, lines: e.lines || (ctx ? ctx.cited.join("-") : null), quote: e.quote, context: ctx,
                         href: UI.codeLink(codeRepo(), R && R.report.run && R.report.run.commit, e.file, e.lines || (ctx ? ctx.cited[0] + "-" + ctx.cited[1] : null)) }));
      }
      if (e.type === "command") return h("li", null, h("code", null, e.command), " ", e.note || "", h("pre", null, e.excerpt));
      if (e.type === "withheld") return h("li", null, h("span", { class: "badge" }, "details withheld"), " ", e.note || "");
      return h("li", null, "Searched for ", h("b", null, e.searched), " (", e.method, ") ", e.note || "");
    }));
  }

  // ------------------------------------------------------------------ deep links (U6)
  // Works on any host: the query picks the source and reports, the hash the view. A link to a report loaded from
  // files can't bring the files with it, so it opens the view once the same files are loaded again.
  function linkFor(view) {
    var q = new URLSearchParams();
    if (source && source.meta && source.meta.repo) {
      q.set("repo", source.meta.owner + "/" + source.meta.repo);
      if (source.meta.ref) q.set("ref", source.meta.ref);
      q.set("project", source.project);
    } else if (source && source.meta && source.meta.sample) { q.set("sample", "1"); q.set("project", source.project); }
    if (source && source.history.length) {
      q.set("report", source.history[sel.report].folder);
      q.set("compare", sel.compare >= 0 ? source.history[sel.compare].folder : "none");
    }
    var hv = new URLSearchParams();
    Object.keys(view || {}).forEach(function (k) { if (view[k]) hv.set(k, view[k]); });
    var qs = q.toString(), hs = hv.toString();
    return location.pathname + (qs ? "?" + qs : "") + (hs ? "#" + hs : "");
  }
  function absolute(view) { return new URL(linkFor(view), location.href).href; }
  function remember(view) { try { history.replaceState(null, "", linkFor(view)); } catch (e) { /* file:// */ } }
  function copyLink(view, label) {
    return h("button", { type: "button", class: "btn sm copy-link", "aria-label": label, onclick: function () {
      UI.copyText(absolute(view));
      if (!(source && source.meta && (source.meta.repo || source.meta.sample))) UI.toast("Copied. It opens this view once the same files are loaded.");
    } }, "Copy link");
  }
  function applyView(v) {
    v = v || {};
    if (v.finding) { resultTabs.select("findings"); openFinding(v.finding); }
    else if (v.bench) { resultTabs.select("scorecard"); openBench(v.bench); }
    else resultTabs.select(v.tab && $("#panel-" + v.tab) ? v.tab : "overview");
    remember(v.finding ? { finding: v.finding } : v.bench ? { bench: v.bench } : { tab: v.tab && $("#panel-" + v.tab) ? v.tab : null });
  }
  function flash(el) { el.classList.add("target-flash"); el.scrollIntoView({ block: "center" }); setTimeout(function () { el.classList.remove("target-flash"); }, 2400); }
  function openBench(id) {
    var wrap = $("#bench-" + id);
    if (!wrap) return;
    var head = wrap.querySelector("button");
    if (head.getAttribute("aria-expanded") !== "true") head.click();
    flash(wrap); head.focus({ preventScroll: true });
  }
  function openFinding(id) {
    var panel = $("#panel-findings");
    var row = panel.querySelector('tr[data-id="' + CSS.escape(id) + '"]');
    if (!row) { var all = panel.querySelector('select[aria-label="Status"]'); if (all) { all.value = "all"; all.dispatchEvent(new Event("change")); } row = panel.querySelector('tr[data-id="' + CSS.escape(id) + '"]'); }
    if (!row) { UI.toast(id + " isn't in this report"); return; }
    var btn = row.querySelector("button.fid");
    if (btn.getAttribute("aria-expanded") !== "true") btn.click();
    flash(row); btn.focus({ preventScroll: true });
  }

  // ------------------------------------------------------------------ render
  function render() {
    $("#results").hidden = false;
    var banners = UI.clear($("#result-banners"));
    var c = R.check, roll = c.rollup;
    if (R.consensus) banners.appendChild(UI.banner("info", "Showing the consensus of " + R.consensus.overall_by_run.length + " runs (median scores). ",
      R.consensus.unstable.length ? "Runs disagreed on " + R.consensus.unstable.join(", ") + ". " : "Runs agreed. ", "Download it as report.json under More → Downloads, and add it to the report's folder."));
    if ((R.report.integrity_flags || []).length) banners.appendChild(UI.banner("bad", h("b", null, "Integrity flag: "), "the grader found text in the repo trying to influence grading. Maturity is capped. See More."));
    if (c.validation.errors.length) banners.appendChild(UI.banner("bad", h("b", null, "This report has " + c.validation.errors.length + " error(s). "), "Treat its numbers with caution; usually the fix is to re-run the grader. Details under More."));
    var pub = c.publish || { problems: [] };
    if (pub.public && pub.problems.length) banners.appendChild(UI.banner("bad", h("b", null, "Not safe to commit to a public grading repo: "),
      pub.problems.join("; ") + ". Use the public copy under More → Downloads, or run ", h("code", null, "gradekit redact --in-place"), "."));
    if (!R.project) banners.appendChild(UI.banner("warn", "No project.toml loaded, so the report is checked against suite defaults. Load the whole project, or add project.toml, to check the config properly."));
    else if (!c.config_hash_match) banners.appendChild(UI.banner("warn", "This report was graded with a different config than the project.toml you loaded (weights, gates or zones changed since). Scores still stand; overall and maturity are recomputed with your current config."));
    renderOverview(); renderDecisions(); renderPriorities(); renderScorecard(); renderFindings(); renderCompare(); renderMore();
    UI.terms($("#results"));
    var pending = roll.priorities.filter(function (p) { return p.decision && p.decision.status === "pending"; }).length;
    var cnt = $("#dec-count"); cnt.hidden = !pending; cnt.textContent = pending;
    var run = R.report.run || {};
    UI.clear($("#print-head")).appendChild(h("div", null, h("h1", null, (run.project || projectName()) + ": grading report"),
      h("p", null, "Commit " + String(run.commit || "").slice(0, 12) + " · " + String(run.date || "").slice(0, 10) + " · overall " + roll.overall_score + " · " + roll.maturity.current_level)));
    var v = want.view; want.view = null;
    applyView(v);
    if (!v || (!v.bench && !v.finding)) $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderOverview() {
    var box = UI.clear($("#panel-overview")), c = R.check, roll = c.rollup, run = R.report.run || {};
    var levels = ["L0", "L1", "L2", "L3", "L4"];
    var names = {}; (info.maturity.levels || []).forEach(function (l) { names[l.level] = l.name; });
    var cur = levels.indexOf(roll.maturity.current_level), nxt = levels.indexOf(roll.maturity.next_level);
    box.appendChild(h("div", { class: "stats-row" },
      h("div", { class: "stat" }, h("div", { class: "k", dataset: { term: "score" } }, "Overall"), h("div", { class: "v" }, roll.overall_score === null ? "–" : String(roll.overall_score)),
        h("div", { class: "s" }, roll.overall_cap_applied ? "Capped by a failed gate (" + roll.overall_score_uncapped + " before the cap)" : "Weighted average out of 10")),
      h("div", { class: "stat span-2" }, h("div", { class: "k", dataset: { term: "maturity level" } }, "Maturity"),
        h("div", { class: "ladder-h" }, levels.map(function (l, i) {
          return h("div", { class: i === cur ? "current" : i < cur ? "reached" : i === nxt ? "next" : "" }, h("b", null, l), names[l] || "");
        })),
        h("div", { class: "s" }, roll.maturity.next_level ? "Next: " + roll.maturity.next_level + " " + (names[roll.maturity.next_level] || "") : "Top level reached")),
      h("div", { class: "stat" }, h("div", { class: "k" }, "Graded"), h("div", { class: "v commit" }, String(run.commit || "?").slice(0, 12)),
        h("div", { class: "s" }, [run.date, (R.report.config || {}).preset ? "preset " + R.report.config.preset : null, R.report.mode === "pr" ? "PR mode" : null].filter(Boolean).join(" · ")))));

    var gates = h("div", { class: "row-btns" }, roll.gates.map(function (g) {
      return h("span", { class: "badge " + (g.status === "failed" ? "bad" : g.status === "passed" ? "ok" : ""), title: bname(g.benchmark_id) + " — gate because " + g.why.join(", ") },
        g.benchmark_id + " " + bname(g.benchmark_id) + ": " + (g.score === null ? "–" : g.score) + (g.status === "failed" ? " ✗" : ""));
    }));
    var checks = h("ul", { class: "checks" },
      check(c.validation.errors.length === 0, "Report format and rules", c.validation.errors.length ? c.validation.errors.length + " error(s), " + c.validation.warnings.length + " warning(s)" : c.validation.warnings.length ? "Valid, with " + c.validation.warnings.length + " warning(s)" : "Valid"),
      check(R.project ? c.config_hash_match : null, "Config", R.project ? (c.config_hash_match ? "Graded with your current project.toml" : "Graded with a different config than the one loaded") : "Checked against suite defaults (no project.toml loaded)"),
      check(R.verify ? R.verify.failures.length === 0 : null, "Code citations", R.verify ? R.verify.checked + " checked, " + R.verify.failures.length + " failed" : "Not checked. Drop the repo's .zip (GitHub: Code → Download ZIP) to check every quote."),
      check(!(R.report.integrity_flags || []).length, "Integrity", (R.report.integrity_flags || []).length ? (R.report.integrity_flags.length + " attempt(s) to influence the grader") : "No attempts to influence the grader found"),
      R.report.holdout && R.report.holdout.run ? check(true, "Hidden checks", Math.round(R.report.holdout.pass_rate * 100) + "% of " + R.report.holdout.checks_run + " passed") : null);
    function check(ok, label, text) {
      return h("li", null, h("span", { class: "badge " + (ok === true ? "ok" : ok === false ? "bad" : "") }, ok === true ? "OK" : ok === false ? "Check" : "—"), h("div", null, h("b", null, label + ": "), text));
    }
    var blockers = roll.maturity.blockers.length ? h("ul", { class: "list-plain" }, roll.maturity.blockers.map(function (b) {
      return h("li", null, b.benchmark_id ? h("b", null, b.benchmark_id + " " + bname(b.benchmark_id) + ": ") : null, b.requirement, " (now ", String(b.current), ")", b.finding_ids ? " — " + b.finding_ids.join(", ") : "");
    })) : h("p", { class: "kbd-note" }, "Nothing blocks the next level.");
    var bars = h("div", { class: "pillar-bars" }, Object.keys(roll.pillar_scores).filter(function (p) { return roll.pillar_scores[p] !== null; }).map(function (p) {
      var v = roll.pillar_scores[p];
      return h("div", { class: "pbar" }, h("span", null, p + " · " + pname(p)), h("div", { class: "track" }, h("i", { style: { "--w": (v * 10) + "%" } })), h("b", null, String(v)));
    }));
    box.appendChild(h("div", { class: "two-col even" },
      h("div", { class: "card" }, h("h2", null, "Checks on this report"), checks),
      h("div", { class: "card" }, h("h2", { dataset: { term: "gate" } }, "Gates"), h("p", { class: "hint" }, "Non-negotiable. A gate at 3 or below caps the overall score."), gates,
        h("h2", { class: "mt-4" }, roll.maturity.next_level ? "What blocks " + roll.maturity.next_level : "Maturity"), blockers)));
    box.appendChild(h("div", { class: "card mt-4" }, h("h2", { dataset: { term: "pillar" } }, "Pillars"), bars));
  }

  // ------------------------------------------------------------------ decisions
  function renderDecisions() {
    var box = UI.clear($("#panel-decisions"));
    var items = R.check.rollup.priorities.filter(function (p) { return p.decision; });
    if (!items.length) { box.appendChild(UI.state("empty", { title: "No decision questions", message: "This report has nothing for a person to decide." })); return; }
    var nameInput = h("input", { type: "text", placeholder: "you@example.com", value: UI.store.get("decider", ""), "aria-label": "Your name or email", class: "maxw-sm" });
    nameInput.addEventListener("input", function () { UI.store.set("decider", nameInput.value); updateDecisionOutput(); });
    box.appendChild(h("p", { class: "hint muted" }, "Some fixes need a person's call: they change behavior, drop a feature, or touch a public interface. Improving agents skip them until they're approved. Answer what you can and leave the rest for later."));
    box.appendChild(h("div", { class: "field" }, h("label", null, "Your name or email (recorded with each answer)"), nameInput));
    items.forEach(function (p) {
      var a = answers[p.action_id] = answers[p.action_id] || { choice: "later", answer: "" };
      var group = "dec-" + p.action_id;
      var seg = h("div", { class: "seg", role: "radiogroup", "aria-label": "Decision for " + p.action_id }, [["approve", "Approve"], ["decline", "Decline"], ["later", "Not yet"]].map(function (o) {
        var r = h("input", { type: "radio", name: group, value: o[0] }); r.checked = a.choice === o[0];
        r.addEventListener("change", function () { a.choice = o[0]; updateDecisionOutput(); });
        return h("label", null, r, h("span", null, o[1]));
      }));
      var txt = h("textarea", { rows: "2", placeholder: "Details or conditions (optional), e.g. “CSV only; drop XLSX from the README.”", "aria-label": "Answer details" });
      txt.value = a.answer; txt.addEventListener("input", function () { a.answer = txt.value; updateDecisionOutput(); });
      box.appendChild(h("div", { class: "decision" },
        h("div", { class: "meta" }, statusBadge(p.decision), " ", p.action_id, " · ", bname(p.benchmark_id), " · ", TIERS[p.tier], " · ", zoneBadge(p.zone)),
        h("div", { class: "q" }, UI.inline(p.decision_question)),
        h("p", { class: "act" }, "Action: ", UI.inline(p.action)),
        p.decision.status !== "pending" ? h("p", { class: "kbd-note" }, "Already answered: " + p.decision.status + (p.decision.answer ? " — " + p.decision.answer : "") + (p.decision.decided_by ? " (" + p.decision.decided_by + ")" : "")) : null,
        p.decision.note ? h("p", { class: "kbd-note" }, p.decision.note) : null,
        seg, h("div", { class: "mt-2" }, txt)));
    });
    box.appendChild(h("div", { class: "card mt-4", id: "dec-output" }));
    updateDecisionOutput();
  }

  var updateDecisionOutput = UI.debounce(async function () {
    var out = $("#dec-output"); if (!out) return;
    UI.clear(out).appendChild(h("h2", null, "Save your answers"));
    var who = UI.store.get("decider", "") || "<your name>";
    var date = new Date().toISOString().slice(0, 10);
    var items = R.check.rollup.priorities.filter(function (p) { return p.decision && answers[p.action_id] && answers[p.action_id].choice !== "later"; });
    if (!items.length) { out.appendChild(h("p", { class: "kbd-note" }, "Choose Approve or Decline on at least one question above.")); return; }
    var decisions = items.map(function (p) {
      var a = answers[p.action_id];
      var d = { action_id: p.action_id, question: p.decision_question, approved: a.choice === "approve" };
      if (a.answer.trim()) d.answer = a.answer.trim();
      d.decided_by = who; d.date = date;
      return d;
    });
    var existing = byRole("decisions")[0];
    var body = out.appendChild(h("div"));
    await UI.saveDecisions(body, { project: projectName(), decisions: decisions, existing: existing ? existing.text : null,
                                   branch: (source && source.meta && source.meta.ref && /^report\//.test(source.meta.ref)) ? source.meta.ref : null });
  }, 200);

  // ------------------------------------------------------------------ priorities
  function renderPriorities() {
    var box = UI.clear($("#panel-priorities"));
    var prios = R.check.rollup.priorities;
    if (!prios.length) { box.appendChild(UI.state("empty", { title: "No improvement actions", message: "The grader planned no steps toward the targets in this report." })); return; }
    box.appendChild(h("p", { class: "hint muted" }, "The order improving agents work in. gradekit ranks it: failed gates and critical problems in hot code first, then what blocks the next maturity level, then the rest by weight × points gained × zone ÷ effort."));
    [0, 1, 2, 3].forEach(function (t) {
      var list = prios.filter(function (p) { return p.tier === t; });
      if (!list.length) return;
      box.appendChild(section(TIERS[t]));
      box.appendChild(h("div", { class: "card" }, list.map(function (p) {
        return h("div", { class: "prio" }, h("div", { class: "rank" }, "#" + p.rank),
          h("div", null, h("div", { class: "t" }, UI.inline(p.action)),
            h("div", { class: "m" }, h("span", { class: "chip" }, p.benchmark_id + " " + bname(p.benchmark_id)), zoneBadge(p.zone),
              h("span", { class: "chip" }, "+" + p.gain + " points"), h("span", { class: "chip" }, "effort " + (p.effort || "?")),
              p.decision ? h("span", null, "decision: ", statusBadge(p.decision)) : null)));
      })));
    });
  }

  // ------------------------------------------------------------------ scorecard
  function renderScorecard() {
    var box = UI.clear($("#panel-scorecard"));
    var roll = R.check.rollup, gates = roll.gates.map(function (g) { return g.benchmark_id; });
    var fz = roll.finding_zones, findings = {};
    (R.report.findings || []).forEach(function (f) { findings[f.id] = f; });
    box.appendChild(h("p", { class: "hint muted" }, "Bars show the score; the tick marks the target. Click a row for its evidence, findings and next actions."));
    var pillars = {};
    R.report.benchmarks.forEach(function (b) { (pillars[b.pillar] = pillars[b.pillar] || []).push(b); });
    Object.keys(pillars).forEach(function (p) {
      var ps = roll.pillar_scores[p];
      box.appendChild(section(p + " · " + pname(p) + (ps !== null && ps !== undefined ? "  —  " + ps : "")));
      box.appendChild(h("div", { class: "card flush" }, pillars[p].map(function (b) {
        var na = b.applicability === "not_applicable";
        var target = roll.targets[b.id];
        var bar = na ? h("span", { class: "kbd-note" }, "not applicable") : h("div", { class: "track barcell" }, h("i", { style: { "--w": (b.score * 10) + "%" } }), target ? h("span", { class: "tgt", style: { "--at": (target * 10) + "%" } }) : null);
        var head = h("button", { type: "button", "aria-expanded": "false" },
          h("span", { class: "id" }, b.id),
          h("span", null, b.name, " ", gates.indexOf(b.id) >= 0 ? h("span", { class: "chip gate" }, "gate") : null, " ",
            b.applicability === "limited" ? h("span", { class: "badge warn", title: b.applicability_reason || "" }, "limited") : null,
            h("span", { class: "kbd-note" }, "  weight " + b.weight)),
          bar, h("span", { class: "score" }, na ? "–" : String(b.score)), h("span", { class: "chev" }, "›"));
        var body = h("div", { class: "body", hidden: true });
        var wrap = h("div", { class: "bench", id: "bench-" + b.id }, head, body);
        head.addEventListener("click", function () {
          var open = body.hidden; body.hidden = !open; head.setAttribute("aria-expanded", String(open)); wrap.setAttribute("open-state", open ? "open" : "");
          if (open && !body.firstChild) fillBench(body, b, findings, fz, target);
          remember(open ? { bench: b.id } : { tab: "scorecard" });
        });
        return wrap;
      })));
    });
  }
  function fillBench(body, b, findings, fz, target) {
    // Why this score (H6): the grader's reasoning, any limit that holds it, and the rubric's words for each band.
    var lim = (R.check.rollup.limits || {})[b.id];
    var why = h("div", { class: "why" }, h("b", null, "Why " + (b.score === null || b.score === undefined ? "no score" : b.score) + ": "), b.rationale ? UI.inline(b.rationale) : h("span", { class: "kbd-note" }, "the grader didn't record why (report score --rationale)."));
    var binding = lim && lim.why ? lim.why.filter(function (w) { return w.max === lim.max; }) : [];
    if (binding.length) why.appendChild(h("p", { class: "mt-2 mb-0" }, h("b", null, "Held at " + lim.max + " or below: "),
      binding.map(function (w) { return w.why || w.kind; }).join("; ") + "."));
    body.appendChild(why);
    var anchors = h("div");
    body.appendChild(anchors);
    rubricFor(b.id).then(function (rb) {
      if (!rb || !rb.anchors) return;
      anchors.appendChild(h("h3", null, "What the scores mean"));
      anchors.appendChild(h("ul", { class: "anchors" }, Object.keys(rb.anchors).map(function (band) {
        var m = band.match(/^(\d+)\D+(\d+)$/), here = m && b.score >= +m[1] && b.score <= +m[2];
        return h("li", { class: here ? "here" : null, "aria-current": here ? "true" : null }, h("b", null, band), rb.anchors[band]);
      })));
      if (rb.caps && rb.caps.length) anchors.appendChild(h("p", { class: "kbd-note" }, "Caps: " + rb.caps.map(function (c) { return c.when + " → max " + c.max + " (" + c.id + ")"; }).join("; ")));
    });
    var hist = h("div");
    body.appendChild(hist);
    benchHistory(b.id).then(function (pts) {
      if (!pts || pts.length < 2) return;
      hist.appendChild(h("h3", null, "Over time"));
      hist.appendChild(h("div", { class: "bench-history" }, pts.map(function (p, i) {
        return h("span", null, i ? "→ " : "", h("b", null, p.score === null || p.score === undefined ? "–" : String(p.score)), " ", h("span", { class: "kbd-note" }, p.folder));
      })));
    });
    if (b.applicability !== "full") body.appendChild(h("p", null, h("b", null, "Applicability: "), b.applicability + " — " + (b.applicability_reason || "")));
    if (b.weight_note) body.appendChild(h("p", null, h("b", null, "Grader's weight note: "), b.weight_note));
    body.appendChild(h("p", { class: "kbd-note" }, "Score " + (b.score === null ? "–" : b.score) + (target ? " · target " + target : "") + " · confidence " + (b.confidence || "–") + (b.previous_score !== null && b.previous_score !== undefined ? " · was " + b.previous_score : "")));
    if (b.change_explanation) body.appendChild(h("p", null, h("b", null, "What changed: "), b.change_explanation));
    if ((b.caps_applied || []).length) body.appendChild(h("p", null, h("b", null, "Capped: "), b.caps_applied.join("; ")));
    if ((b.gaming_flags || []).length) body.appendChild(UI.banner("bad", h("b", null, "Gaming flags: "), b.gaming_flags.join("; ")));
    if ((b.strengths || []).length) { body.appendChild(h("h3", null, "Strengths")); b.strengths.forEach(function (s) { body.appendChild(h("div", null, s.note, evidenceList(s.evidence))); }); }
    if ((b.enforcement || []).length) {
      body.appendChild(h("h3", null, "Enforced by"));
      b.enforcement.forEach(function (e) {   // format 5: {note, evidence}; format 4: a bare evidence object
        var item = e && e.type ? { note: e.note || "", evidence: [e] } : e;
        body.appendChild(h("div", null, item.note, evidenceList(item.evidence)));
      });
    }
    if ((b.finding_ids || []).length) {
      body.appendChild(h("h3", null, "Findings"));
      b.finding_ids.forEach(function (id) {
        var f = findings[id], z = fz[id] || {};
        if (!f) return;
        body.appendChild(h("div", { class: "finding-line" }, h("b", null, id + " "), sevBadge(z.effective_severity || f.severity), " ", zoneBadge(z.criticality), " ", h("span", { class: "badge" }, f.status), " ", f.title, " ", withheldBadge(f), evidenceList(f.evidence)));
      });
    }
    if ((b.path_to_target || []).length) {
      body.appendChild(h("h3", null, "Path to target"));
      body.appendChild(h("ol", { class: "list-tight" }, b.path_to_target.map(function (a) {
        return h("li", null, a.action, h("span", { class: "kbd-note" }, "  (" + a.id + ", effort " + a.effort + ", → " + a.expected_new_score + (a.requires_human_decision ? ", needs a decision" : "") + ")"));
      })));
    }
    body.appendChild(h("div", { class: "bench-tools" }, copyLink({ bench: b.id }, "Copy link to " + b.id)));
  }
  async function rubricFor(id) {
    if (!rubric) {
      try { rubric = await (await fetch(new URL("suite/rubric/rubric.json", GK.site).href)).json(); }
      catch (e) { rubric = { benchmarks: [] }; }
    }
    return (rubric.benchmarks || []).filter(function (x) { return x.id === id; })[0];
  }
  // A benchmark's score in every report of the loaded project, oldest first (reports are fetched once, then cached).
  async function benchHistory(id) {
    if (!source || source.history.length < 2) return null;
    var out = [];
    for (var i = 0; i < source.history.length; i++) {
      var x = source.history[i];
      try { histCache[x.folder] = histCache[x.folder] || await x.get(); } catch (e) { continue; }
      var bb = (histCache[x.folder].benchmarks || []).filter(function (y) { return y.id === id; })[0];
      if (bb) out.push({ folder: x.folder, score: bb.applicability === "not_applicable" ? "n/a" : bb.score });
    }
    return out;
  }

  // ------------------------------------------------------------------ findings
  function renderFindings() {
    var box = UI.clear($("#panel-findings"));
    var fz = R.check.rollup.finding_zones, list = R.report.findings || [];
    if (!list.length) { box.appendChild(UI.state("empty", { title: "No findings", message: "The grader recorded no problems in this report." })); return; }
    var f = { zone: "all", sev: "all", status: "open" };
    var shifted = list.some(function (x) { var z = fz[x.id] || {}; return z.effective_severity && z.effective_severity !== x.severity; });
    function selectFilter(label, key, opts) {
      var sel = h("select", { "aria-label": label, class: "w-auto" }, opts.map(function (o) { return h("option", { value: o[0] }, o[1]); }));
      sel.value = f[key]; sel.addEventListener("change", function () { f[key] = sel.value; draw(); });
      return h("label", null, label + " ", sel);
    }
    box.appendChild(h("div", { class: "filters" },
      selectFilter("Zone", "zone", [["all", "All"], ["hot", "Hot"], ["normal", "Normal"], ["cold", "Cold"]]),
      selectFilter("Severity", "sev", [["all", "All"], ["critical", "Critical"], ["major", "Major"], ["minor", "Minor"]]),
      selectFilter("Status", "status", [["open", "Open: not fixed or accepted"], ["all", "All"], ["fixed", "Fixed"], ["accepted", "Accepted"]]),
      shifted ? h("span", { class: "kbd-note" }, "Graded under the 4.x rules: severity shown is effective, one higher in hot zones and one lower in cold.") : null));
    var tableWrap = h("div", { class: "card tight" });
    box.appendChild(tableWrap);
    function draw() {
      var rows = list.filter(function (x) {
        var z = fz[x.id] || {};
        var openish = ["new", "noticed", "open", "regressed"].indexOf(x.status) >= 0;
        return (f.zone === "all" || z.criticality === f.zone) && (f.sev === "all" || z.effective_severity === f.sev) &&
               (f.status === "all" || (f.status === "open" ? openish : x.status === f.status));
      });
      UI.clear(tableWrap).appendChild(rows.length ? h("table", { class: "findings" }, h("thead", null, h("tr", null, ["ID", "Severity", "Zone", "Status", "Finding"].map(function (t) { return h("th", null, t); }))),
        h("tbody", null, rows.map(function (x) {
          var z = fz[x.id] || {};
          var detail = h("tr", { class: "finding-detail", hidden: true }, h("td", { colspan: "5" }));
          var toggle = h("button", { type: "button", class: "link fid", "aria-expanded": "false", "aria-label": x.id + ": show its evidence" }, h("code", null, x.id));
          toggle.addEventListener("click", function () {
            var open = detail.hidden; detail.hidden = !open; toggle.setAttribute("aria-expanded", String(open));
            if (open && !detail.firstChild.firstChild) findingDetail(detail.firstChild, x, z);
            remember(open ? { finding: x.id } : { tab: "findings" });
          });
          return [h("tr", { dataset: { id: x.id } }, h("td", null, toggle), h("td", null, sevBadge(z.effective_severity || x.severity), z.effective_severity && z.effective_severity !== x.severity ? h("div", { class: "kbd-note" }, "was " + x.severity) : null),
            h("td", null, zoneBadge(z.criticality), z.zone ? h("div", { class: "kbd-note" }, z.zone) : null), h("td", null, x.status), h("td", null, x.title, " ", withheldBadge(x), x.disposition ? h("div", { class: "kbd-note" }, "Accepted: " + x.disposition) : null)), detail];
        }))) : UI.state("empty", { title: "No findings match these filters", message: "Change or clear the filters above." }));
    }
    draw();
  }

  function findingDetail(cell, x, z) {
    cell.appendChild(h("p", { class: "m-0" }, h("b", null, x.benchmark_id + " · " + bname(x.benchmark_id)),
      x.first_seen_commit ? h("span", { class: "kbd-note" }, " · first seen at " + String(x.first_seen_commit).slice(0, 8)) : null,
      x.cap ? h("span", { class: "kbd-note" }, " · holds " + x.cap) : null));
    if (x.dispute) cell.appendChild(UI.banner("warn", h("b", null, "Disputed: "), x.dispute.reason || "", x.dispute.answer ? h("div", null, h("b", null, "Answer: "), x.dispute.answer) : null));
    cell.appendChild(evidenceList(x.evidence));
    cell.appendChild(h("div", { class: "bench-tools" }, copyLink({ finding: x.id }, "Copy link to " + x.id),
      h("button", { type: "button", class: "btn sm", onclick: function () { applyView({ bench: x.benchmark_id }); } }, "Open " + x.benchmark_id)));
  }

  // ------------------------------------------------------------------ compare
  function renderCompare() {
    var box = UI.clear($("#panel-compare")), d = R.diff;
    if (!d) {
      box.appendChild(UI.state("empty", { title: "Load an earlier report to see what changed",
        message: "Load the whole project (from the grading repo, a folder or a zip) and the previous report is picked automatically; or drop an earlier report.json." }));
      return;
    }
    box.appendChild(UI.banner(d.verdict === "PASS" ? "info" : "bad", h("b", null, d.verdict === "PASS" ? "Nothing got worse. " : "Something got worse. "),
      "Overall " + d.overall.old + " → " + d.overall.new + " · maturity " + d.maturity.old + " → " + d.maturity.new + " · commit " + String(d.from_commit).slice(0, 8) + " → " + String(d.to_commit).slice(0, 8)));
    if (d.regressions.length) box.appendChild(h("div", { class: "card" }, h("h2", null, "Regressions"), h("ul", null, d.regressions.map(function (r) { return h("li", null, r); }))));
    box.appendChild(h("div", { class: "two-col even mt-4" },
      h("div", { class: "card" }, h("h2", null, "Score changes"), d.score_changes.length ? h("table", null, h("tbody", null, d.score_changes.map(function (c) {
        var up = c.new !== null && c.old !== null && c.new > c.old;
        return h("tr", null, h("td", null, h("code", null, c.id)), h("td", null, bname(c.id)), h("td", null, (c.old === null ? "–" : c.old) + " → " + (c.new === null ? "–" : c.new)), h("td", null, h("span", { class: "badge " + (up ? "ok" : "bad") }, up ? "up" : "down")));
      }))) : h("p", { class: "kbd-note" }, "No score changes.")),
      h("div", { class: "card" }, h("h2", null, "Findings"),
        list("New", d.findings.new), list("Fixed", d.findings.fixed), list("Regressed", d.findings.regressed))));
    function list(title, items) {
      return h("div", { class: "mb-3" }, h("b", null, title + " (" + items.length + ")"), items.length ? h("ul", { class: "list-tight" }, items.map(function (f) {
        return h("li", null, h("code", null, f.id), " ", sevBadge(f.effective_severity), " ", f.title, f.pre_existing ? h("span", { class: "kbd-note" }, " (already there before this change)") : null);
      })) : null);
    }
    if (d.notes.length) box.appendChild(h("div", { class: "card mt-4" }, h("h2", null, "Notes"), h("ul", null, d.notes.map(function (n) { return h("li", null, n); }))));
  }

  // ------------------------------------------------------------------ more
  function renderMore() {
    var box = UI.clear($("#panel-more")), r = R.report, c = R.check;
    // Downloads
    var dl = h("div", { class: "row-btns" });
    function addDl(label, name, obj) { var b = h("button", { type: "button", class: "btn" }, label); b.addEventListener("click", function () { UI.download(name, JSON.stringify(obj, null, 2) + "\n", "application/json"); }); dl.appendChild(b); }
    if (R.consensus) addDl("Download consensus as report.json", "report.json", R.consensus.report);
    var priv = r.holdout && Array.isArray(r.holdout.private_details) && r.holdout.private_details.length;
    var unsafe = ((c.publish || {}).problems || []).length > 0;
    var leakBox = h("div");
    if (priv || unsafe) {
      var red = h("button", { type: "button", class: "btn" }, "Download a copy safe to publish");
      red.addEventListener("click", async function () {
        var x = await GK.call("redact", { report: r });
        UI.clear(leakBox);
        if (x.leaks.length) {
          leakBox.appendChild(UI.banner("bad", h("b", null, "Not downloaded: "), "withheld details still appear elsewhere in the report. Reword these places in general terms, then try again.",
            h("ul", null, x.leaks.map(function (l) { return h("li", null, l); }))));
          return;
        }
        UI.download("report.json", JSON.stringify(x.report, null, 2) + "\n", "application/json");
      });
      dl.appendChild(red);
    }
    if (dl.firstChild) box.appendChild(h("div", { class: "card" }, h("h2", null, "Downloads"),
      priv || unsafe ? UI.banner("warn", "This report still contains " + (priv ? "per-check hidden-check results" : "") + (priv && unsafe ? " and " : "") +
        (unsafe ? "the details of sensitive findings" : "") + ". Don't commit it to a public repo; use the copy safe to publish, and keep this one private.") : null, dl, leakBox));
    if (R.consensus) {
      box.appendChild(section("Consensus across runs", "Median score per benchmark. Spreads over 1 point mean the rubric wording for that benchmark may be too vague."));
      box.appendChild(h("div", { class: "card" }, h("table", null, h("thead", null, h("tr", null, ["ID", "Scores by run", "Median", "Spread"].map(function (t) { return h("th", null, t); }))),
        h("tbody", null, R.consensus.rows.map(function (row) {
          return h("tr", null, h("td", null, row.id), h("td", null, row.scores.map(function (x) { return x === null ? "–" : x; }).join(", ")), h("td", null, row.median === null ? "–" : String(row.median)),
            h("td", null, String(row.spread), row.unstable ? " " : null, row.unstable ? h("span", { class: "badge warn" }, row.split ? "applicability split" : "unstable") : null));
        })))));
    }
    if (R.verify && R.verify.failures.length) {
      box.appendChild(section("Citations that didn't check out"));
      box.appendChild(h("div", { class: "card" }, h("ul", null, R.verify.failures.map(function (f) { return h("li", null, f); }))));
    }
    if ((r.integrity_flags || []).length) {
      box.appendChild(section("Integrity flags"));
      box.appendChild(h("div", { class: "card" }, r.integrity_flags.map(function (f) { return h("div", null, h("b", null, f.description), evidenceList(f.evidence)); })));
    }
    box.appendChild(section("Validation", "From gradekit validate."));
    box.appendChild(h("div", { class: "card" },
      c.validation.errors.length ? h("div", null, h("b", null, "Errors"), h("ul", null, c.validation.errors.map(function (e) { return h("li", null, e); }))) : h("p", null, "No errors."),
      c.validation.warnings.length ? h("div", null, h("b", null, "Warnings"), h("ul", null, c.validation.warnings.map(function (e) { return h("li", null, e); }))) : null,
      (c.validation.notes || []).length ? h("p", { class: "kbd-note" }, "Note: " + c.validation.notes.join(" ")) : null,
      h("p", { class: "kbd-note" }, "Config used: " + c.config_source + " · hash " + c.config.hash)));
    if ((r.gap_register || []).length) {
      box.appendChild(section("Gaps", "Things the project's purpose needs, or users would expect, that are missing."));
      box.appendChild(h("div", { class: "card" }, h("table", null, h("tbody", null, r.gap_register.map(function (g) {
        return h("tr", null, h("td", null, h("code", null, g.id)), h("td", null, sevBadge(g.severity)), h("td", null, g.necessity), h("td", null, g.gap, g.rationale ? h("div", { class: "kbd-note" }, g.rationale) : null), h("td", null, g.status));
      })))));
    }
    if ((r.feature_inventory || []).length) {
      box.appendChild(section("Features", "What the project claims, and whether it works."));
      box.appendChild(h("div", { class: "card" }, h("table", null, h("tbody", null, r.feature_inventory.map(function (x) {
        return h("tr", null, h("td", null, x.feature), h("td", null, h("span", { class: "badge " + (x.status === "complete" ? "ok" : x.status === "broken" || x.status === "stub" ? "bad" : "warn") }, x.status)), h("td", { class: "kbd-note" }, x.source));
      })))));
    }
    var metrics = r.metrics || {};
    if (Object.keys(metrics).length) {
      box.appendChild(section("Metrics", "Raw measurements, recorded alongside the scores."));
      box.appendChild(h("div", { class: "card" }, h("table", null, h("tbody", null, Object.keys(metrics).map(function (k) {
        var v = metrics[k];
        return h("tr", null, h("td", null, h("code", null, k)), h("td", null, v === null ? "not measured" : String(v)), h("td", { class: "kbd-note" }, (r.metrics_notes || {})[k] || ""));
      })))));
    }
    if ((r.limitations || []).length) {
      box.appendChild(section("Limitations", "What the grader couldn't run or verify."));
      box.appendChild(h("div", { class: "card" }, h("ul", null, r.limitations.map(function (l) { return h("li", null, l); }))));
    }
  }

  // ------------------------------------------------------------------ print / save as PDF (U3)
  // Every section, in order, every benchmark open, without the controls (style.css @media print).
  function printReport() {
    $$(".bench").forEach(function (w) { var b = w.querySelector("button"); if (b.getAttribute("aria-expanded") !== "true") b.click(); });
    $$("#panel-findings button.fid").forEach(function (b) { if (b.getAttribute("aria-expanded") !== "true") b.click(); });
    window.print();
  }

  // ------------------------------------------------------------------ wiring
  document.addEventListener("DOMContentLoaded", function () {
    UI.bindEnginePill($("#engine-pill"));
    GK.load().catch(function (err) { UI.clear($("#engine-error")).appendChild(UI.engineHelp(err)); });
    var loadTabs = UI.tabs($("#load-tabs"));
    loadTabs.select("repo");
    resultTabs = UI.tabs($("#result-tabs"));
    $("#result-tabs").addEventListener("click", function (e) { var t = e.target.closest("button[data-tab]"); if (t) remember({ tab: t.dataset.tab }); });
    $("#print-report").addEventListener("click", printReport);
    $("#copy-report-link").addEventListener("click", function () {
      var hv = new URLSearchParams(location.hash.slice(1)), v = {};
      hv.forEach(function (val, k) { v[k] = val; });
      UI.copyText(absolute(v));
      if (!(source && source.meta && (source.meta.repo || source.meta.sample))) UI.toast("Copied. It opens this view once the same files are loaded.");
    });
    UI.dropZone($("#drop"), $("#file-input"), onFiles);
    $("#pick-folder").addEventListener("click", function () { $("#folder-input").click(); });
    $("#folder-input").addEventListener("change", function () { var l = Array.prototype.slice.call(this.files); this.value = ""; if (l.length) onFolder(l); });
    $("#analyze").addEventListener("click", analyze);
    $("#gh-load").addEventListener("click", loadGitHub);
    $("#pick-report").addEventListener("change", function () {
      sel.report = parseInt(this.value, 10);
      if (sel.compare === sel.report) sel.compare = -1;
      if (sel.compare < 0 && sel.report > 0) sel.compare = sel.report - 1;
      analyze();
    });
    $("#pick-compare").addEventListener("change", function () { sel.compare = parseInt(this.value, 10); analyze(); });
    $("#clear-files").addEventListener("click", function () { files = []; source = null; R = null; pendingPicker = null; renderFiles(); $("#results").hidden = true; UI.clear($("#gh-status")); });
    $("#sample").addEventListener("click", function () { loadTabs.select("files"); loadSample(); });
    var gh = UI.store.get("gh", {});
    var q = new URLSearchParams(location.search), hv = new URLSearchParams(location.hash.slice(1));
    want.report = q.get("report"); want.compare = q.get("compare");
    want.view = { tab: hv.get("tab"), bench: hv.get("bench"), finding: hv.get("finding") };
    $("#gh-repo").value = q.get("repo") || gh.repo || "";
    $("#gh-project").value = q.get("project") || gh.project || "";
    $("#gh-ref").value = q.get("ref") || "";
    if (q.get("repo")) loadGitHub();
    else if (q.get("sample")) { loadTabs.select("files"); loadSample(); }
  });
})();
