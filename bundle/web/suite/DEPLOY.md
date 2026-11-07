# Hosting the suite on a web server

The web version is a folder of static files. There's no server code, database or build step on the server itself. Copy it to any web server and point coding agents at its `AGENT.md`.

## 1. Build the site

The ready-built site comes in `code-grading-suite-web.zip`. If you've edited the kit (rubric wording, weights, prompts), rebuild it:

```bash
python3 tools/build_web.py --out ../web
```

This regenerates everything from the kit, including checksums. Rendered HTML pages need the Python `markdown` package (`pip install markdown`). Without it, the builder still works but shows docs as plain preformatted text. Agents read the raw `.md` files either way.

## 2. Upload it

Copy the *contents* of the built folder to a directory on your server, for example `/var/www/grading/` so it is served at `https://your-server/grading/`. Any path works because every link in the site is relative.

**Recommended: one directory per version.** Deploy to `/grading/v3.1.0/` and point agents at that exact URL. An improvement loop that runs for weeks then can't have its rubric change underneath it. To also offer a "latest" URL, copy (or symlink) the newest version to `/grading/latest/`.

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
    location ~* \.(py|sql|txt)$ { types { } default_type text/plain; }
}
```

**Caddy:**
```
your-server.example.com {
    root * /var/www
    file_server
    @md path *.md
    header @md Content-Type "text/markdown; charset=utf-8"
    @txt path *.py *.sql *.txt
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
BASE=https://your-server/grading/v3.1.0
curl -sI "$BASE/AGENT.md" | grep -i content-type     # expect text/markdown; charset=utf-8
curl -s  "$BASE/SHA256SUMS" -o SHA256SUMS
curl -s  "$BASE/downloads/code-grading-suite-3.1.0.zip" -o code-grading-suite-3.1.0.zip
sha256sum -c SHA256SUMS --ignore-missing              # expect: OK
```

## 5. Point an agent at it

Open the site's landing page. It shows ready-to-copy instructions for the grader, improver and pull-request roles, with your server's URL already filled in. For example:

> Grade the code in this repository using the Code Grading Suite at https://your-server/grading/v3.1.0/AGENT.md. Act as the **grader**. …

## Security notes

- **Serve it from a server you control, over HTTPS.** Agents treat this site as their instructions. Anyone who can change these files can change how your code is graded.
- **Never host private material here:** hidden checks, dispositions, decisions or grading reports. The site is the *public* part of the suite. Hidden checks in particular only work while improving agents can't see them.
- **Access control is optional.** The prompts aren't secret. If you put the site behind authentication, agents need credentials to fetch it (e.g. `curl -u` from a shell), and some agents' built-in web tools can't sign in. A private network address the agents can reach is often simpler.
- **Don't block agents with `robots.txt`.** Some agents' web tools respect it and would refuse to fetch the suite. If you don't want search engines indexing the site, use a non-public URL or an `X-Robots-Tag: noindex` header instead.
