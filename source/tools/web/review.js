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
  var SIDE = { "project.toml": "project", "decisions.json": "decisions", "dispositions.json": "dispositions", "org.toml": "org" };

  function projectName() {
    return (source && source.project) || (R && R.report && R.report.run && R.report.run.project) || "<project>";
  }

  // ------------------------------------------------------------------ loose files
  function guessRole(f) {
    if (SIDE[f.name]) return SIDE[f.name];
    if (/\.zip$/i.test(f.name)) return "zip";
    if (/\.toml$/i.test(f.name)) return byRole("project").length ? "org" : "project";
    if (f.json && Array.isArray(f.json.benchmarks)) {
      var main = files.find(function (x) { return x.role === "report"; });
      if (!main) return "report";
      var a = (main.json.run || {}).commit, b = (f.json.run || {}).commit;
      return a && b && a === b ? "run" : "previous";
    }
    if (f.json && Array.isArray(f.json.decisions)) return "decisions";
    if (f.json && Array.isArray(f.json.dispositions)) return "dispositions";
    return "ignore";
  }

  function addFile(name, content, isBytes, role, fromSource) {
    var f = { id: ++fileSeq, name: name, fromSource: !!fromSource };
    if (isBytes) f.bytes = content; else f.text = content;
    if (!isBytes && /\.json$/i.test(name)) { try { f.json = JSON.parse(content); } catch (e) { f.error = "not valid JSON"; } }
    f.role = role || (f.error ? "ignore" : guessRole(f));
    if (!role && f.role === "previous") {
      var main = files.find(function (x) { return x.role === "report"; });
      if (main && String((f.json.run || {}).date) > String((main.json.run || {}).date)) { main.role = "previous"; f.role = "report"; }
    }
    files.push(f);
    return f;
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
      sel.addEventListener("change", function () { f.role = sel.value; updateAnalyzeButton(); });
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
  function scanEntries(entries) {
    var projects = {}, org = null;
    entries.forEach(function (e) {
      var parts = e.path.replace(/^\/+/, "").split("/"), last = parts[parts.length - 1];
      if (last === "org.toml") { org = e; return; }
      var idx = parts.lastIndexOf("reports");
      var root = idx >= 0 ? parts.slice(0, idx) : parts.slice(0, -1), rest = idx >= 0 ? parts.slice(idx + 1) : [last];
      var key = root.join("/"), name = root[root.length - 1] || "project";
      var p = projects[key] = projects[key] || { name: name, key: key, side: {}, reports: {} };
      if (idx < 0 && rest.length === 1 && SIDE[last] && last !== "org.toml") p.side[last] = e;
      else if (rest.length === 2 && rest[1] === "report.json") (p.reports[rest[0]] = p.reports[rest[0]] || { runs: [] }).report = e;
      else if (rest.length === 3 && rest[1] === "runs" && /\.json$/.test(rest[2])) (p.reports[rest[0]] = p.reports[rest[0]] || { runs: [] }).runs.push(e);
    });
    var found = Object.keys(projects).map(function (k) { var p = projects[k]; p.org = org; return p; })
      .filter(function (p) { return p.side["project.toml"] || Object.keys(p.reports).some(function (f) { return p.reports[f].report; }); });
    // Copies of the suite (any folder with tools/gradekit.py, such as bundle/bare/ or a website's suite/)
    // ship an example project. Skip projects inside them, unless they're all there is.
    var kits = entries.map(function (e) { return e.path.replace(/^\/+/, ""); })
      .filter(function (p) { return p === "tools/gradekit.py" || /\/tools\/gradekit\.py$/.test(p); })
      .map(function (p) { return p.slice(0, p.length - "tools/gradekit.py".length); });
    var outside = found.filter(function (p) { return !kits.some(function (k) { return (p.key + "/").indexOf(k) === 0; }); });
    if (outside.length) return outside;
    // Only copies of the example: show each project once (the shortest path).
    var seen = {};
    return found.slice().sort(function (a, b) { return a.key.length - b.key.length; })
      .filter(function (p) { if (seen[p.name]) return false; seen[p.name] = true; return true; });
  }

  // Oldest first, like gradekit's report_order_key: folders are <date>-<commit>, so the name orders by day;
  // reports from the same day are ordered by run.date (a UTC timestamp). Only same-day reports are read.
  async function orderFolders(folders, runDate) {
    var byDay = {};
    folders.forEach(function (f) { (byDay[f.slice(0, 10)] = byDay[f.slice(0, 10)] || []).push(f); });
    var dates = {};
    for (var day in byDay) {
      if (byDay[day].length < 2) continue;
      for (var i = 0; i < byDay[day].length; i++) dates[byDay[day][i]] = await runDate(byDay[day][i]);
    }
    return folders.slice().sort(function (a, b) {
      var ka = [a.slice(0, 10), dates[a] || "", a], kb = [b.slice(0, 10), dates[b] || "", b];
      for (var i = 0; i < 3; i++) { if (ka[i] < kb[i]) return -1; if (ka[i] > kb[i]) return 1; }
      return 0;
    });
  }

  async function useProject(p, label, meta) {
    pendingPicker = null;
    files = files.filter(function (f) { return !f.fromSource && ["project", "decisions", "dispositions", "org", "report", "previous", "run"].indexOf(f.role) < 0; });
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
    renderFiles();
    if (source.history.length) analyze();
    else UI.toast("Loaded " + p.name + ": no reports yet");
  }

  async function chooseProject(projects, label, meta) {
    if (!projects.length) { UI.toast("No project found there: expected project.toml or reports/<date>/report.json"); return; }
    if (projects.length === 1) return useProject(projects[0], label, meta);
    var pick = h("select", { "aria-label": "Project" }, projects.map(function (p, i) { return h("option", { value: i }, p.name + " (" + Object.keys(p.reports).length + " reports)"); }));
    var go = h("button", { type: "button", class: "btn primary" }, "Load project");
    go.addEventListener("click", function () { useProject(projects[parseInt(pick.value, 10)], label, meta); });
    pendingPicker = h("div", { class: "banner info" }, "This contains several projects. Pick one: ", pick, " ", go);
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
        } catch (err) { UI.clear($("#engine-error")).appendChild(err.gk ? h("div", { class: "banner bad" }, err.message) : UI.engineHelp(err)); }
        addFile(file.name, bytes, true, "zip");
      } else {
        loose.push(file);
      }
    }
    for (var j = 0; j < loose.length; j++) addFile(loose[j].name, await UI.readFile(loose[j]));
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
    await chooseProject(scanEntries(entries), "folder " + top);
  }

  // ------------------------------------------------------------------ GitHub (public grading repos)
  function parseRepo(input) {
    var s = input.trim().replace(/\.git$/, "");
    var m = s.match(/github\.com\/([^\/]+)\/([^\/#?]+)(?:\/(tree|pull)\/([^?#]+))?/);
    if (m) return { owner: m[1], repo: m[2], kind: m[3], rest: m[4] };
    m = s.match(/^([\w.-]+)\/([\w.-]+)$/);
    return m ? { owner: m[1], repo: m[2] } : null;
  }
  async function getJSON(url) {
    var r = await fetch(url);
    if (!r.ok) {
      var limited = (r.status === 403 || r.status === 429) && r.headers.get("x-ratelimit-remaining") === "0";
      var reset = limited && Number(r.headers.get("x-ratelimit-reset"));
      var e = new Error(limited ? "GitHub's limit for anonymous requests (60 an hour per network) is used up" + (reset ? "; it resets at " + new Date(reset * 1000).toLocaleTimeString() : "") + ". Try again then, or download the repo and use Open files" : url.replace(/^https:\/\//, "") + " → " + r.status);
      e.status = r.status; e.limited = limited; throw e;
    }
    return r.json();
  }
  async function getText(url) { var r = await fetch(url); if (!r.ok) { var e = new Error(r.status === 404 ? "not found" : String(r.status)); e.status = r.status; throw e; } return r.text(); }
  function encRef(ref) { return ref.split("/").map(encodeURIComponent).join("/"); }

  async function loadGitHub() {
    var st = UI.clear($("#gh-status"));
    var say = function (msg, cls) { UI.clear(st).appendChild(h("div", { class: "banner " + (cls || "info"), style: "margin-top:10px" }, msg)); };
    var p = parseRepo($("#gh-repo").value);
    if (!p) { say("Enter the grading repo as owner/repo or a github.com URL.", "warn"); return; }
    var ref = $("#gh-ref").value.trim(), project = $("#gh-project").value.trim();
    var owner = p.owner, repo = p.repo;
    UI.store.set("gh", { repo: $("#gh-repo").value, project: project });
    try {
      say("Looking up the repository…");
      if (p.kind === "tree" && !ref) ref = decodeURIComponent(p.rest);
      if (p.kind === "pull") {
        var pr = await getJSON("https://api.github.com/repos/" + owner + "/" + repo + "/pulls/" + parseInt(p.rest, 10));
        owner = pr.head.repo.owner.login; repo = pr.head.repo.name; ref = pr.head.ref;
        $("#gh-ref").value = ref;
        var m = ref.match(/^(?:report|decisions)\/([^\/]+)\//);
        if (m && !project) { project = m[1]; $("#gh-project").value = project; }
      }
      if (!ref) ref = (await getJSON("https://api.github.com/repos/" + owner + "/" + repo)).default_branch;
      // Read everything at one commit: raw files by branch name can be minutes stale right after a push,
      // and a commit gives a consistent snapshot of reports and decisions.
      var sha = null;
      try { sha = (await getJSON("https://api.github.com/repos/" + owner + "/" + repo + "/commits/" + encodeURIComponent(ref))).sha; }
      catch (e) { if (e.status !== 404 && e.status !== 422) throw e; }
      var at = sha || ref;
      var api = function (path) { return "https://api.github.com/repos/" + owner + "/" + repo + "/contents/" + path + "?ref=" + encodeURIComponent(at); };
      var raw = function (path) { return "https://raw.githubusercontent.com/" + owner + "/" + repo + "/" + encRef(at) + "/" + path; };
      if (!project) {
        var listed = null;
        try { listed = await getJSON(api("projects")); } catch (e) { if (e.status !== 404) throw e; }
        var list = (listed || []).filter(function (x) { return x.type === "dir"; }).map(function (x) { return x.name; });
        var dl = UI.clear($("#gh-projects")); list.forEach(function (n) { dl.appendChild(h("option", { value: n })); });
        if (list.length === 1) { project = list[0]; $("#gh-project").value = project; }
        else { say(list.length ? "Pick a project: " + list.join(", ") + "." : listed ? "There are no projects in projects/ yet. Add one with Set up a project." : "No projects/ folder found in this repo.", list.length ? "info" : "warn"); return; }
      }
      say("Loading " + project + "…");
      var base = "projects/" + project + "/";
      var listing = [];
      try { listing = await getJSON(api(base + "reports")); } catch (e) { if (e.status !== 404) throw e; }
      var folders = listing.filter(function (x) { return x.type === "dir"; }).map(function (x) { return x.name; }).sort();
      var side = {};
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
      await chooseProject(scanEntries(entries), "the sample grading repo");
    } catch (err) { UI.toast("Couldn't load the sample: " + err.message); }
  }

  // ------------------------------------------------------------------ analysis
  async function analyze() {
    UI.clear($("#engine-error"));
    $("#analyze").disabled = true; $("#analyze").textContent = "Reviewing…";
    try {
      var current, prev = null, runs = [];
      if (source && source.history.length) {
        var hr = source.history[sel.report];
        current = await hr.get();
        runs = await hr.runs();
        if (sel.compare >= 0 && sel.compare !== sel.report) prev = await source.history[sel.compare].get();
      }
      var looseReport = byRole("report")[0];
      if (!current && looseReport) current = looseReport.json;
      if (!current) return;
      if (!prev && byRole("previous")[0]) prev = byRole("previous")[0].json;
      runs = runs.concat(byRole("run").map(function (r) { return r.json; }));
      var text = function (role) { var f = byRole(role)[0]; return f ? f.text : null; };
      var base = { project_toml: text("project"), org_toml: text("org"), decisions_json: text("decisions"), dispositions_json: text("dispositions") };
      if (!info) info = await GK.call("info", {});
      var consensus = null;
      if (runs.length) {
        var all = (current.benchmarks ? [current] : []).concat(runs);
        if (all.length >= 2) { consensus = await GK.call("consensus", Object.assign({ runs: all }, base)); current = consensus.report; }
      }
      var check = await GK.call("check", Object.assign({ report: current }, base));
      var diff = prev ? (await GK.call("compare", Object.assign({ old: prev, new: current }, base))).diff : null;
      var verify = null, zip = byRole("zip")[0];
      if (zip) { var path = await GK.putFile(zip.bytes, ".zip"); verify = await GK.call("verify_zip", { report: current, zip_path: path }); }
      R = { report: current, check: check, diff: diff, verify: verify, consensus: consensus, project: byRole("project")[0] };
      answers = {};
      renderHistory();
      render();
    } catch (err) {
      UI.clear($("#engine-error")).appendChild(err.gk ? h("div", { class: "banner bad" }, h("b", null, "Couldn't review these files: "), err.message) : UI.engineHelp(err));
    } finally {
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
  function section(title, sub) { return h("div", { style: "margin:26px 0 10px" }, h("h2", { style: "font-family:var(--serif);font-size:1.3rem;margin:0" }, title), sub ? h("p", { class: "hint", style: "margin:4px 0 0;color:var(--muted);font-size:.9rem" }, sub) : null); }
  function evidenceList(evs) {
    return h("ul", { style: "margin:4px 0;padding-left:18px" }, (evs || []).map(function (e) {
      if (e.type === "code") return h("li", null, h("code", null, e.file + ":" + e.lines), " ", e.note || "", e.quote ? h("pre", { style: "margin:4px 0;font-size:.78rem;white-space:pre-wrap" }, e.quote) : null);
      if (e.type === "command") return h("li", null, h("code", null, e.command), " ", e.note || "", h("pre", { style: "margin:4px 0;font-size:.78rem;white-space:pre-wrap" }, e.excerpt));
      if (e.type === "withheld") return h("li", null, h("span", { class: "badge" }, "details withheld"), " ", e.note || "");
      return h("li", null, "Searched for ", h("b", null, e.searched), " (", e.method, ") ", e.note || "");
    }));
  }

  // ------------------------------------------------------------------ render
  function render() {
    $("#results").hidden = false;
    var banners = UI.clear($("#result-banners"));
    var c = R.check, roll = c.rollup;
    if (R.consensus) banners.appendChild(h("div", { class: "banner info" }, "Showing the consensus of " + R.consensus.overall_by_run.length + " runs (median scores). ",
      R.consensus.unstable.length ? "Runs disagreed on " + R.consensus.unstable.join(", ") + ". " : "Runs agreed. ", "Download it as report.json under More → Downloads, and add it to the report's folder."));
    if ((R.report.integrity_flags || []).length) banners.appendChild(h("div", { class: "banner bad" }, h("b", null, "Integrity flag: "), "the grader found text in the repo trying to influence grading. Maturity is capped. See More."));
    if (c.validation.errors.length) banners.appendChild(h("div", { class: "banner bad" }, h("b", null, "This report has " + c.validation.errors.length + " error(s). "), "Treat its numbers with caution; usually the fix is to re-run the grader. Details under More."));
    var pub = c.publish || { problems: [] };
    if (pub.public && pub.problems.length) banners.appendChild(h("div", { class: "banner bad" }, h("b", null, "Not safe to commit to a public grading repo: "),
      pub.problems.join("; ") + ". Use the public copy under More → Downloads, or run ", h("code", null, "gradekit redact --in-place"), "."));
    if (!R.project) banners.appendChild(h("div", { class: "banner warn" }, "No project.toml loaded, so the report is checked against suite defaults. Load the whole project, or add project.toml, to check the config properly."));
    else if (!c.config_hash_match) banners.appendChild(h("div", { class: "banner warn" }, "This report was graded with a different config than the project.toml you loaded (weights, gates or zones changed since). Scores still stand; overall and maturity are recomputed with your current config."));
    renderOverview(); renderDecisions(); renderPriorities(); renderScorecard(); renderFindings(); renderCompare(); renderMore();
    var pending = roll.priorities.filter(function (p) { return p.decision && p.decision.status === "pending"; }).length;
    var cnt = $("#dec-count"); cnt.hidden = !pending; cnt.textContent = pending;
    resultTabs.select("overview");
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderOverview() {
    var box = UI.clear($("#panel-overview")), c = R.check, roll = c.rollup, run = R.report.run || {};
    var levels = ["L0", "L1", "L2", "L3", "L4"];
    var names = {}; (info.maturity.levels || []).forEach(function (l) { names[l.level] = l.name; });
    var cur = levels.indexOf(roll.maturity.current_level), nxt = levels.indexOf(roll.maturity.next_level);
    box.appendChild(h("div", { class: "stats-row" },
      h("div", { class: "stat" }, h("div", { class: "k" }, "Overall"), h("div", { class: "v" }, roll.overall_score === null ? "–" : String(roll.overall_score)),
        h("div", { class: "s" }, roll.overall_cap_applied ? "Capped by a failed gate (" + roll.overall_score_uncapped + " before the cap)" : "Weighted average out of 10")),
      h("div", { class: "stat", style: "grid-column:span 2" }, h("div", { class: "k" }, "Maturity"),
        h("div", { class: "ladder-h" }, levels.map(function (l, i) {
          return h("div", { class: i === cur ? "current" : i < cur ? "reached" : i === nxt ? "next" : "" }, h("b", null, l), names[l] || "");
        })),
        h("div", { class: "s" }, roll.maturity.next_level ? "Next: " + roll.maturity.next_level + " " + (names[roll.maturity.next_level] || "") : "Top level reached")),
      h("div", { class: "stat" }, h("div", { class: "k" }, "Graded"), h("div", { class: "v", style: "font-size:1.05rem;font-family:var(--mono)" }, String(run.commit || "?").slice(0, 12)),
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
      return h("div", { class: "pbar" }, h("span", null, p + " · " + pname(p)), h("div", { class: "track" }, h("i", { style: "width:" + (v * 10) + "%" })), h("b", null, String(v)));
    }));
    box.appendChild(h("div", { class: "two-col even" },
      h("div", { class: "card" }, h("h2", null, "Checks on this report"), checks),
      h("div", { class: "card" }, h("h2", null, "Gates"), h("p", { class: "hint" }, "Non-negotiable. A gate at 3 or below caps the overall score."), gates,
        h("h2", { style: "margin-top:18px" }, roll.maturity.next_level ? "What blocks " + roll.maturity.next_level : "Maturity"), blockers)));
    box.appendChild(h("div", { class: "card", style: "margin-top:16px" }, h("h2", null, "Pillars"), bars));
  }

  // ------------------------------------------------------------------ decisions
  function renderDecisions() {
    var box = UI.clear($("#panel-decisions"));
    var items = R.check.rollup.priorities.filter(function (p) { return p.decision; });
    if (!items.length) { box.appendChild(h("div", { class: "empty" }, "No decision questions in this report. Nothing to answer.")); return; }
    var nameInput = h("input", { type: "text", placeholder: "you@example.com", value: UI.store.get("decider", ""), "aria-label": "Your name or email", style: "max-width:320px" });
    nameInput.addEventListener("input", function () { UI.store.set("decider", nameInput.value); updateDecisionOutput(); });
    box.appendChild(h("p", { class: "hint", style: "color:var(--muted)" }, "Some fixes need a person's call: they change behavior, drop a feature, or touch a public interface. Improving agents skip them until they're approved. Answer what you can and leave the rest for later."));
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
        seg, h("div", { style: "margin-top:8px" }, txt)));
    });
    box.appendChild(h("div", { class: "card", id: "dec-output", style: "margin-top:18px" }));
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
    try {
      var res = await GK.call("decisions_update", { decisions: decisions, decisions_json: existing ? existing.text : null });
      var project = projectName();
      var path = "projects/" + project + "/decisions.json";
      if (!existing) out.appendChild(h("div", { class: "banner warn" }, "No decisions.json was loaded, so this file contains only today's answers. If the project already has a decisions.json, load it first (loading from the grading repo does this for you) so earlier answers are kept."));
      out.appendChild(h("p", { class: "hint" }, "Your answers have been added to the end of ", h("code", null, "decisions.json"), " (" + items.length + " new). Replace the file's contents with this:"));
      out.appendChild(h("pre", { class: "out-pre", style: "max-height:300px" }, res.json));
      var row = h("div", { class: "row-btns" });
      var copyBtn = h("button", { type: "button", class: "btn primary" }, "Copy decisions.json");
      copyBtn.addEventListener("click", function () { UI.copyText(res.json); });
      var dl = h("button", { type: "button", class: "btn" }, "Download decisions.json");
      dl.addEventListener("click", function () { UI.download("decisions.json", res.json, "application/json"); });
      row.appendChild(copyBtn); row.appendChild(dl);
      out.appendChild(row);
      out.appendChild(h("h3", { style: "font-size:.95rem;margin:18px 0 4px" }, "Where to put it"));
      var branch = (source && source.meta && source.meta.ref && /^report\//.test(source.meta.ref)) ? source.meta.ref : "report/" + project + "/…";
      out.appendChild(h("ol", { class: "steps-mini" },
        h("li", null, h("b", null, "On the report's pull request (suggested): "), "in the grading repo, switch to the PR's branch (", h("code", null, branch), "), open ", h("code", null, path), ", click the pencil (", h("b", null, "Edit"), "), replace everything with the copied file, and ", h("b", null, "commit directly to that branch"), ". Then merge the PR."),
        h("li", null, h("b", null, "Report already merged: "), "open ", h("code", null, path), " on the default branch, click ", h("b", null, "Edit"), ", paste, and choose ", h("b", null, "Create a new branch"), " named ", h("code", null, "decisions/" + project + "/" + date), " to open a small pull request."),
        h("li", null, h("b", null, "Local files: "), "save it as ", h("code", null, "decisions.json"), " in the project's folder.")));
      out.appendChild(h("p", { class: "kbd-note" }, "Permissions: editing on GitHub needs write access to the grading repo. Answers are only ever added, never edited; the newest answer to a question wins."));
    } catch (err) { out.appendChild(h("div", { class: "banner bad" }, err.message)); }
  }, 200);

  // ------------------------------------------------------------------ priorities
  function renderPriorities() {
    var box = UI.clear($("#panel-priorities"));
    var prios = R.check.rollup.priorities;
    if (!prios.length) { box.appendChild(h("div", { class: "empty" }, "No improvement actions in this report.")); return; }
    box.appendChild(h("p", { class: "hint", style: "color:var(--muted)" }, "The order improving agents work in. gradekit ranks it: failed gates and critical problems in hot code first, then what blocks the next maturity level, then the rest by weight × points gained × zone ÷ effort."));
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
    box.appendChild(h("p", { class: "hint", style: "color:var(--muted)" }, "Bars show the score; the tick marks the target. Click a row for its evidence, findings and next actions."));
    var pillars = {};
    R.report.benchmarks.forEach(function (b) { (pillars[b.pillar] = pillars[b.pillar] || []).push(b); });
    Object.keys(pillars).forEach(function (p) {
      var ps = roll.pillar_scores[p];
      box.appendChild(section(p + " · " + pname(p) + (ps !== null && ps !== undefined ? "  —  " + ps : "")));
      box.appendChild(h("div", { class: "card", style: "padding:6px 16px" }, pillars[p].map(function (b) {
        var na = b.applicability === "not_applicable";
        var target = roll.targets[b.id];
        var bar = na ? h("span", { class: "kbd-note" }, "not applicable") : h("div", { class: "track barcell" }, h("i", { style: "width:" + (b.score * 10) + "%" }), target ? h("span", { class: "tgt", style: "left:calc(" + (target * 10) + "% - 1px)" }) : null);
        var head = h("button", { type: "button", "aria-expanded": "false" },
          h("span", { class: "id" }, b.id),
          h("span", null, b.name, " ", gates.indexOf(b.id) >= 0 ? h("span", { class: "chip gate" }, "gate") : null, " ",
            b.applicability === "limited" ? h("span", { class: "badge warn", title: b.applicability_reason || "" }, "limited") : null,
            h("span", { class: "kbd-note" }, "  weight " + b.weight)),
          bar, h("span", { class: "score" }, na ? "–" : String(b.score)), h("span", { class: "chev" }, "›"));
        var body = h("div", { class: "body", hidden: true });
        var wrap = h("div", { class: "bench" }, head, body);
        head.addEventListener("click", function () {
          var open = body.hidden; body.hidden = !open; head.setAttribute("aria-expanded", String(open)); wrap.setAttribute("open-state", open ? "open" : "");
          if (open && !body.firstChild) fillBench(body, b, findings, fz, target);
        });
        return wrap;
      })));
    });
  }
  function fillBench(body, b, findings, fz, target) {
    if (b.applicability !== "full") body.appendChild(h("p", null, h("b", null, "Applicability: "), b.applicability + " — " + (b.applicability_reason || "")));
    if (b.weight_note) body.appendChild(h("p", null, h("b", null, "Grader's weight note: "), b.weight_note));
    body.appendChild(h("p", { class: "kbd-note" }, "Score " + (b.score === null ? "–" : b.score) + (target ? " · target " + target : "") + " · confidence " + (b.confidence || "–") + (b.previous_score !== null && b.previous_score !== undefined ? " · was " + b.previous_score : "")));
    if (b.change_explanation) body.appendChild(h("p", null, h("b", null, "What changed: "), b.change_explanation));
    if ((b.caps_applied || []).length) body.appendChild(h("p", null, h("b", null, "Capped: "), b.caps_applied.join("; ")));
    if ((b.gaming_flags || []).length) body.appendChild(h("div", { class: "banner bad" }, h("b", null, "Gaming flags: "), b.gaming_flags.join("; ")));
    if ((b.strengths || []).length) { body.appendChild(h("h4", null, "Strengths")); b.strengths.forEach(function (s) { body.appendChild(h("div", null, s.note, evidenceList(s.evidence))); }); }
    if ((b.finding_ids || []).length) {
      body.appendChild(h("h4", null, "Findings"));
      b.finding_ids.forEach(function (id) {
        var f = findings[id], z = fz[id] || {};
        if (!f) return;
        body.appendChild(h("div", { style: "margin:6px 0" }, h("b", null, id + " "), sevBadge(z.effective_severity || f.severity), " ", zoneBadge(z.criticality), " ", h("span", { class: "badge" }, f.status), " ", f.title, " ", withheldBadge(f), evidenceList(f.evidence)));
      });
    }
    if ((b.path_to_target || []).length) {
      body.appendChild(h("h4", null, "Path to target"));
      body.appendChild(h("ol", { style: "margin:4px 0;padding-left:20px" }, b.path_to_target.map(function (a) {
        return h("li", null, a.action, h("span", { class: "kbd-note" }, "  (" + a.id + ", effort " + a.effort + ", → " + a.expected_new_score + (a.requires_human_decision ? ", needs a decision" : "") + ")"));
      })));
    }
  }

  // ------------------------------------------------------------------ findings
  function renderFindings() {
    var box = UI.clear($("#panel-findings"));
    var fz = R.check.rollup.finding_zones, list = R.report.findings || [];
    if (!list.length) { box.appendChild(h("div", { class: "empty" }, "No findings.")); return; }
    var f = { zone: "all", sev: "all", status: "open" };
    function selectFilter(label, key, opts) {
      var sel = h("select", { "aria-label": label, style: "width:auto" }, opts.map(function (o) { return h("option", { value: o[0] }, o[1]); }));
      sel.value = f[key]; sel.addEventListener("change", function () { f[key] = sel.value; draw(); });
      return h("label", null, label + " ", sel);
    }
    box.appendChild(h("div", { class: "filters" },
      selectFilter("Zone", "zone", [["all", "All"], ["hot", "Hot"], ["normal", "Normal"], ["cold", "Cold"]]),
      selectFilter("Severity", "sev", [["all", "All"], ["critical", "Critical"], ["major", "Major"], ["minor", "Minor"]]),
      selectFilter("Status", "status", [["open", "Open (new, open, regressed)"], ["all", "All"], ["fixed", "Fixed"], ["accepted", "Accepted"]]),
      h("span", { class: "kbd-note" }, "Severity shown is effective: one higher in hot zones, one lower in cold.")));
    var tableWrap = h("div", { class: "card", style: "padding:4px 12px" });
    box.appendChild(tableWrap);
    function draw() {
      var rows = list.filter(function (x) {
        var z = fz[x.id] || {};
        var openish = ["new", "open", "regressed"].indexOf(x.status) >= 0;
        return (f.zone === "all" || z.criticality === f.zone) && (f.sev === "all" || z.effective_severity === f.sev) &&
               (f.status === "all" || (f.status === "open" ? openish : x.status === f.status));
      });
      UI.clear(tableWrap).appendChild(rows.length ? h("table", { class: "findings" }, h("thead", null, h("tr", null, ["ID", "Severity", "Zone", "Status", "Finding"].map(function (t) { return h("th", null, t); }))),
        h("tbody", null, rows.map(function (x) {
          var z = fz[x.id] || {};
          return h("tr", null, h("td", null, h("code", null, x.id)), h("td", null, sevBadge(z.effective_severity || x.severity), z.effective_severity && z.effective_severity !== x.severity ? h("div", { class: "kbd-note" }, "was " + x.severity) : null),
            h("td", null, zoneBadge(z.criticality), z.zone ? h("div", { class: "kbd-note" }, z.zone) : null), h("td", null, x.status), h("td", null, x.title, " ", withheldBadge(x), x.disposition ? h("div", { class: "kbd-note" }, "Accepted: " + x.disposition) : null));
        }))) : h("div", { class: "empty" }, "No findings match these filters."));
    }
    draw();
  }

  // ------------------------------------------------------------------ compare
  function renderCompare() {
    var box = UI.clear($("#panel-compare")), d = R.diff;
    if (!d) {
      box.appendChild(h("div", { class: "empty" }, h("p", null, "Load an earlier report to see what changed."),
        h("p", { class: "kbd-note" }, "Load the whole project (from the grading repo, a folder or a zip) and the previous report is picked automatically; or drop an earlier report.json.")));
      return;
    }
    box.appendChild(h("div", { class: "banner " + (d.verdict === "PASS" ? "info" : "bad") }, h("b", null, d.verdict === "PASS" ? "Nothing got worse. " : "Something got worse. "),
      "Overall " + d.overall.old + " → " + d.overall.new + " · maturity " + d.maturity.old + " → " + d.maturity.new + " · commit " + String(d.from_commit).slice(0, 8) + " → " + String(d.to_commit).slice(0, 8)));
    if (d.regressions.length) box.appendChild(h("div", { class: "card" }, h("h2", null, "Regressions"), h("ul", null, d.regressions.map(function (r) { return h("li", null, r); }))));
    box.appendChild(h("div", { class: "two-col even", style: "margin-top:16px" },
      h("div", { class: "card" }, h("h2", null, "Score changes"), d.score_changes.length ? h("table", null, h("tbody", null, d.score_changes.map(function (c) {
        var up = c.new !== null && c.old !== null && c.new > c.old;
        return h("tr", null, h("td", null, h("code", null, c.id)), h("td", null, bname(c.id)), h("td", null, (c.old === null ? "–" : c.old) + " → " + (c.new === null ? "–" : c.new)), h("td", null, h("span", { class: "badge " + (up ? "ok" : "bad") }, up ? "up" : "down")));
      }))) : h("p", { class: "kbd-note" }, "No score changes.")),
      h("div", { class: "card" }, h("h2", null, "Findings"),
        list("New", d.findings.new), list("Fixed", d.findings.fixed), list("Regressed", d.findings.regressed))));
    function list(title, items) {
      return h("div", { style: "margin-bottom:10px" }, h("b", null, title + " (" + items.length + ")"), items.length ? h("ul", { style: "margin:4px 0;padding-left:18px" }, items.map(function (f) {
        return h("li", null, h("code", null, f.id), " ", sevBadge(f.effective_severity), " ", f.title, f.pre_existing ? h("span", { class: "kbd-note" }, " (already there before this change)") : null);
      })) : null);
    }
    if (d.notes.length) box.appendChild(h("div", { class: "card", style: "margin-top:16px" }, h("h2", null, "Notes"), h("ul", null, d.notes.map(function (n) { return h("li", null, n); }))));
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
          leakBox.appendChild(h("div", { class: "banner bad" }, h("b", null, "Not downloaded: "), "withheld details still appear elsewhere in the report. Reword these places in general terms, then try again.",
            h("ul", null, x.leaks.map(function (l) { return h("li", null, l); }))));
          return;
        }
        UI.download("report.json", JSON.stringify(x.report, null, 2) + "\n", "application/json");
      });
      dl.appendChild(red);
    }
    if (dl.firstChild) box.appendChild(h("div", { class: "card" }, h("h2", null, "Downloads"),
      priv || unsafe ? h("div", { class: "banner warn" }, "This report still contains " + (priv ? "per-check hidden-check results" : "") + (priv && unsafe ? " and " : "") +
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

  // ------------------------------------------------------------------ wiring
  document.addEventListener("DOMContentLoaded", function () {
    UI.bindEnginePill($("#engine-pill"));
    GK.load().catch(function (err) { UI.clear($("#engine-error")).appendChild(UI.engineHelp(err)); });
    var loadTabs = UI.tabs($("#load-tabs"));
    loadTabs.select("repo");
    resultTabs = UI.tabs($("#result-tabs"));
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
    var q = new URLSearchParams(location.search);
    $("#gh-repo").value = q.get("repo") || gh.repo || "";
    $("#gh-project").value = q.get("project") || gh.project || "";
    $("#gh-ref").value = q.get("ref") || "";
    if (q.get("repo")) loadGitHub();
  });
})();
