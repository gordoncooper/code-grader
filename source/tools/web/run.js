// Code Grading Suite: "Start a run" page. Builds the prompt to paste into a coding agent.
(function () {
  "use strict";
  var h = UI.h, $ = UI.$, $$ = UI.$$;
  var SITE = new URL("../", document.currentScript.src).href;
  // On a site with several versions, prompts point at this major's own path (e.g. …/v5/), which keeps its rules
  // when a newer major becomes the site's root.
  var AGENT_BASE = SITE;
  if (window.SiteVersions) SiteVersions.then(function (v) {
    if (v && v.current && v.url(v.current) !== AGENT_BASE) { AGENT_BASE = v.url(v.current); if (typeof update === "function") update(); }
  });

  var ROLES = {
    grade:   { title: "Grade the code", who: "GRADER", desc: "A full, read-only audit. Adds one dated report folder for the project.", file: "prompts/cards/grader.md" },
    review:  { title: "Review a report", who: "REPORT REVIEWER", desc: "An agent checks a grader's report and prepares the decision questions. People can use the Review page instead.", file: "prompts/cards/reviewer.md" },
    improve: { title: "Improve the code", who: "IMPROVER", desc: "Works down the report's ranked priorities and stops at each benchmark's target.", file: "prompts/cards/improver.md" },
    prcheck: { title: "Check a pull request", who: "PR CHECKER", desc: "Re-grades only what a code change touches and returns PASS or FAIL.", file: "prompts/cards/pr-check.md" }
  };
  // [title, description, permissions]
  var DELIVERY = {
    grade: {
      pr: ["Open a pull request", "Adds only the new report folder to the grading repo, on its own branch. You answer decisions on that PR and merge it.", "push branches and open PRs on the grading repo"],
      save: ["Save the files locally", "Writes the report folder into the project folder. No git.", "write access to that folder"],
      "return": ["Give them back in the chat", "For when the agent can't write anywhere; you save the files.", "none beyond reading the code"]
    },
    review: {
      pr: ["Work on the report's pull request", "Comments with its check; commits decisions to the PR only if agents may decide.", "comment on and push to the report PR"],
      followup: ["Open a follow-up decisions PR", "For a report that's already merged.", "push branches and open PRs on the grading repo"],
      save: ["Edit local files", "", "write access to the project folder"],
      "return": ["Give everything back in the chat", "You paste anything you want to keep.", "none"]
    },
    improve: {
      pr: ["Open a pull request", "Pushes a branch and opens a PR on the code repo, with an improvement log.", "push branches and open PRs on the code repo"],
      commit: ["Commit locally", "Commits on a local branch, without pushing.", "a local clone"],
      save: ["Leave the changes uncommitted", "You review the working tree yourself.", "a local clone"]
    },
    prcheck: {
      comment: ["Comment on the pull request", "Posts PASS or FAIL with a short summary.", "comment on the code repo's PRs"],
      save: ["Save the results", "Writes pr-report.json and pr-comment.md to a folder.", "write access to that folder"],
      "return": ["Give results back in the chat", "", "none"]
    }
  };

  var s = Object.assign({ role: "grade", where: "cloud", code: "url", codeLoc: "", gdir: "repo", gdirRepo: "", gdirLocal: "", project: "", projectAuto: true,
                          suite: "site", suiteLoc: "", delivery: null, commit: "", runs: "1", reportLoc: "", guidance: "",
                          budget: "tier01", branch: "", pr: "", improveSource: "repo", size: "medium", deliveries: {} },
                        UI.store.get("run2", {}));

  // ---------------------------------------------------------------- remembered projects
  // Each project's settings are kept in this browser, so the next run of it is one click.
  // Per-run details (commit, PR, branch, report) aren't kept: they change every time.
  var KEEP = ["where", "code", "codeLoc", "gdir", "gdirRepo", "gdirLocal", "suite", "suiteLoc", "runs", "budget",
              "improveSource", "guidance", "size", "deliveries"];
  var MAX_PROJECTS = 8;
  function savedProjects() { return UI.store.get("run:projects", {}); }
  function rememberProject() {
    var name = slugName(s.project);
    if (!name) return;
    var all = savedProjects(), keep = { used: Date.now() };
    KEEP.forEach(function (k) { keep[k] = s[k]; });
    all[name] = keep;
    var names = Object.keys(all).sort(function (a, b) { return all[b].used - all[a].used; });
    names.slice(MAX_PROJECTS).forEach(function (n) { delete all[n]; });
    UI.store.set("run:projects", all);
  }
  var rememberLater = UI.debounce(function () { rememberProject(); renderSaved(); }, 600);
  function useProject(name) {
    var saved = savedProjects()[name];
    if (!saved) return;
    KEEP.forEach(function (k) { if (saved[k] !== undefined) s[k] = saved[k]; });
    s.project = name; s.projectAuto = false;
    s.commit = ""; s.pr = ""; s.branch = ""; s.reportLoc = "";
    s.delivery = (s.deliveries || {})[s.role] || null;
    $("#code-loc").value = s.codeLoc || "";
    $("#gdir-loc").value = gdirLoc() || "";
    $("#suite-loc").value = s.suiteLoc || "";
    ["where", "code", "gdir", "suite"].forEach(function (n) { $$("input[name=" + n + "]").forEach(function (r) { r.checked = s[n] === r.value; }); });
    $("#size").value = s.size;
    renderDelivery(); renderExtras(); update();
    UI.toast("Settings for " + name + " restored");
  }
  function renderSaved() {
    var all = savedProjects(), names = Object.keys(all).sort(function (a, b) { return all[b].used - all[a].used; });
    var box = UI.clear($("#saved-projects"));
    $("#saved-card").hidden = !names.length;
    names.forEach(function (n) {
      var use = h("button", { type: "button", class: "saved-chip" + (n === slugName(s.project) ? " on" : ""), "aria-pressed": String(n === slugName(s.project)) }, n);
      use.addEventListener("click", function () { useProject(n); });
      var forget = h("button", { type: "button", class: "icon-btn", "aria-label": "Forget " + n }, "×");
      forget.addEventListener("click", function () { var a = savedProjects(); delete a[n]; UI.store.set("run:projects", a); renderSaved(); });
      box.appendChild(h("span", { class: "saved" }, use, forget));
    });
  }

  // ---------------------------------------------------------------- what to expect
  // Rough agent time for a capable coding agent, by task and code size. Cost follows time.
  var SIZES = { small: "Small (under 10k lines)", medium: "Medium (10k–100k lines)", large: "Large (over 100k lines)" };
  var MINUTES = {
    grade:   { small: [20, 40], medium: [45, 90], large: [90, 180] },
    review:  { small: [10, 20], medium: [15, 30], large: [20, 45] },
    improve: { small: [30, 60], medium: [60, 120], large: [120, 240] },
    prcheck: { small: [5, 15], medium: [10, 25], large: [15, 40] }
  };
  function span(m) {
    function f(x) { return x < 60 ? x + " min" : (x % 60 ? (x / 60).toFixed(1).replace(/\.0$/, "") : x / 60) + " h"; }
    return m[0] < 60 && m[1] >= 60 ? f(m[0]) + " to " + f(m[1]) : f(m[0]).replace(/ (min|h)$/, "") + "–" + f(m[1]);
  }
  function expectations() {
    var m = MINUTES[s.role][s.size || "medium"].slice();
    if (s.role === "improve" && s.budget === "all") m = [m[0] * 2, m[1] * 2];
    if (s.role === "improve" && s.budget === "top5") m = [Math.round(m[0] * 0.75), Math.round(m[1] * 0.75)];
    var lines = [h("li", null, h("b", null, "Agent time: "), "about " + span(m) + (s.role === "grade" && s.runs === "3" ? " per grader; run the three side by side" : "") + ".")];
    var cost = s.role === "grade" && s.runs === "3" ? "Three graders cost about three times one. Worth it for milestones, not every cycle."
             : s.role === "prcheck" ? "The cheapest run: it only re-grades what the change touches."
             : s.role === "improve" ? "Grows with the budget. Smaller batches cost less and are easier to review."
             : "Cost follows the agent time.";
    lines.push(h("li", null, h("b", null, "Cost: "), cost));
    var you = { grade: "Answer the decision questions in the report (usually a few minutes), then merge it.",
                review: "Read its recommendations and answer the decisions.",
                improve: "Review its pull request like any other.",
                prcheck: "Nothing, unless it fails." }[s.role];
    lines.push(h("li", null, h("b", null, "Your part: "), you));
    UI.clear($("#expect")).appendChild(h("ul", { class: "expect" }, lines));
  }

  // The cycle, and where this run sits in it.
  var CYCLE = [["grade", "Grade"], ["review", "Decide"], ["improve", "Improve"], ["prcheck", "Check"]];
  function renderCycle() {
    UI.clear($("#cycle")).appendChild(h("ol", { class: "cycle", "aria-label": "The cycle" }, CYCLE.map(function (c) {
      return h("li", c[0] === s.role ? { class: "on", "aria-current": "step" } : null, c[1]);
    })));
  }
  var promptTab = 1;

  function today() { return new Date().toISOString().slice(0, 10); }
  function slugName(v) { return String(v || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, ""); }
  function repoName(url) { var m = String(url || "").trim().replace(/\.git$/, "").replace(/\/+$/, "").match(/([^\/:\\]+)$/); return m ? slugName(m[1]) : ""; }
  function project() { return slugName(s.project) || "<project>"; }
  function recommended(role) {
    var repo = s.gdir === "repo";
    return { grade: repo ? "pr" : "save", review: repo ? "pr" : "return", improve: s.code === "url" ? "pr" : "commit",
             prcheck: s.code === "url" ? "comment" : "return" }[role];
  }

  function renderRoles() {
    var box = UI.clear($("#roles"));
    Object.keys(ROLES).forEach(function (k) {
      var r = h("input", { type: "radio", name: "role", value: k }); r.checked = s.role === k;
      r.addEventListener("change", function () { s.role = k; s.delivery = (s.deliveries || {})[k] || null; promptTab = 1; renderDelivery(); renderExtras(); update(); });
      box.appendChild(h("label", { class: "choice" }, r, h("b", null, ROLES[k].title), h("span", null, ROLES[k].desc)));
    });
  }

  function renderDelivery() {
    var box = UI.clear($("#delivery"));
    var opts = DELIVERY[s.role], rec = recommended(s.role);
    var remembered = (s.deliveries || {})[s.role];
    if (!s.delivery || !opts[s.delivery]) s.delivery = remembered && opts[remembered] ? remembered : rec;
    Object.keys(opts).forEach(function (k) {
      var r = h("input", { type: "radio", name: "delivery", value: k }); r.checked = s.delivery === k;
      r.addEventListener("change", function () { s.delivery = k; s.deliveries = Object.assign({}, s.deliveries); s.deliveries[s.role] = k; update(); });
      box.appendChild(h("label", { class: "choice" }, r, k === rec ? h("span", { class: "tag" }, "Suggested") : null,
        h("b", null, opts[k][0]), opts[k][1] ? h("span", null, opts[k][1]) : null, h("span", { style: "margin-top:4px;font-size:.76rem" }, "Needs: " + opts[k][2])));
    });
  }

  function field(label, input, hint) { return h("div", { class: "field" }, h("label", null, label, input), hint ? h("small", null, hint) : null); }
  function bindInput(el, key) { el.value = s[key] || ""; el.addEventListener("input", function () { s[key] = el.value; update(); }); return el; }
  function seg(name, key, opts) {
    return h("div", { class: "seg", role: "radiogroup" }, opts.map(function (o) {
      var r = h("input", { type: "radio", name: name, value: o[0] }); r.checked = s[key] === o[0];
      r.addEventListener("change", function () { s[key] = o[0]; update(); });
      return h("label", null, r, h("span", null, o[1]));
    }));
  }

  function renderExtras() {
    var box = UI.clear($("#extras"));
    if (s.role === "grade") {
      box.appendChild(field("Commit to grade ", bindInput(h("input", { type: "text", placeholder: "Leave empty for the latest commit" }), "commit")));
      var runs = h("select", null, h("option", { value: "1" }, "One grader (most cycles)"), h("option", { value: "3" }, "Three independent graders (milestones)"));
      runs.value = s.runs; runs.addEventListener("change", function () { s.runs = runs.value; promptTab = 1; update(); });
      box.appendChild(field("How many graders? ", runs, "Three graders take the median and flag benchmarks where they disagree. You'll get three prompts; run each in its own fresh session."));
    } else if (s.role === "review") {
      box.appendChild(field("Which report? ", bindInput(h("input", { type: "text", placeholder: "The report PR's URL, or leave empty for the latest report" }), "reportLoc")));
      box.appendChild(field("Guidance for decisions (optional) ", bindInput(h("textarea", { rows: "3", placeholder: "e.g. Recommend yes for anything that doesn't change a public API." }), "guidance"),
        "The agent only approves decisions if project.toml allows agent decisions. Otherwise it writes recommendations for you."));
    } else if (s.role === "improve") {
      box.appendChild(h("div", { class: "field" }, h("span", { class: "label" }, "How does it get the report?"),
        seg("isrc", "improveSource", [["repo", "It reads it from the grading repo"], ["files", "I'll hand it the files"]]),
        h("small", null, "Either way, it only looks at the files it's pointed to.")));
      var budget = h("select", null, h("option", { value: "tier01" }, "Fix-first and next-level items (tiers 0–1)"), h("option", { value: "top5" }, "The top 5 priorities"), h("option", { value: "all" }, "Everything below target"));
      budget.value = s.budget; budget.addEventListener("change", function () { s.budget = budget.value; update(); });
      box.appendChild(field("How much? ", budget, "Smaller batches are easier to review."));
      box.appendChild(field("Branch name (optional) ", bindInput(h("input", { type: "text", placeholder: "improve/" + today() }), "branch")));
    } else {
      box.appendChild(field("Pull request ", bindInput(h("input", { type: "text", placeholder: "https://github.com/acme/orders-api/pull/123, or main..my-branch" }), "pr")));
    }
  }

  function suiteLines() {
    if (s.suite === "path") return ["Suite: the Code Grading Suite at " + (s.suiteLoc || "<path to the suite>") + ". Use that folder as SUITE_DIR.",
                                    "Read " + ROLES[s.role].file + " in it completely, then follow it exactly."];
    return ["Suite: open " + AGENT_BASE + "AGENT.md and follow it to download and verify the Code Grading Suite.",
            "Then read suite/" + ROLES[s.role].file + " completely and follow it exactly."];
  }
  function codeLine() {
    var loc = s.codeLoc || (s.code === "url" ? "<code repository URL>" : "<code folder>");
    return "Code: " + loc + (s.code === "url" ? " (clone it into a fresh working copy)" : "");
  }
  function gdirLoc() { return s.gdir === "repo" ? s.gdirRepo : s.gdirLocal; }
  function gradingLines() {
    var loc = gdirLoc() || (s.gdir === "repo" ? "<grading repo URL>" : "<project folder>");
    if (s.gdir === "repo") return ["Grading repo: " + loc, "Project: " + project() + " (folder projects/" + project() + "/)"];
    return ["Project folder: " + loc + " (project.toml, decisions.json, dispositions.json, reports/)", "Project: " + project()];
  }

  function buildPrompt(run) {
    var role = ROLES[s.role], L = [];
    L.push("Act as the " + role.who + " in the Code Grading Suite.", "");
    suiteLines().forEach(function (x) { L.push(x); });
    L.push("", "Inputs:");
    L.push("- " + codeLine());
    var improverFiles = s.role === "improve" && s.improveSource === "files";
    if (!improverFiles) gradingLines().forEach(function (x) { L.push("- " + x); });
    if (s.role === "grade") {
      L.push("- Commit to grade: " + (s.commit || "the latest commit on the default branch"));
      L.push("- Runs: " + (s.runs === "3" ? run + " of 3. Grade independently and write runs/run-" + run + ".json and .md in the report folder instead of report.*" : "1 of 1"));
      if (s.suite === "site") L.push("- Suite website (for the review link in the PR description): " + SITE);
    } else if (s.role === "review") {
      L.push("- Report: " + (s.reportLoc || "the newest report in the project's reports/ folder"));
      if (s.guidance) L.push("- Guidance for decisions: " + s.guidance.replace(/\s+/g, " ").trim());
    } else if (s.role === "improve") {
      if (improverFiles) L.push("- Report and decisions: the files I'm handing you (report.json, decisions.json, project.toml)");
      else L.push("- Report and decisions: read the newest reports/<date>-<commit>/report.json, decisions.json and project.toml from projects/" + project() + "/. Don't look at anything else in the grading repo.");
      L.push("- Work on branch: " + (s.branch || "improve/" + today()));
      L.push("- Budget: " + { tier01: "all tier 0 and tier 1 actions", top5: "the top 5 priorities", all: "everything below target" }[s.budget]);
    } else {
      L.push("- Pull request: " + (s.pr || "<PR URL or BASE..HEAD>"));
    }
    var d = DELIVERY[s.role][s.delivery];
    L.push("", "Delivery: " + s.delivery + " (" + d[0].charAt(0).toLowerCase() + d[0].slice(1) + ")");
    L.push("Permissions you'll need: " + d[2] + ".");
    L.push("");
    if (s.role === "grade") L.push("Work in a fresh, disposable environment with no production credentials. Don't change the code or any existing grading files; only add the new report folder." + (s.delivery === "pr" ? " Never push to the grading repo's default branch." : ""));
    if (s.role === "review") L.push("Don't change the code. Only touch decisions.json as the reviewer prompt allows.");
    if (s.role === "improve") L.push("Never change grading files. Only act on decision questions that are approved in decisions.json.");
    if (s.role === "prcheck") L.push("Don't change the pull request. Use the newest merged report on the grading repo's default branch as the baseline.");
    return L.join("\n");
  }

  function nextSteps() {
    var review = h("a", { href: "review.html" + (s.gdir === "repo" && s.gdirRepo ? "?repo=" + encodeURIComponent(s.gdirRepo) + "&project=" + encodeURIComponent(project()) : "") }, "Review a report");
    var setup = h("a", { href: "setup.html" }, "Set up a project");
    var steps = {
      grade: [
        ["No project.toml for " + project() + " yet? Make one first with ", setup, "."],
        [s.runs === "3" ? "Start three separate, fresh agent sessions and paste one prompt into each." : "Start a fresh agent session and paste the prompt."],
        s.runs === "3" ? ["When all three are done, open ", review, ", load the project and use the consensus as report.json."] :
          ["When it's done, open ", review, " to read it and answer any decision questions."],
        [s.delivery === "pr" ? "Commit your updated decisions.json to the same PR (the Review page shows how), then merge it." : "Save your updated decisions.json in the project folder."]
      ],
      review: [["Paste the prompt into an agent session."], ["Read its verdict and recommendations."], ["Answer the decision questions it lists, here or in ", review, "."]],
      improve: [
        ["Make sure the report is merged and your decisions are in decisions.json."],
        [s.improveSource === "files" ? "Hand the agent report.json, decisions.json and project.toml along with the prompt." : "Give the session read access to the grading repo as well as the code repo."],
        ["Review its pull request like any other. A PR check shows whether anything got worse."]
      ],
      prcheck: [["Paste the prompt into an agent session, or run it from CI."], ["FAIL means something got worse: read the regressions it lists before merging."]]
    }[s.role];
    var after = {
      grade: "Next in the cycle: decide (answer the report's questions), then improve.",
      review: "Next in the cycle: improve, working from the approved decisions.",
      improve: "Next in the cycle: a PR check on its changes, then the next grade.",
      prcheck: "Next in the cycle: merge if it passed; grade again at the next milestone."
    }[s.role];
    var ol = UI.clear($("#next-steps"));
    steps.forEach(function (parts) { ol.appendChild(h("li", null, parts)); });
    UI.clear($("#after")).appendChild(document.createTextNode(after));
  }

  function update() {
    UI.store.set("run2", s);
    var tabsEl = $("#prompt-tabs");
    var multi = s.role === "grade" && s.runs === "3";
    tabsEl.hidden = !multi;
    UI.clear(tabsEl);
    var refocus = tabsEl.contains(document.activeElement);
    if (multi) [1, 2, 3].forEach(function (n) {
      var b = h("button", { type: "button", role: "tab", "aria-selected": String(n === promptTab), "aria-controls": "prompt-out",
                            tabindex: n === promptTab ? "0" : "-1" }, "Run " + n);
      b.addEventListener("click", function () { promptTab = n; update(); });
      tabsEl.appendChild(b);
    });
    if (multi && refocus) tabsEl.querySelector("[aria-selected=true]").focus();
    $("#prompt-out").textContent = buildPrompt(multi ? promptTab : 1);
    $("#code-loc").placeholder = s.code === "url" ? "https://github.com/acme/orders-api" : (s.where === "local" ? "~/code/orders-api" : "/workspace/orders-api");
    $("#gdir-loc").placeholder = s.gdir === "repo" ? "https://github.com/acme/grading" : "~/grading/projects/orders-api";
    $("#gdir-hint").textContent = s.gdir === "repo" ? "The grading repo, with a projects/ folder for every graded codebase." : "A project folder with project.toml, decisions.json, dispositions.json and reports/.";
    $("#project-path").textContent = "projects/" + project() + "/";
    if ($("#project-name").value !== s.project) $("#project-name").value = s.project;
    $("#suite-loc").hidden = s.suite !== "path";
    $("#suite-loc").placeholder = "~/code-grading-suite";
    nextSteps(); expectations(); renderCycle(); rememberLater();
  }

  function bindSeg(name, key, after) {
    $$("input[name=" + name + "]").forEach(function (r) {
      r.checked = s[key] === r.value;
      r.addEventListener("change", function () { if (r.checked) { s[key] = r.value; if (after) after(); update(); } });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    UI.tabKeys($("#prompt-tabs"), function () { return $$("#prompt-tabs button"); });
    renderRoles();
    bindSeg("where", "where", function () { s.delivery = null; renderDelivery(); });
    bindSeg("code", "code", function () { s.delivery = null; renderDelivery(); });
    bindSeg("gdir", "gdir", function () { s.delivery = null; renderDelivery(); $("#gdir-loc").value = gdirLoc() || ""; });
    bindSeg("suite", "suite");
    var code = $("#code-loc");
    code.value = s.codeLoc || "";
    code.addEventListener("input", function () {
      s.codeLoc = code.value;
      if (s.projectAuto) s.project = repoName(code.value);
      update();
    });
    var pn = $("#project-name");
    pn.value = s.project || "";
    pn.addEventListener("input", function () { s.project = pn.value; s.projectAuto = !pn.value; update(); });
    pn.addEventListener("change", function () { s.project = slugName(pn.value); pn.value = s.project; update(); });
    var gl = $("#gdir-loc"); gl.value = gdirLoc() || "";
    gl.addEventListener("input", function () { if (s.gdir === "repo") s.gdirRepo = gl.value; else s.gdirLocal = gl.value; update(); });
    bindInput($("#suite-loc"), "suiteLoc");
    var size = $("#size");
    Object.keys(SIZES).forEach(function (k) { size.appendChild(h("option", { value: k }, SIZES[k])); });
    size.value = s.size || "medium";
    size.addEventListener("change", function () { s.size = size.value; update(); });
    renderSaved();
    renderDelivery(); renderExtras(); update();
    $("#copy-prompt").addEventListener("click", function () { UI.copyText($("#prompt-out").textContent); });
  });
})();
