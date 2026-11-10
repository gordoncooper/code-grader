# Hosting the suite on a web server

The website has three parts: documentation, the agent entry point (`AGENT.md` plus the raw kit files), and the browser tools (**Set up a project**, **Start a run**, **Review a report**, **Projects**). It is all static files, so any web server works.

The web version is a folder of static files. There's no server code, database or build step on the server itself. Copy it to any web server and point coding agents at its `AGENT.md`.

## 1. Build the site

The ready-built site comes in `code-grading-suite-web.zip`. If you've edited the kit (rubric wording, weights, prompts), rebuild it:

```bash
python3 tools/build_web.py --out ../web
```

This regenerates everything from the kit, including checksums. The builder needs Python 3.11+. Rendered HTML pages need `markdown-it-py` or `markdown` (`pip install markdown-it-py`). Without it, the builder still works but shows docs as plain preformatted text. Agents read the raw `.md` files either way.

## 2. Upload it

Copy the *contents* of the built folder to a directory on your server, for example `/var/www/grading/` so it is served at `https://your-server/grading/`. Any path works because every link in the site is relative.

**Recommended: one directory per major version.** Each project pins the major it uses (`suite = "5"` in its `project.toml`), so serve each major at its own path and point agents at that path. An improvement loop that runs for weeks then can't have its rules change underneath it. A minor or patch release replaces its major's directory. The suite's own site does it like this:

```
/grading/              the newest version (optional: a copy of the newest major)
/grading/v5/           the newest 5.x
/grading/v4/           the newest 4.x
/grading/versions.json and one in each vN/ directory
```

`versions.json` lists the versions, newest first, with paths relative to the file. With it, the pages show a version menu, **Start a run** writes prompts that point at the page's own major (`…/v5/AGENT.md`), and `AGENT.md` sends agents to the project's pinned major. Every built site ships a `versions.json` that lists only itself, so a single version needs nothing. To host several, replace the one beside each copy's `index.html`. It isn't in `SHA256SUMS`, because it describes your host rather than the kit:

```json
{"latest": "5.0.1",
 "versions": [{"major": "5", "version": "5.0.1", "path": "v5/"}, {"major": "4", "version": "4.3.0", "path": "v4/"}]}
```

In `/grading/v4/versions.json` the paths are `../v5/` and `../v4/`. On GitHub Pages, this repo's *Publish website* workflow builds the whole layout from the release tags (`.github/scripts/site_versions.py`).

## 3. Make sure file types are served correctly

Agents fetch `.md`, `.json` and `.py` files directly. Some servers send `.md` as a binary download, or without UTF-8, which garbles characters like `→` and `≥`. The configs below fix that.

**Apache:** the included `.htaccess` handles it (needs `AllowOverride FileInfo`, plus `mod_headers` for the security header).

**nginx:**
```nginx
location /grading/ {
    root /var/www;                      # files live in /var/www/grading/
    charset utf-8;
    charset_types text/markdown text/plain application/json text/css application/javascript;
    add_header X-Content-Type-Options nosniff;

    location ~* \.md$          { types { } default_type text/markdown; }
    location ~* \.(py|sql|txt|toml)$ { types { } default_type text/plain; }
}
```

**Caddy:**
```
your-server.example.com {
    root * /var/www
    file_server
    @md path *.md
    header @md Content-Type "text/markdown; charset=utf-8"
    @txt path *.py *.sql *.txt *.toml
    header @txt Content-Type "text/plain; charset=utf-8"
}
```

**Quick local test:**
```bash
cd web && python3 -m http.server 8000
# then open http://localhost:8000/
```

## 4. Check it

```bash
BASE=https://your-server/grading/v5
curl -sI "$BASE/AGENT.md" | grep -i content-type     # expect text/markdown; charset=utf-8
curl -s  "$BASE/SHA256SUMS" -o SHA256SUMS
curl -s  "$BASE/downloads/code-grading-suite-5.0.1.zip" -o code-grading-suite-5.0.1.zip
sha256sum -c SHA256SUMS --ignore-missing              # expect: OK
```

## 5. Point an agent at it

Open the site's landing page. It shows ready-to-copy instructions for the grader, improver and pull-request roles, with your server's URL already filled in. For example:

> Grade the code in this repository using the Code Grading Suite at https://your-server/grading/v5/AGENT.md. Act as the **grader**. …

## Self-hosting the Python runtime

The **Set up a project** and **Review a report** pages (and **Projects**, when it saves decisions) run the suite's own `gradekit.py` in the browser using [Pyodide](https://pyodide.org) (Python compiled to WebAssembly). By default, Pyodide is loaded from the jsDelivr CDN the first time a page needs it: about 12 MB, cached afterwards. Your files are never uploaded; only the runtime is downloaded.

