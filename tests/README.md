# Tests

The kit's test suite. CI runs it on every pull request that touches `source/` or `tests/` (`.github/workflows/tests.yml`).

| File | What it checks | Needs |
|---|---|---|
| `test_gradekit.py` | The engine: paths, zones, report ordering, project discovery, PR-check verdicts, decisions, config fingerprints. Several tests pin bugs fixed in 4.2.1 and 4.2.2. | Python 3.11+ |
| `test_cli.py` | The `gradekit` commands on the bundled example | Python 3.11+ |
| `test_site.py` | Every page, desktop and phone: no errors, no broken links, no sideways scrolling | Chromium |
| `test_pages.py` | Set up, Start a run and Review, driven like a person would (GitHub is mocked) | Chromium |
| `test_static_host.py` | The unmodified site on a plain static server under a sub-path, with the real Pyodide engine | Chromium, internet |
| `test_accessibility.py` | axe-core (pinned, checksummed; downloaded once into `tests/.cache/`) on every page and state at desktop and phone width, with zero violations allowed; keyboard: every control reachable with Tab and showing focus, skip link, arrow keys in tabs, choosing files | Chromium, internet the first time |
| `test_security.py` | Every page carries the content-security policy, and every page and state works under it; Pyodide files that don't match their pins are refused; the pins match the published Pyodide (that one needs the internet) | Chromium |
| `test_visual.py` | Layout at 320, 390, 768 and 1280 px: no sideways scrolling, tap targets of at least 24×24 px, no controls on top of each other or cut off. Plus screenshots compared with the baselines in `visual/` | Chromium, Pillow |

**Content-security policy in tests:** the usual `page` fixture bypasses the pages' policy, so tests can inject axe-core and wait on JavaScript expressions. `strict_page` enforces it, as visitors get it, and records any violations. Use only selector waits with it.

**Screenshot baselines** are compared only on the platform and browser that made them, which is CI's, because fonts render differently on other machines. Elsewhere that test skips itself. CI makes them on its first run and commits them to the pull request. After an intended visual change, add the `update-visual` label to the pull request, or run the Tests workflow by hand with *update_visual* ticked. CI then remakes the baselines and commits them to the branch. Remove the label afterwards, so later pushes are compared again. When a comparison fails, CI uploads the actual and diff images as the `visual-diff` artifact.

Other suites (the agent commands, CI for grading repos, the index, and so on) each have a `test_<feature>.py` file; their docstrings say what they cover.

The browser tests build the site from `source/` and run the page's engine calls in CPython, so they need no network. Only `test_static_host.py` loads the real runtime.

```bash
pip install -r tests/requirements.txt
python -m playwright install chromium
python -m pytest tests -m "not browser"     # engine and command line, a few seconds
python -m pytest tests -m browser            # the website, about a minute
```

`GRADEKIT=path/to/gradekit.py` runs the engine tests against another copy, e.g. an older release, to confirm a test catches the bug it pins. `CHROME_PATH` points the browser tests at an installed Chrome instead of Playwright's.
