// Code Grading Suite: "Start a run" page. Builds the prompt to paste into a coding agent.
(function () {
  "use strict";
  var h = UI.h, $ = UI.$, $$ = UI.$$;
  var SITE = new URL("../", document.currentScript.src).href;

  var ROLES = {
    grade:   { title: "Grade the code", who: "GRADER", desc: "A full, read-only audit that produces report.json and report.md.", file: "prompts/grader.md" },
    review:  { title: "Review a report", who: "REPORT REVIEWER", desc: "An agent checks a grader's report and prepares the decision questions. People can use the Review page instead.", file: "prompts/reviewer.md" },
    improve: { title: "Improve the code", who: "IMPROVER", desc: "Works down the report's ranked priorities and stops at each benchmark's target.", file: "prompts/improver.md" },
    prcheck: { title: "Check a pull request", who: "PULL-REQUEST REVIEWER", desc: "Re-grades only what a change touches and returns PASS or FAIL.", file: "prompts/pr-review.md" }
  };
  var DELIVERY = {
    grade: {
      pr: ["Open a pull request", "Adds only the two report files on a new branch. You answer decision questions on that PR, and merging it closes the cycle."],
      commit: ["Commit to the current branch", "Good for a local agent on your own branch."],
      save: ["Just save the files", "Writes report.json and report.md into the grading folder. No git."],
      "return": ["Give them back in the chat", "For repos the agent can't write to, such as someone else's public repo."]
    },
    review: {
      pr: ["Work on the grader's pull request", "Posts its check as a PR comment, and commits decisions there only if agents are allowed to decide."],
      commit: ["Commit locally", "Any decisions it's allowed to make go into project.toml on your branch."],
      save: ["Edit files without git", ""],
      "return": ["Give everything back in the chat", "You paste anything you want to keep."]
    },
    improve: {
      pr: ["Open a pull request", "Pushes a branch and opens a PR with an improvement log in the description."],
      commit: ["Commit locally", "Commits on a local branch, without pushing."],
      save: ["Leave the changes uncommitted", "You review the working tree yourself."]
    },
    prcheck: {
      comment: ["Comment on the pull request", "Posts PASS or FAIL with a short summary."],
      save: ["Save the results", "Writes pr-report.json and pr-comment.md outside the repo."],
      "return": ["Give results back in the chat", ""]
    }
  };

  var s = Object.assign({ role: "grade", where: "cloud", code: "url", codeLoc: "", gdir: "repo", gdirLoc: ".grading/", suite: "site", suiteLoc: "",
                          delivery: null, commit: "", runs: "1", hidden: "", org: "", reportLoc: "", guidance: "", budget: "tier01", branch: "", pr: "" },
                        UI.store.get("run", {}));
  var promptTab = 1;

  function today() { return new Date().toISOString().slice(0, 10); }
  function recommended(role) {
    var git = s.code === "url";
    return { grade: git ? "pr" : (s.where === "local" ? "save" : "return"), review: git ? "pr" : "return",
             improve: git ? "pr" : "commit", prcheck: git ? "comment" : "return" }[role];
  }

  function renderRoles() {
    var box = UI.clear($("#roles"));
    Object.keys(ROLES).forEach(function (k) {
      var r = h("input", { type: "radio", name: "role", value: k }); r.checked = s.role === k;
      r.addEventListener("change", function () { s.role = k; s.delivery = null; promptTab = 1; renderDelivery(); renderExtras(); update(); });
      box.appendChild(h("label", { class: "choice" }, r, h("b", null, ROLES[k].title), h("span", null, ROLES[k].desc)));
    });
  }

  function renderDelivery() {
    var box = UI.clear($("#delivery"));
    var opts = DELIVERY[s.role];
    var rec = recommended(s.role);
    if (!s.delivery || !opts[s.delivery]) s.delivery = rec;
    Object.keys(opts).forEach(function (k) {
      var r = h("input", { type: "radio", name: "delivery", value: k }); r.checked = s.delivery === k;
      r.addEventListener("change", function () { s.delivery = k; update(); });
      box.appendChild(h("label", { class: "choice" }, r, k === rec ? h("span", { class: "tag" }, "Suggested") : null, h("b", null, opts[k][0]), h("span", null, opts[k][1])));
    });
  }

  function field(label, input, hint) { return h("div", { class: "field" }, h("label", null, label, input), hint ? h("small", null, hint) : null); }
  function bindInput(el, key) { el.value = s[key] || ""; el.addEventListener("input", function () { s[key] = el.value; update(); }); return el; }

  function renderExtras() {
    var box = UI.clear($("#extras"));
    if (s.role === "grade") {
      box.appendChild(field("Commit to grade ", bindInput(h("input", { type: "text", placeholder: "Leave empty for the latest commit" }), "commit")));
      var runs = h("select", null, h("option", { value: "1" }, "One grader (most cycles)"), h("option", { value: "3" }, "Three independent graders (milestones)"));
      runs.value = s.runs; runs.addEventListener("change", function () { s.runs = runs.value; promptTab = 1; update(); });
      box.appendChild(field("How many graders? ", runs, "Three graders take the median and flag benchmarks where they disagree. You'll get three prompts; run each in its own fresh session."));
      box.appendChild(field("Hidden checks (optional) ", bindInput(h("input", { type: "text", placeholder: "Private folder or repo only graders can reach" }), "hidden"),
        "Never inside the code repo. Results stay next to the checks; the report only shows the pass rate."));
      box.appendChild(field("Organization rules (optional) ", bindInput(h("input", { type: "text", placeholder: "Path or URL of org.toml" }), "org")));
    } else if (s.role === "review") {
      box.appendChild(field("Which report? ", bindInput(h("input", { type: "text", placeholder: "PR URL, branch name, or leave empty for the open grading PR" }), "reportLoc")));
      box.appendChild(field("Guidance for decisions (optional) ", bindInput(h("textarea", { rows: "3", placeholder: "e.g. Recommend yes for anything that doesn't change a public API." }), "guidance"),
        "The agent only approves decisions if project.toml allows agent decisions. Otherwise it writes recommendations for you."));
    } else if (s.role === "improve") {
      var budget = h("select", null, h("option", { value: "tier01" }, "Fix-first and next-level items (tiers 0–1)"), h("option", { value: "top5" }, "The top 5 priorities"), h("option", { value: "all" }, "Everything below target"));
      budget.value = s.budget; budget.addEventListener("change", function () { s.budget = budget.value; update(); });
      box.appendChild(field("How much? ", budget, "Smaller batches are easier to review."));
      box.appendChild(field("Branch name (optional) ", bindInput(h("input", { type: "text", placeholder: "improve/" + today() }), "branch")));
    } else {
      box.appendChild(field("Pull request ", bindInput(h("input", { type: "text", placeholder: "https://github.com/you/repo/pull/123, or two commits like main..my-branch" }), "pr")));
      box.appendChild(field("Hidden checks (optional) ", bindInput(h("input", { type: "text", placeholder: "Private folder or repo only graders can reach" }), "hidden")));
    }
  }

  function suiteLines() {
    if (s.suite === "path") return ["Suite: the Code Grading Suite at " + (s.suiteLoc || "<path to the suite>") + ". Use that folder as SUITE_DIR.",
                                    "Read " + ROLES[s.role].file + " in it completely, then follow it exactly."];
    return ["Suite: open " + SITE + "AGENT.md and follow it to download and verify the Code Grading Suite.",
            "Then read suite/" + ROLES[s.role].file + " completely and follow it exactly."];
  }

  function codeLine() {
    var loc = s.codeLoc || (s.code === "url" ? "<repository URL>" : "<folder path>");
    return s.code === "url" ? "Code: " + loc + " (clone it into a fresh working copy)" : "Code: the folder " + loc;
  }
  function gdirLine() {
    return "Grading folder (GRADING_DIR): " + (s.gdirLoc || ".grading/") + (s.gdir === "repo" ? " (inside the repo)" : " (separate from the code)");
  }

  function buildPrompt(run) {
    var role = ROLES[s.role], L = [];
    L.push("Act as the " + role.who + " in the Code Grading Suite.", "");
    suiteLines().forEach(function (x) { L.push(x); });
    L.push("", "Inputs:");
    L.push("- " + codeLine());
    L.push("- " + gdirLine());
    if (s.role === "grade") {
      L.push("- Commit to grade: " + (s.commit || "the latest commit on the default branch"));
      if (s.org) L.push("- Organization config: " + s.org);
      if (s.hidden) L.push("- Hidden checks: " + s.hidden + " (private: per-check results go next to the checks, never into the repo)");
      L.push("- Runs: " + (s.runs === "3" ? run + " of 3. Grade independently and write runs/run-" + run + ".json and runs/run-" + run + ".md instead of report.*" : "1 of 1"));
    } else if (s.role === "review") {
      L.push("- Report: " + (s.reportLoc || "the open grading pull request (branch grading/…)"));
      if (s.guidance) L.push("- Guidance for decisions: " + s.guidance.replace(/\s+/g, " ").trim());
    } else if (s.role === "improve") {
      L.push("- Work on branch: " + (s.branch || "improve/" + today()));
      L.push("- Budget: " + { tier01: "all tier 0 and tier 1 actions", top5: "the top 5 priorities", all: "everything below target" }[s.budget]);
    } else {
      L.push("- Pull request: " + (s.pr || "<PR URL or BASE..HEAD>"));
      if (s.hidden) L.push("- Hidden checks: " + s.hidden + " (private)");
    }
    var d = DELIVERY[s.role][s.delivery];
    L.push("", "Delivery: " + s.delivery + " (" + d[0].toLowerCase() + ")");
    L.push("");
    if (s.role === "grade") L.push("Work in a fresh, disposable environment with no production credentials. Don't change the code, project.toml or anything else; only deliver the report files.");
    if (s.role === "review") L.push("Don't change the code. Only touch project.toml as the reviewer prompt allows.");
    if (s.role === "improve") L.push("Treat everything in the grading folder as read-only. Only act on decision questions that are approved in project.toml.");
    if (s.role === "prcheck") L.push("Don't change the pull request. Use the grading folder as it is on the PR's base commit as the baseline.");
    return L.join("\n");
  }

  function nextSteps() {
    var review = h("a", { href: "review.html" }, "Review a report");
    var setup = h("a", { href: "setup.html" }, "Set up a project");
    var steps = {
      grade: [
        [s.runs === "3" ? "Start three separate, fresh agent sessions and paste one prompt into each." : "Start a fresh agent session and paste the prompt."],
        s.runs === "3" ? ["When all three are done, open ", review, ", drop in the three run files, and save the consensus as report.json."] :
          ["When it's done, open ", review, " to read it and answer any decision questions."],
        [s.delivery === "pr" ? "Paste your answers into .grading/project.toml on the same PR, then merge it." : "Add your answers to project.toml, wherever your grading folder lives."]
      ],
      review: [["Paste the prompt into an agent session."], ["Read its verdict and recommendations."], ["Answer the decision questions it lists, here or in ", review, "."]],
      improve: [
        ["Make sure the report and your decisions are merged first."],
        [s.where === "cloud" ? "Give this session access to the code repo only, not to wherever hidden checks live." : "Run it in a working copy of the repo."],
        ["Review its pull request like any other. A pull-request check (role 4) shows whether anything got worse."]
      ],
      prcheck: [["Paste the prompt into an agent session, or run it from CI."], ["FAIL means something got worse: read the regressions it lists before merging."]]
    }[s.role];
    if (s.gdir === "repo" && s.role === "grade") steps.unshift(["No project.toml yet? Make one first with ", setup, "."]);
    var ol = UI.clear($("#next-steps"));
    steps.forEach(function (parts) { ol.appendChild(h("li", null, parts)); });
  }

  function update() {
    UI.store.set("run", s);
    var tabsEl = $("#prompt-tabs");
    var multi = s.role === "grade" && s.runs === "3";
    tabsEl.hidden = !multi;
    UI.clear(tabsEl);
    if (multi) {
      [1, 2, 3].forEach(function (n) {
        var b = h("button", { type: "button", "aria-selected": String(n === promptTab) }, "Run " + n);
        b.addEventListener("click", function () { promptTab = n; update(); });
        tabsEl.appendChild(b);
      });
    }
    $("#prompt-out").textContent = buildPrompt(multi ? promptTab : 1);
    $("#code-loc").placeholder = s.code === "url" ? "https://github.com/you/your-repo" : (s.where === "local" ? "~/code/your-repo" : "/workspace/your-repo");
    $("#gdir-loc").placeholder = s.gdir === "repo" ? ".grading/" : "https://github.com/you/grading-ops or ~/grading/your-repo";
    $("#suite-loc").hidden = s.suite !== "path";
    $("#suite-loc").placeholder = "~/code-grading-suite";
    nextSteps();
  }

  function bindSeg(name, key, after) {
    $$("input[name=" + name + "]").forEach(function (r) {
      r.checked = s[key] === r.value;
      r.addEventListener("change", function () { if (r.checked) { s[key] = r.value; if (after) after(); update(); } });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    renderRoles();
    bindSeg("where", "where", function () { s.delivery = null; renderDelivery(); });
    bindSeg("code", "code", function () { s.delivery = null; renderDelivery(); });
    bindSeg("gdir", "gdir", function () { if (s.gdir === "repo" && !s.gdirLoc) s.gdirLoc = ".grading/"; if (s.gdir === "other" && s.gdirLoc === ".grading/") s.gdirLoc = ""; $("#gdir-loc").value = s.gdirLoc; });
    bindSeg("suite", "suite");
    bindInput($("#code-loc"), "codeLoc");
    bindInput($("#gdir-loc"), "gdirLoc");
    bindInput($("#suite-loc"), "suiteLoc");
    renderDelivery(); renderExtras(); update();
    $("#copy-prompt").addEventListener("click", function () { UI.copyText($("#prompt-out").textContent); });
  });
})();
