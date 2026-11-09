// Code Grading Suite: the components page. Builds every component with the same UI.* calls the tool pages use.
(function () {
  "use strict";
  var h = UI.h;

  function demo(title, note) {
    var kids = Array.prototype.slice.call(arguments, 2);
    return UI.card({ title: title, small: true, hint: note, cls: "demo" }, kids);
  }
  function label(text) { return h("p", { class: "label mt-3 mb-2" }, text); }

  function build() {
    var g = UI.$("#gallery");

    g.appendChild(demo("Buttons", "A primary action, the rest, a small one, an inline text button and an icon button.",
      h("div", { class: "row-btns" },
        h("button", { type: "button", class: "btn primary" }, "Primary"),
        h("button", { type: "button", class: "btn" }, "Default"),
        h("button", { type: "button", class: "btn sm" }, "Small"),
        h("button", { type: "button", class: "btn", disabled: true }, "Disabled"),
        h("button", { type: "button", class: "icon-btn", "aria-label": "Remove" }, "×")),
      h("p", { class: "small" }, "Inline: ", h("button", { type: "button", class: "link" }, "choose files"), " in a sentence.")));

    g.appendChild(demo("Chips and badges", "Chips label data (a benchmark, a change, a gate); badges give a status.",
      label("Chips"),
      h("div", { class: "row-btns" }, UI.chip("A3 Robustness"), UI.chip("B4 +2", "up"), UI.chip("F6 −1", "down"), UI.chip("A2 gate", "gate")),
      label("Badges"),
      h("div", { class: "row-btns" }, UI.badge("neutral"), UI.badge("info", "info"), UI.badge("passed", "ok"), UI.badge("limited", "warn"),
        UI.badge("critical", "bad"), UI.badge("hot", "hot"), UI.badge("cold", "cold"))));

    g.appendChild(demo("Banners", "A message about a whole section. Errors are announced to screen readers.",
      UI.banner("info", h("b", null, "Info. "), "Showing the consensus of 3 runs."),
      UI.banner("ok", h("b", null, "Done. "), "Nothing got worse."),
      UI.banner("warn", h("b", null, "Check this. "), "No project.toml loaded, so the report is checked against defaults."),
      UI.banner("bad", h("b", null, "Problem. "), "This report has 2 errors.")));

    g.appendChild(demo("States", "What a section shows when it has nothing to show yet: loading, empty, or an error with a way forward.",
      label("Loading"),
      UI.state("loading", { title: "Reviewing the report…" }),
      label("Loading, with the shape of what's coming"),
      UI.state("loading", { title: "Loading projects…", skeleton: 3 }),
      label("Empty"),
      UI.state("empty", { title: "No findings", message: "The grader recorded no problems in this report.", action: { label: "Open files", onClick: function () { UI.toast("Open files"); } } }),
      label("Error"),
      UI.state("error", { title: "Couldn't load from GitHub", message: "The repository wasn't found. Check that it's public.", retry: function () { UI.toast("Retrying"); } })));

    var tabs = UI.tabBar("demo-tabs", [{ id: "one", label: "Overview" }, { id: "two", label: "Decisions", count: 3 }, { id: "three", label: "Findings" }], "Demo sections");
    tabs.classList.add("mt-0");
    var panels = h("div", null,
      h("div", { class: "panel", id: "panel-one" }, h("p", { class: "m-0" }, "The first panel. Arrow keys, Home and End move between tabs.")),
      h("div", { class: "panel", id: "panel-two", hidden: true }, h("p", { class: "m-0" }, "Three decisions are waiting.")),
      h("div", { class: "panel", id: "panel-three", hidden: true }, UI.state("empty", { title: "No findings" })));
    g.appendChild(demo("Tabs", "Sections of one view (the WAI-ARIA tabs pattern).", tabs, panels));

    var name = h("input", { type: "text", placeholder: "orders-api" });
    var repo = h("input", { type: "text", value: "not a repo" });
    var mode = h("select", null, h("option", null, "Full audit"), h("option", null, "Pull request check"));
    var notes = h("textarea", { rows: "3", placeholder: "Anything the grader should know" });
    g.appendChild(demo("Fields", "Label, control, help and error, joined up for screen readers.",
      UI.field({ label: "Project", control: name, help: "Lowercase, with dashes." }),
      UI.field({ label: "Grading repo", control: repo, error: "Use owner/name or a github.com URL." }),
      UI.field({ label: "Mode", control: mode }),
      UI.field({ label: "Notes", control: notes }),
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: true }), " Let agent reviewers approve decision questions")));

    g.appendChild(demo("Segmented control", "One choice from a few, all visible.",
      UI.seg("demo-seg", [{ value: "full", label: "Full" }, { value: "pr", label: "PR check" }, { value: "consensus", label: "Consensus" }], "full", null, "Mode")));

    var rows = [{ id: "A3-001", sev: "critical", title: "A zero interval hangs the scheduler" }, { id: "E2-002", sev: "minor", title: "The API reference omits the exception classes" }];
    var cols = [{ label: "ID", cell: function (r) { return h("code", null, r.id); } },
                { label: "Severity", cell: function (r) { return UI.badge(r.sev, r.sev === "critical" ? "bad" : null); } },
                { label: "Title", cell: function (r) { return r.title; } }];
    g.appendChild(demo("Tables", "Scroll sideways on their own on narrow screens; an empty table is an empty state.",
      UI.table({ columns: cols, rows: rows, caption: "Findings", cls: "findings" }),
      label("With no rows"),
      UI.table({ columns: cols, rows: [], empty: { title: "No findings match these filters", message: "Change or clear the filters above." } })));

    g.appendChild(demo("Stats and bars", "Numbers at a glance, and a score against its target.",
      h("div", { class: "stats-row" },
        h("div", { class: "stat" }, h("div", { class: "k" }, "Overall"), h("div", { class: "v" }, "6.8"), h("div", { class: "s" }, "target 8")),
        h("div", { class: "stat" }, h("div", { class: "k" }, "Maturity"), h("div", { class: "v" }, "L1"), h("div", { class: "s" }, "next: L2"))),
      h("div", { class: "pillar-bars" },
        h("div", { class: "pbar" }, h("span", null, "A · Correctness"), h("div", { class: "track" }, h("i", { style: { "--w": "62%" } }), h("span", { class: "tgt", style: { "--at": "80%" } })), h("b", null, "6.2")),
        h("div", { class: "pbar" }, h("span", null, "E · Adoption"), h("div", { class: "track" }, h("i", { style: { "--w": "55%" } }), h("span", { class: "tgt", style: { "--at": "70%" } })), h("b", null, "5.5")))));

    UI.tabs(UI.$("#demo-tabs")).select("one");
  }
  document.addEventListener("DOMContentLoaded", build);
})();