**Every runtime file is checked before it runs.** `assets/engine-config.js` pins the SHA-384 hash of each Pyodide core file: the loader, the WebAssembly, the standard library and the lock file. The browser refuses any file that doesn't match, and packages are checked against the lock file. A compromised or changed CDN can't run code on these pages; the pill says *Engine unavailable* and why. The suite's own files (`suite/tools/gradekit.py` and the rest) are checked against this site's `manifest.json` in the same way, so a half-finished deploy is caught too.

To avoid the CDN (for an air-gapped network, a host that allows only its own origin, or just to remove the dependency), the easiest way is the **web-with-Pyodide download**: each release has a `code-grading-suite-web-pyodide-vX.Y.Z.zip`, the same site with Pyodide already in `pyodide/`. Deploy it like the plain site; it loads nothing from a CDN.

To do the same to a site you've built or already deployed, run the kit's `tools/vendor_pyodide.py` on it from any machine with internet access, once:

```bash
python3 tools/vendor_pyodide.py path/to/site                       # downloads the pinned Pyodide from the CDN
python3 tools/vendor_pyodide.py path/to/site --from ./pyodide-0.29.3  # or uses files you already have
```

It copies Pyodide's core files and the packages the pages use into `pyodide/`. It refuses any file that doesn't match its pinned hash or Pyodide's lock file. It also writes `pyodide/THIRD-PARTY-NOTICES.md` and `pyodide/licenses/`: the licenses of what it copied (Pyodide's MPL-2.0 with where its source is, CPython's for the standard library, and each package's, taken from its own wheel), which their terms ask anyone redistributing them to include. It downloads Pyodide's and CPython's license texts for the exact versions; offline, give `--licenses-from DIR` with `pyodide-LICENSE` and `cpython-LICENSE`. Then it points `assets/engine-config.js` at the local copy and updates `manifest.json` and `SHA256SUMS`. The pages still check every file as they load it.

To set it up by hand instead:

1. Download the Pyodide release named in `assets/engine-config.js` from the Pyodide GitHub releases page. The "core" archive is enough to run everything. **Review a report** also uses Pyodide's `jsonschema` package (and its dependencies) for the full report-format check; it's in the full archive. Without it, the page still checks every scoring rule and notes that the structural schema check was skipped.
2. Unpack it into a folder on your server, e.g. `/grading/pyodide/`.
3. Edit `assets/engine-config.js` and set `pyodideIndexURL` to that folder, e.g. `"../pyodide/"` or `"/grading/pyodide/"`. Keep the same Pyodide version: the pinned hashes still apply. A different version needs its own `pyodideIntegrity` hashes (`openssl dgst -sha384 -binary FILE | base64` for each file).
4. Keep it on the same server as the site. The pages' content-security policy (below) allows scripts only from the site itself and `cdn.jsdelivr.net`.

Serve `.wasm` files as `application/wasm` (most servers already do).

**First visit after deploying:** open **Set up a project** and check that the pill in the top-right corner says *Engine ready*. If it says *Engine unavailable*, the message on the page explains why: usually the CDN is blocked, or the page was opened as a local file instead of from a server.

## Security notes

- **Content-security policy.** Every page carries a strict policy in a `<meta>` tag, so it works on any host:
  - **scripts:** only from the site and `cdn.jsdelivr.net`, never inline, and nothing may `eval`. Pyodide only needs to compile WebAssembly (`'wasm-unsafe-eval'`);
  - **connections:** only to the site, jsDelivr and GitHub (the Review page reads public grading repos);
  - **forms and plugins:** none.

  The `.htaccess` file sends the same policy as a header, plus `frame-ancestors 'none'` so other sites can't frame the pages. On other hosts, send it as a header if you can (for example, Netlify's `_headers` file or a CloudFront response-headers policy). If you load Pyodide or reports from somewhere else, add that origin to `script-src` and `connect-src` in both places.
- **Check what you deploy.** Each release lists its files' checksums in `SHA256SUMS`, and the zips carry signed build provenance. Check them before you deploy:

  ```bash
  sha256sum -c SHA256SUMS --ignore-missing
  gh attestation verify code-grading-suite-web-vX.Y.Z.zip --repo OWNER/REPO   # the repo you download releases from
  ```

  The built site also has its own `SHA256SUMS` and `manifest.json` for every file.

- **Serve it from a server you control, over HTTPS.** Agents treat this site as their instructions. Anyone who can change these files can change how your code is graded.
- **Keep the site and the grading repo separate.** The site holds only the suite. Project settings, decisions and reports belong in your grading repo.
- **Access control is optional.** The prompts aren't secret. If you put the site behind authentication, agents need credentials to fetch it (e.g. `curl -u` from a shell), and some agents' built-in web tools can't sign in. A private network address the agents can reach is often simpler.
- **Don't block agents with `robots.txt`.** Some agents' web tools respect it and would refuse to fetch the suite. If you don't want search engines indexing the site, use a non-public URL or an `X-Robots-Tag: noindex` header instead.
