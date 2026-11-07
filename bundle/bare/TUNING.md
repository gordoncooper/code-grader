# Tuning the suite

Every adjustable part of scoring is plain, commented TOML. You never need to touch the prompts or the code to change weights, gates, zones, targets or maturity rules.

## How configs stack

```
config/defaults.toml   suite defaults: ships with the kit
org.toml               optional: your house rules, shared by every project
project.toml           per project: context, answers, zones, overrides
```

Each layer overrides the one above it. **Tables merge key by key** (setting one weight leaves the others alone). **Lists are replaced whole** (setting `gates.extra` replaces the list rather than appending to it).

```bash
gradekit resolve --config org.toml --config project.toml              # see the result
gradekit resolve --config org.toml --config project.toml --explain F3 # why F3 has the weight it has
gradekit presets --config org.toml                                    # all presets side by side, with your org rules
```

**Org and project configs are owned by people.** `project.toml` normally lives in the repo's `.grading/` folder, protected by CODEOWNERS; the pull-request check fails any improvement PR that changes it. For the strictest setup, keep it in a separate private repo instead.

## Start a project in one minute

The easiest way is the website's **Set up a project** page: pick a preset, answer the questions, mark zones, and download the file. From the command line:

```bash
python3 SUITE_DIR/tools/gradekit.py init --preset service --name orders-api \
    --answer data_sensitivity=financial --grading-dir .grading
python3 SUITE_DIR/tools/gradekit.py resolve
```

`init` writes a commented `project.toml` with every question answered, from the preset plus any `--answer` flags. Edit the file, re-run `resolve`, and check that the weights and gates look right before grading. `config/project.example.toml` is a fully filled-in example.

## What you can tune, from lightest touch to heaviest

### 1. Answer the questions (per project; most common)
Eight questions: data sensitivity, audience, lifespan, failure impact, team, change rate, delivery and scale. They move the weights in well-understood ways and add gates where they matter. If a weight looks wrong, the fix is usually a more accurate answer, not an override.

```toml
[project]
preset = "service"

[answers]
data_sensitivity = "financial"
scale            = "large"
```

### 2. Map criticality zones (per project; highest leverage)
The first matching zone wins, so list specific zones first.

```toml
[[zones]]
name = "payments"
paths = ["src/payments/**", "src/billing/**"]
criticality = "hot"
why = "Moves money"

[[zones]]
name = "tooling"
paths = ["scripts/**", "examples/**", "tests/fixtures/**"]
criticality = "cold"
why = "Never runs in production"
```

Patterns: `**` matches any number of directories, `*` matches within one directory, and a pattern ending in `/` means everything under it. Paths are relative to the repo root.

### 3. Set targets (per project)
```toml
[targets]
mode = "level:L3"          # or "proportional" (default) or "maximal"
overrides = { F4 = 10 }    # this project must be fast, whatever the mode
```

### 4. Override a weight (per project; needs a reason)
```toml
[weights.overrides]
F4 = { weight = 3, reason = "Contractual p99 latency SLA of 50 ms" }
X6 = { weight = 0, reason = "No agents maintain this repo" }   # 0 = doesn't count at all
```

### 5. Add or remove gates
```toml
[gates]
extra   = ["C4"]       # tests are non-negotiable here
exclude = []           # removing A1 or A2 is allowed, but resolve warns loudly
```

### 6. House rules for every project (org.toml)
Anything in `defaults.toml` can be overridden here. Some typical examples:

```toml
# We care more about docs than the defaults do
[weights.base]
E2 = 3

# Hot zones matter even more to us
[zone_settings]
priority_multiplier = { hot = 3.0, normal = 1.0, cold = 0.25 }

# Our teams under-estimate effort
[priorities]
effort_cost = { S = 1, M = 3, L = 8 }
```

To change maturity levels, copy the **whole** `[[maturity.levels]]` section from `defaults.toml` into `org.toml` and edit it there. Lists of tables are replaced whole, so restate every level, not just the one you're changing.

### 7. Add your own question or preset
Questions and presets are just data, so add as many as you like. `resolve` checks every benchmark ID you mention.

```toml
[questions.realtime]
prompt  = "Does it have hard real-time or latency requirements?"
default = "no"
options.no  = { label = "No", effects = {} }
options.yes = { label = "Yes", effects = { F4 = 2, X3 = 1 }, gates = ["F4"] }

[presets.payments_service]
description = "A service that moves money"
answers = { delivery = "service", failure_impact = "revenue_loss", data_sensitivity = "financial", realtime = "yes" }
```

### 8. Accepted findings and decisions (per project)
These also live in `project.toml`, so one file holds everything people decide. Both are **append-only**: add new entries at the end and never edit old ones. For decisions, the newest answer to a question wins.

```toml
[[dispositions]]                 # a finding you accept as-is; it stops lowering the score
finding_id = "B5-001"
decision   = "won't fix"
reason     = "One payment provider is a deliberate constraint through 2027"
decided_by = "jane@example.com"
date       = "2026-11-07"

[[decisions]]                    # an answer to a report's decision question
action_id  = "D1-act-1"
question   = "Implement CSV and XLSX export, or drop the export claim from the README?"
approved   = true
answer     = "Implement CSV only; remove XLSX from the README."
decided_by = "jane@example.com"
date       = "2026-11-07"
```

The **Review a report** page writes `[[decisions]]` blocks for you. Adding dispositions or decisions doesn't change the config fingerprint, so reports stay comparable.

To let agent reviewers approve decision questions (the default is humans only):

```toml
[review]
allow_agent_decisions = true
```

## Good habits

- **Change config between grading cycles, not during one.** Every report records the hash of the config it was graded with. `gradekit validate` rejects a report checked against a different config, and `gradekit diff` warns when two reports used different configs. Otherwise a weight change can look like code getting better or worse.
- **Prefer answers over overrides.** Answers explain *why* a weight is what it is. Overrides are for the odd case the questions don't capture.
- **Recalibrate after big changes.** If you change base weights, gates or maturity rules, re-run calibration (`calibration/README.md`) and note the change in your own changelog.
- **Review the `weight_note`s.** Graders flag weights that look wrong for the code they saw. If the same note keeps coming up, adjust the answer or add an override.
- **Keep it boring.** The defaults are deliberately conservative. Most projects need only a preset, two or three answers and a zone map.
