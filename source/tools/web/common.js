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
      // Styles only as an object of custom properties or properties, set through the CSSOM: no style
      // attributes, so the pages work under a strict Content-Security-Policy (style-src without 'unsafe-inline').
      else if (k === "style") {
        if (typeof v !== "object") throw new Error("h(): give style as an object, e.g. {\"--w\": \"40%\"}; use classes for the rest");
        Object.keys(v).forEach(function (p) { if (p.slice(0, 2) === "--") el.style.setProperty(p, v[p]); else el.style[p] = v[p]; });
      }
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

  // ------------------------------------------------------------------ components
  // One builder per component; app/components.html shows each in every state. Pages use these instead of
  // their own markup for banners, states, chips, badges, cards, fields, segmented controls, tables and tabs.
  var TONES = ["info", "ok", "warn", "bad"];
  function tone(t) { return TONES.indexOf(t) >= 0 ? t : "info"; }

  // A message across the top of a section: UI.banner("warn", "No project.toml loaded…").
  function banner(t) {
    var kids = Array.prototype.slice.call(arguments, 1);
    return h("div", { class: "banner " + tone(t), role: t === "bad" ? "alert" : null }, kids);
  }

  // What a section shows while it has nothing to show: loading, empty or error.
  //   UI.state("loading", {title: "Reading the report…"})
  //   UI.state("empty", {title: "No findings", message: "…", action: {label: "Load files", onClick: fn}})
  //   UI.state("error", {title: "Couldn't load it", message: err.message, retry: fn})
  function state(kind, o) {
    o = o || {};
    var kids = [];
    if (kind === "loading") kids.push(o.skeleton ? skeleton(o.skeleton) : h("span", { class: "spinner", "aria-hidden": "true" }));
    if (o.title) kids.push(h("p", { class: "state-title" }, o.title));
    if (o.message) kids.push(h("p", null, typeof o.message === "string" ? inline(o.message) : o.message));
    if (o.retry) kids.push(h("button", { type: "button", class: "btn", onclick: o.retry }, o.retryLabel || "Try again"));
    if (o.action) kids.push(o.action.href ? h("a", { class: "btn", href: o.action.href }, o.action.label)
                                          : h("button", { type: "button", class: "btn", onclick: o.action.onClick }, o.action.label));
    var el = h("div", { class: "state " + kind, role: kind === "error" ? "alert" : kind === "loading" ? "status" : null,
                        "aria-busy": kind === "loading" ? "true" : null, dataset: { state: kind } }, kids);
    return el;
  }
  function skeleton(lines) {
    var n = typeof lines === "number" ? lines : 3, out = [];
    for (var i = 0; i < n; i++) out.push(h("i"));
    return h("span", { class: "skeleton", "aria-hidden": "true" }, out);
  }
  // Put a state into a container (replacing what's there), e.g. while waiting on the engine.
  function show(container, kind, o) { return clear(container).appendChild(state(kind, o)); }
  // An error from the engine or the network, as an error state: a gradekit message as it is, anything else explained.
  function failed(err, o) {
    o = o || {};
    if (err && err.gk) return state("error", { title: o.title || "That didn't work", message: err.message, retry: o.retry });
    var msg = (err && err.message) || String(err);
    return state("error", { title: o.title || "Something went wrong", message: msg, retry: o.retry });
  }

  function chip(text, t, title) { return h("span", { class: "chip" + (t ? " " + t : ""), title: title || null }, text); }
  function badge(text, t, title) { return h("span", { class: "badge" + (t ? " " + t : ""), title: title || null }, text); }

  // A card: UI.card({title: "Findings", num: 2, hint: "…", compact: true, id: "x"}, child, …)
  function card(o) {
    o = o || {};
    var kids = Array.prototype.slice.call(arguments, 1);
    var head = o.title ? h(o.level || "h2", { class: o.small ? "sm" : null }, o.num ? h("span", { class: "num" }, String(o.num)) : null, o.title) : null;
    return h("section", { class: "card" + (o.compact ? " compact" : "") + (o.cls ? " " + o.cls : ""), id: o.id || null },
             head, o.hint ? h("p", { class: "hint" }, o.hint) : null, kids);
  }

  // A form field: label, control, help and error, wired together for screen readers.
  //   UI.field({label: "Grading repo", control: input, help: "owner/name", error: null})
  var fieldSeq = 0;
  function field(o) {
    var c = o.control, id = c.id || (c.id = "f-" + (++fieldSeq));
    var help = o.help ? h("small", { class: "help", id: id + "-help" }, o.help) : null;
    var err = o.error ? h("small", { class: "error-text", id: id + "-error" }, o.error) : null;
    var by = [help && help.id, err && err.id].filter(Boolean).join(" ");
    if (by) c.setAttribute("aria-describedby", by);
    if (err) c.setAttribute("aria-invalid", "true"); else c.removeAttribute("aria-invalid");
    return h("div", { class: "field" + (err ? " has-error" : "") + (o.cls ? " " + o.cls : "") },
             h("label", { for: id }, o.label), c, help, err);
  }

  // A segmented control (radio buttons): UI.seg("mode", [{value: "full", label: "Full"}, …], "full", onChange, "Mode")
  function seg(name, options, value, onChange, label) {
    return h("div", { class: "seg", role: "radiogroup", "aria-label": label || null }, options.map(function (opt) {
      var input = h("input", { type: "radio", name: name, value: opt.value, checked: opt.value === value,
                               onchange: function () { if (onChange) onChange(opt.value); } });
      return h("label", null, input, h("span", null, opt.label));
    }));
  }

  // A table that scrolls on its own on narrow screens, with an empty state instead of an empty table.
  //   UI.table({columns: [{label: "ID", cell: function (row) { … }}], rows: [...], empty: {title: "No findings"}, cls: "findings"})
  function table(o) {
    if (!o.rows.length) return state("empty", o.empty || { title: "Nothing to show" });
    // Focusable and labeled, so a table that scrolls sideways on a phone can be scrolled with the keyboard.
    return h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": o.caption || "Table" }, h("table", { class: o.cls || null },
      o.caption ? h("caption", { class: "sr-only" }, o.caption) : null,
      h("thead", null, h("tr", null, o.columns.map(function (c) { return h("th", { scope: "col", class: c.cls || null }, c.label); }))),
      h("tbody", null, o.rows.map(function (r) {
        return h("tr", null, o.columns.map(function (c) { return h("td", { class: c.cls || null }, c.cell(r)); }));
      }))));
  }

  // Tab buttons for UI.tabs: UI.tabBar("result-tabs", [{id: "overview", label: "Overview", count: 3}], "Report sections")
  function tabBar(id, items, label) {
    return h("div", { class: "tabs", id: id, "aria-label": label || null }, items.map(function (t) {
      return h("button", { type: "button", dataset: { tab: t.id } }, t.label, t.count ? h("span", { class: "count" }, String(t.count)) : null);
    }));
  }

  // SVG elements (charts): UI.svg("path", {d: "M0 0L10 10", class: "line"}). Same rules as h(): text stays text.
  var SVGNS = "http://www.w3.org/2000/svg";
  function svg(tag, props) {
    var el = document.createElementNS(SVGNS, tag);
    if (props) Object.keys(props).forEach(function (k) {
      var v = props[k];
      if (v === null || v === undefined || v === false) return;
      if (k.slice(0, 2) === "on" && typeof v === "function") el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, String(v));
    });
    Array.prototype.slice.call(arguments, 2).forEach(function add(c) {
      if (c === null || c === undefined || c === false) return;
      if (Array.isArray(c)) c.forEach(add);
      else el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    });
    return el;
  }

  // ------------------------------------------------------------------ GitHub (public grading repos, no sign-in)
  var gh = {
    parseRepo: function (input) {
      var s = String(input || "").trim().replace(/\.git$/, "");
      var m = s.match(/github\.com\/([^\/]+)\/([^\/#?]+)(?:\/(tree|pull)\/([^?#]+))?/);
      if (m) return { owner: m[1], repo: m[2], kind: m[3], rest: m[4] };
      m = s.match(/^([\w.-]+)\/([\w.-]+)$/);
      return m ? { owner: m[1], repo: m[2] } : null;
    },
    getJSON: async function (url) {
      var r = await fetch(url);
      if (!r.ok) {
        var limited = (r.status === 403 || r.status === 429) && r.headers.get("x-ratelimit-remaining") === "0";
        var reset = limited && Number(r.headers.get("x-ratelimit-reset"));
        var e = new Error(limited ? "GitHub's limit for anonymous requests (60 an hour per network) is used up" + (reset ? "; it resets at " + new Date(reset * 1000).toLocaleTimeString() : "") + ". Try again then, or download the repo and open its files instead" : url.replace(/^https:\/\//, "") + " → " + r.status);
        e.status = r.status; e.limited = limited; throw e;
      }
      return r.json();
    },
    getText: async function (url) { var r = await fetch(url); if (!r.ok) { var e = new Error(r.status === 404 ? "not found" : String(r.status)); e.status = r.status; throw e; } return r.text(); },
    encRef: function (ref) { return ref.split("/").map(encodeURIComponent).join("/"); },
    // One commit of a repo: {owner, repo, ref, sha, raw(path), api(path)}. Raw files by branch name can be minutes
    // stale right after a push, so everything is read at the branch's current commit.
    at: async function (owner, repo, ref) {
      if (!ref) ref = (await gh.getJSON("https://api.github.com/repos/" + owner + "/" + repo)).default_branch;
      var sha = null;
      try { sha = (await gh.getJSON("https://api.github.com/repos/" + owner + "/" + repo + "/commits/" + encodeURIComponent(ref))).sha; }
      catch (e) { if (e.status !== 404 && e.status !== 422) throw e; }
      var at = sha || ref;
      return { owner: owner, repo: repo, ref: ref, sha: sha,
               api: function (path) { return "https://api.github.com/repos/" + owner + "/" + repo + "/contents/" + path + "?ref=" + encodeURIComponent(at); },
               raw: function (path) { return "https://raw.githubusercontent.com/" + owner + "/" + repo + "/" + gh.encRef(at) + "/" + path; } };
    }
  };

  // ------------------------------------------------------------------ code
  // A link to a file's lines at one commit, on GitHub, GitLab or Bitbucket (any self-hosted GitLab too: its URLs have
  // "/-/"). Other hosts: null, and the page shows the path instead.
  function codeLink(repoUrl, commit, file, lines) {
    var u = String(repoUrl || "").trim().replace(/\.git$/, "").replace(/\/+$/, "");
    if (!/^https?:\/\//.test(u) || !commit || !file) return null;
    var m = String(lines || "").match(/^(\d+)(?:-(\d+))?$/), a = m && m[1], b = m && (m[2] || m[1]);
    var path = String(file).split("/").map(encodeURIComponent).join("/");
    if (/github\.com\//.test(u)) return u + "/blob/" + commit + "/" + path + (a ? "#L" + a + (b !== a ? "-L" + b : "") : "");
    if (/bitbucket\.org\//.test(u)) return u + "/src/" + commit + "/" + path + (a ? "#lines-" + a + (b !== a ? ":" + b : "") : "");
    if (/gitlab\./.test(u) || /\/-\//.test(u)) return u.replace(/\/-\/.*$/, "") + "/-/blob/" + commit + "/" + path + (a ? "#L" + a + (b !== a ? "-" + b : "") : "");
    return null;
  }

  // Cited code with line numbers. With context (from a code archive), the lines around it too, cited lines marked.
  //   UI.codeBlock({file, lines, quote, href, context: {start, text: [...], cited: [a, b]}})
  function codeBlock(o) {
    var rows = [], m = String(o.lines || "").match(/^(\d+)(?:-(\d+))?$/);
    if (o.context && o.context.text) {
      o.context.text.forEach(function (t, i) {
        var n = o.context.start + i, hit = n >= o.context.cited[0] && n <= o.context.cited[1];
        rows.push(h("span", { class: "ln" + (hit ? " hit" : ""), dataset: { n: String(n) } }, t || " "));
      });
    } else {
      var first = m ? parseInt(m[1], 10) : null;
      String(o.quote || "").split("\n").forEach(function (t, i) {
        rows.push(h("span", { class: "ln hit", dataset: { n: first ? String(first + i) : "·" } }, t || " "));
      });
    }
    var where = o.file + (o.lines ? ":" + o.lines : "");
    return h("figure", { class: "code" },
      h("figcaption", null, h("code", null, where),
        o.href ? h("a", { href: o.href, class: "small", target: "_blank", rel: "noopener" }, "Open at the graded commit") : null),
      h("pre", null, rows));
  }

  // ------------------------------------------------------------------ saving files
  // Nothing here asks a person to paste JSON or TOML into an editor. Each save offers, best first:
  //   1. the code host does it: a new-file page with the file filled in (GitHub, GitLab), or ticking boxes on a PR;
  //   2. a command or agent prompt that writes the file with gradekit;
  //   3. download, then upload (works on any host, and for local folders).
  // No host fills in an edit of a file that already exists, so existing files go by 2 or 3.

  // {host: "github"|"gitlab"|null, base, branch} for a repo address ("owner/repo" means GitHub).
  function repoHost(repo, branch) {
    var s = String(repo || "").trim().replace(/\.git$/, "").replace(/\/+$/, "");
    if (!s) return null;
    if (/^[\w.-]+\/[\w.-]+$/.test(s)) s = "https://github.com/" + s;
    var m = s.match(/^(https?:\/\/[^\/]+\/.+?)(?:\/-)?\/tree\/([^?#]+)/);
    var base = m ? m[1] : s.replace(/[?#].*$/, ""), br = branch || (m ? decodeURIComponent(m[2]) : null);
    var hostname = (base.match(/^https?:\/\/([^\/]+)/) || [])[1] || "";
    var host = /github/i.test(hostname) ? "github" : (/gitlab/i.test(hostname) || /\/-\//.test(s)) ? "gitlab" : null;
    return { host: host, base: base, branch: br, name: host === "github" ? "GitHub" : host === "gitlab" ? "GitLab" : "your code host" };
  }

  // The host's new-file page with `text` filled in at `path`, or null (unknown host, or too long for an address).
  function newFileLink(repo, path, text, branch) {
    var r = repoHost(repo, branch);
    if (!r || !r.host) return null;
    var br = (r.branch || "main").split("/").map(encodeURIComponent).join("/");
    var parts = path.split("/"), name = parts.pop(), dir = parts.map(encodeURIComponent).join("/");
    var href = r.host === "github"
      ? r.base + "/new/" + br + (dir ? "/" + dir : "") + "?filename=" + encodeURIComponent(name) + "&value=" + encodeURIComponent(text)
      : r.base + "/-/new/" + br + (dir ? "/" + dir : "") + "?file_name=" + encodeURIComponent(name) + "&content=" + encodeURIComponent(text);
    if (href.length > 7500) return null;
    return { href: href, host: r.host, name: r.name, branch: r.branch || "main" };
  }

  function route(title, hint) {
    var el = h("div", { class: "save-route" }, h("h3", { class: "sub-h" }, title));
    if (hint) el.appendChild(h("p", { class: "hint" }, hint));
    return el;
  }

  function shq(s) { s = String(s); return /^[\w@.\/:=+,-]+$/.test(s) ? s : "'" + s.replace(/'/g, "'\\''") + "'"; }

  // UI.saveFile(box, {path, text, repo, branch, exists, mime, agent, downloadId, local})
  //   path: where it goes in the grading repo; repo: the grading repo's address (optional); exists: the file is
  //   already there (no prefilled link then); agent: the prompt for an agent (default: create the file and open a PR).
  function saveFile(box, o) {
    clear(box);
    var name = o.path.split("/").pop(), wrap = h("div", { class: "save-routes" });
    var link = o.exists ? null : newFileLink(o.repo, o.path, o.text, o.branch);
    if (link) {
      var r1 = wrap.appendChild(route("Create it on " + link.name + " (quickest)",
        h("span", null, "Opens " + link.name + "'s new-file page at ", h("code", null, o.path), " on ", h("code", null, link.branch),
          ", with the file filled in. Choose ", h("b", null, link.host === "github" ? "Commit changes… → Create a new branch" : "a new branch with a merge request"),
          " to send it as a pull request.")));
      r1.appendChild(h("div", { class: "row-btns" }, h("a", { class: "btn primary", href: link.href, target: "_blank", rel: "noopener" }, "Open " + link.name + " with " + name + " filled in")));
      if (link.host === "gitlab")
        r1.appendChild(h("p", { class: "kbd-note" }, "Some GitLab versions open the editor empty. If yours does, use Download and upload below."));
    }
    var prompt = o.agent || ("In the grading repo" + (o.repo ? " (" + o.repo + ")" : "") + ", " + (o.exists ? "replace " + o.path + " with" : "create " + o.path + " with") +
      " exactly this content, then commit it on a new branch and open a pull request:\n\n```\n" + o.text.replace(/\n$/, "") + "\n```\n");
    var r2 = wrap.appendChild(route("Ask an agent", "Give this to a coding agent that can push to the grading repo."));
    r2.appendChild(h("div", { class: "row-btns" }, h("button", { type: "button", class: "btn" + (link ? "" : " primary"), onclick: function () { copyText(prompt); } }, "Copy the prompt")));
    var r3 = wrap.appendChild(route("Download and upload",
      h("span", null, "Download it, then add it at ", h("code", null, o.path), ". On GitHub: ", h("b", null, "Add file → Upload files"),
        "; on GitLab: ", h("b", null, "+ → Upload file"), (o.exists ? "; uploading a file with the same name replaces it." : "."),
        o.local ? " In a local folder: " + o.local + "." : "")));
    r3.appendChild(h("div", { class: "row-btns" },
      h("button", { type: "button", class: "btn", id: o.downloadId || null, onclick: function () { download(name, o.text, o.mime); } }, "Download " + name),
      h("button", { type: "button", class: "btn", onclick: function () { copyText(o.text); } }, "Copy")));
    box.appendChild(wrap);
    box.appendChild(h("p", { class: "kbd-note" }, "Permissions: each way needs write access to the grading repo (or a fork to send a pull request from)."));
    return { link: link, prompt: prompt };
  }

  // The `gradekit decide` commands that record these answers (one per distinct answer text).
  function decideCommands(project, decisions) {
    var groups = {}, order = [];
    decisions.forEach(function (d) {
      var key = (d.approved ? "approve" : "decline") + "\u0000" + (d.answer || "") + "\u0000" + (d.decided_by || "");
      if (!groups[key]) { groups[key] = { verb: d.approved ? "--approve" : "--decline", ids: [], answer: d.answer, by: d.decided_by }; order.push(key); }
      groups[key].ids.push(d.action_id);
    });
    return order.map(function (k) {
      var g = groups[k];
      return "gradekit decide --project " + shq(project) + " " + g.verb + " " + g.ids.map(shq).join(" ") + " --by " + shq(g.by || "NAME") +
        (g.answer ? " --answer " + shq(g.answer) : "");
    });
  }

  // Answers become entries appended to the project's decisions.json. Used by Review and the Projects inbox.
  //   UI.saveDecisions(box, {project, decisions: [{action_id, question, approved, answer, decided_by, date}],
  //                          existing: "text of decisions.json" | null, repo: "owner/repo" | URL | null, branch: "report/…" | null})
  async function saveDecisions(box, o) {
    clear(box);
    var path = "projects/" + o.project + "/decisions.json";
    var wrap = box.appendChild(h("div", { class: "save-routes" }));
    var r = repoHost(o.repo);
    if (r && r.host && o.branch && /^report\//.test(o.branch)) {
      var prs = r.host === "github" ? r.base + "/pulls?q=" + encodeURIComponent("is:pr head:" + o.branch)
                                    : r.base + "/-/merge_requests?source_branch=" + encodeURIComponent(o.branch);
      var t = wrap.appendChild(route("Tick the boxes on the report's pull request (quickest)",
        h("span", null, "Its description lists each question with a box to approve it and one to decline it. The grading CI records what you tick under your " + r.name + " login",
          r.host === "gitlab" ? " when you run the merge request's grading-decide job." : ".", " Needs the 5.0 grading CI and write access.")));
      t.appendChild(h("div", { class: "row-btns" }, h("a", { class: "btn primary", href: prs, target: "_blank", rel: "noopener" }, "Open the pull request")));
    }
    var cmds = decideCommands(o.project, o.decisions);
    var where = (o.repo ? " (" + o.repo + ")" : "") + (o.branch ? ", on branch " + o.branch : "");
    var prompt = "In the grading repo" + where + ", record these answers to decision questions with the grading kit, then commit " + path +
      (o.branch ? " and push it to that branch" : " on a new branch and open a pull request") + ":\n\n" + cmds.join("\n") +
      "\n\nDon't edit decisions.json by hand: `gradekit decide` checks each ID against the newest report and only appends.\n";
    var c = wrap.appendChild(route("Run gradekit, or ask an agent to",
      h("span", null, "In the grading repo" + (o.branch ? ", on the report's branch" : "") + ". It checks each answer against the newest report and adds it to the end of ", h("code", null, path), ".")));
    c.appendChild(h("pre", { class: "out-pre scroll-sm", tabindex: "0" }, cmds.join("\n")));
    c.appendChild(h("div", { class: "row-btns" },
      h("button", { type: "button", class: "btn", onclick: function () { copyText(cmds.join("\n") + "\n"); } }, "Copy the commands"),
      h("button", { type: "button", class: "btn", onclick: function () { copyText(prompt); } }, "Copy as a prompt for an agent")));
    var d = wrap.appendChild(route("Download and upload",
      h("span", null, "The whole file with your " + o.decisions.length + " new " + (o.decisions.length === 1 ? "answer" : "answers") + " at the end. Upload it to ",
        h("code", null, path), (o.branch ? " on " + o.branch : ""), " (GitHub: ", h("b", null, "Add file → Upload files"), "; GitLab: ", h("b", null, "+ → Upload file"),
        "), replacing the old one, or save it in the project's folder.")));
    var res;
    try { res = await GK.call("decisions_update", { decisions: o.decisions, decisions_json: o.existing }); }
    catch (err) { d.appendChild(failed(err, { title: "Couldn't write decisions.json" })); return null; }
    if (o.existing === null || o.existing === undefined)
      d.appendChild(banner("warn", "This project's decisions.json wasn't loaded, so this file holds only today's answers. Use one of the ways above, or load the project from the grading repo first so earlier answers are kept."));
    d.appendChild(h("div", { class: "row-btns" },
      h("button", { type: "button", class: "btn", onclick: function () { download("decisions.json", res.json, "application/json"); } }, "Download decisions.json")));
    d.appendChild(h("details", { class: "advanced" }, h("summary", null, "Show the file"), h("pre", { class: "out-pre scroll-sm", tabindex: "0" }, res.json)));
    box.appendChild(h("p", { class: "kbd-note" }, "Permissions: each way needs write access to the grading repo. Answers are only ever added, never edited; the newest answer to a question wins."));
    return res;
  }

  function toast(msg) {
    var t = $(".toast") || ($("main") || document.body).appendChild(h("div", { class: "toast", role: "status" }));
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toast.t); toast.t = setTimeout(function () { t.classList.remove("show"); }, 1800);
  }
  function copyText(text) {
    function fallback() {
      var t = h("textarea", { class: "sr-only", "aria-hidden": "true" }); t.value = text; document.body.appendChild(t); t.select();
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
    return banner("bad",
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
      document.dispatchEvent(new CustomEvent("gk:tab", { detail: { tabs: uid, tab: id } }));
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
  // ------------------------------------------------------------------ guided first run (U4)
  // ?tour=1 on any app page starts it; progress is kept in this browser. Each page marks its steps with
  // UI.tour.done(id). A bar at the top of every app page shows what's done and links to the next step.
  var TOUR = [
    { id: "sample", title: "Open a sample report", href: "review.html?sample=1&tour=1",
      tip: "A grader's report on a small example API: its score, maturity level and gates." },
    { id: "scorecard", title: "Find the weakest benchmark", href: "review.html?sample=1&tour=1#tab=scorecard",
      tip: "The Scorecard tab lists every benchmark with its score, weight and evidence." },
    { id: "decide", title: "Answer a decision question", href: "review.html?sample=1&tour=1#tab=decisions",
      tip: "Some fixes need a person's call. Choose Approve or Decline and see how the answer is saved." },
    { id: "projects", title: "See every project at once", href: "projects.html?sample=1&tour=1",
      tip: "Where each project stands, its trends, and what's waiting on whom." },
    { id: "setup", title: "Set up your own project", href: "setup.html?tour=1",
      tip: "Its address, what kind of project it is, and three questions." },
    { id: "run", title: "Get the prompt for its first grade", href: "run.html?tour=1",
      tip: "Copy the prompt and paste it into a coding agent." }
  ];
  var tour = {
    state: function () { return store.get("tour", null); },
    done: function (id) {
      var t = tour.state(); if (!t || !t.on || t.done[id]) return;
      t.done[id] = new Date().toISOString(); store.set("tour", t); tour.render();
      var step = TOUR.find(function (x) { return x.id === id; });
      if (step) toast("Done: " + step.title.toLowerCase());
    },
    start: function () { var t = tour.state(); if (!t || !t.on) store.set("tour", { on: true, done: (t && t.done) || {} }); },
    end: function () { var t = tour.state() || { done: {} }; t.on = false; store.set("tour", t); tour.render(); },
    render: function () {
      var old = $(".tour-bar"); if (old) old.remove();
      var t = tour.state(), app = $(".app");
      if (!t || !t.on || !app) return;
      var n = TOUR.filter(function (x) { return t.done[x.id]; }).length, next = TOUR.find(function (x) { return !t.done[x.id]; });
      var here = location.pathname.split("/").pop();
      // A step on this page that's a view of it (#tab=…) links to just that view, so the page doesn't reload.
      function hrefOf(x) { var p = x.href.split("#"); return p[1] && p[0].split("?")[0] === here && $("#results") && !$("#results").hidden ? "#" + p[1] : x.href; }
      var list = h("ol", { class: "tour-steps" }, TOUR.map(function (x) {
        return h("li", { class: t.done[x.id] ? "done" : x === next ? "next" : null },
          h("a", { href: hrefOf(x) }, x.title), t.done[x.id] ? h("span", { class: "sr-only" }, " (done)") : null, h("span", { class: "kbd-note" }, " " + x.tip));
      }));
      var bar = h("nav", { class: "tour-bar", "aria-label": "Guided first run" },
        h("div", { class: "tour-head" },
          h("b", null, "Guided first run"),
          h("progress", { max: String(TOUR.length), value: String(n), "aria-label": n + " of " + TOUR.length + " steps done" }),
          h("span", { class: "kbd-note" }, n + " of " + TOUR.length),
          next ? h("span", { class: "tour-next" }, "Next: ", next.href.split("?")[0] === here && !/#/.test(next.href) ? h("b", null, next.title) : h("a", { href: hrefOf(next) }, next.title), h("span", { class: "kbd-note" }, " — " + next.tip))
               : h("span", { class: "tour-next" }, h("b", null, "All done."), " Your project's next step is a grade: paste the prompt into an agent."),
          h("button", { type: "button", class: "btn sm ml-auto", onclick: tour.end }, next ? "End the tour" : "Close")),
        h("details", { class: "advanced" }, h("summary", null, "All steps"), list));
      app.insertBefore(bar, app.firstChild);
    }
  };

  document.addEventListener("DOMContentLoaded", function () {
    terms(document);
    if (new URLSearchParams(location.search).get("tour")) tour.start();
    tour.render();
  });

  // `code` spans in report text (questions, actions) as <code>; everything else stays plain text.
  function inline(text) {
    return String(text == null ? "" : text).split(/`([^`]+)`/).map(function (part, i) { return i % 2 ? h("code", null, part) : part; });
  }
  window.UI = { h: h, $: $, $$: $$, inline: inline, clear: clear, toast: toast, copyText: copyText, download: download, readFile: readFile,
                store: store, debounce: debounce, bindEnginePill: bindEnginePill, engineHelp: engineHelp, dropZone: dropZone, tabs: tabs, tabKeys: tabKeys, terms: terms,
                banner: banner, state: state, show: show, failed: failed, skeleton: skeleton, chip: chip, badge: badge, card: card,
                field: field, seg: seg, table: table, tabBar: tabBar, svg: svg, gh: gh, saveDecisions: saveDecisions, saveFile: saveFile, tour: tour, newFileLink: newFileLink, repoHost: repoHost, decideCommands: decideCommands, codeLink: codeLink, codeBlock: codeBlock };
})();
