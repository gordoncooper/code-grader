# Tests

The kit's test suite. CI runs it on every pull request that touches `source/` or `tests/` (`.github/workflows/tests.yml`).

| File | What it checks | Needs |
|---|---|---|
| `test_gradekit.py` | The engine: paths, zones, report ordering, project discovery, PR-check verdicts, decisions, config fingerprints. Several tests pin bugs fixed in 4.2.1 and 4.2.2. | Python 3.11+ |
| `test_cli.py` | The `gradekit` commands on the bundled example | Python 3.11+ |
| `test_site.py` | Every page, desktop and phone: no errors, no broken links, no sideways scrolling | Chromium |
| `test_pages.py` | Set up, Start a run and Review, driven like a person would (GitHub is mocked) | Chromium |
| `test_static_host.py` | The unmodified site on a plain static server under a sub-path, with the real Pyodide engine | Chromium, internet |

The browser tests build the site from `source/` and run the page's engine calls in CPython, so they need no network. Only `test_static_host.py` loads the real runtime.

```bash
pip install -r tests/requirements.txt
python -m playwright install chromium
python -m pytest tests -m "not browser"     # engine and command line, a few seconds
python -m pytest tests -m browser            # the website, about a minute
```

`GRADEKIT=path/to/gradekit.py` runs the engine tests against another copy, e.g. an older release, to confirm a test catches the bug it pins. `CHROME_PATH` points the browser tests at an installed Chrome instead of Playwright's.
