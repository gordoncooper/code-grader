// Code Grading Suite: runs tools/gradekit.py in the browser and exposes GK.call().
(function () {
  "use strict";
  var script = document.currentScript && document.currentScript.src;
  var SITE = script ? new URL("../", script).href : new URL("./", location.href).href;
  var SUITE_FILES = ["tools/gradekit.py", "config/defaults.toml", "rubric/catalog.json", "schema/report.schema.json"];
  // Optional Pyodide packages, loaded the first time a call needs them (from the same place as Pyodide itself).
  // If one can't be loaded, gradekit falls back and says what it skipped.
  var CALL_PACKAGES = { check: ["jsonschema"] };
  var listeners = [];
  var state = { status: "idle", message: "" };
  var readyPromise = null;
  var impl = null;

  function setStatus(status, message) {
    state = { status: status, message: message };
    listeners.forEach(function (fn) { try { fn(state); } catch (e) { /* ignore */ } });
  }

  function loadScript(src, integrity) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src; s.async = true;
      if (integrity) { s.integrity = integrity; s.crossOrigin = "anonymous"; }
      s.onload = resolve;
      s.onerror = function () { reject(new Error("couldn't load " + src)); };
      document.head.appendChild(s);
    });
  }

  function hexToBase64(hex) {
    var bin = "";
    for (var i = 0; i < hex.length; i += 2) bin += String.fromCharCode(parseInt(hex.substr(i, 2), 16));
    return btoa(bin);
  }

  // The suite's own files are checked against this site's manifest.json, so a half-finished deploy or a
  // changed file is caught instead of run.
  var manifest = null;
  async function suiteHashes() {
    if (manifest) return manifest;
    manifest = {};
    try {
      var res = await fetch(new URL("manifest.json", SITE).href, { cache: "no-cache" });
      if (res.ok) (await res.json()).files.forEach(function (f) { manifest[f.path] = "sha256-" + hexToBase64(f.sha256); });
    } catch (e) { /* no manifest: files are still served from this site */ }
    return manifest;
  }
  async function fetchText(path) {
    var hashes = await suiteHashes(), opts = { cache: "no-cache" };
    if (hashes["suite/" + path]) opts.integrity = hashes["suite/" + path];
    var res;
    try { res = await fetch(new URL("suite/" + path, SITE).href, opts); }
    catch (e) { throw new Error("suite/" + path + " doesn't match this site's manifest.json (redeploy the whole site)"); }
    if (!res.ok) throw new Error("couldn't fetch suite/" + path + " (" + res.status + ")");
    return res.text();
  }

  // Pyodide's own loader fetches its files with plain fetch(); while it loads (and for packages
  // later), known files get the pinned hash added, so the browser verifies them.
  function verifyPyodideFetches(index, hashes) {
    var orig = window.fetch;
    window.fetch = function (input, init) {
      var url = typeof input === "string" ? input : (input && input.url) || String(input);
      var h = url.indexOf(index) === 0 ? hashes[url.slice(index.length).split("?")[0]] : null;
      if (h && !(init && init.integrity)) init = Object.assign({}, init || {}, { integrity: h });
      return orig.call(this, input, init);
    };
  }

  async function startPyodide() {
    var cfg = window.GK_CONFIG || {};
    var index = cfg.pyodideIndexURL || "https://cdn.jsdelivr.net/pyodide/v0.29.3/full/";
    if (!/\/$/.test(index)) index += "/";
    setStatus("loading", "Loading Python…");
    var pins = cfg.pyodideIntegrity;
    var options = { indexURL: index };
    if (pins) {
      // Pyodide's lock file (checked) gives the hash of every package; add those to the pins.
      var lockRes = await fetch(index + "pyodide-lock.json", { integrity: pins["pyodide-lock.json"] }).catch(function () {
        throw new Error("Pyodide's files at " + index + " don't match the pinned hashes in engine-config.js");
      });
      var lock = await lockRes.json(), hashes = Object.assign({}, pins);
      Object.keys(lock.packages || {}).forEach(function (n) {
        var pkg = lock.packages[n];
        if (pkg.file_name && pkg.sha256 && !/^[a-z]+:/.test(pkg.file_name)) hashes[pkg.file_name] = "sha256-" + hexToBase64(pkg.sha256);
      });
      verifyPyodideFetches(index, hashes);
      options.lockFileContents = lock;
      options.packageBaseUrl = index;
      try {
        if (typeof window.loadPyodide !== "function") await loadScript(index + "pyodide.js", pins["pyodide.js"]);
        // Loaded here, checked, so Pyodide doesn't load it again unchecked.
        if (typeof window._createPyodideModule !== "function") await loadScript(index + "pyodide.asm.js", pins["pyodide.asm.js"]);
      } catch (e) {
        throw new Error("Pyodide's files at " + index + " don't match the pinned hashes in engine-config.js");
      }
    } else if (typeof window.loadPyodide !== "function") {
      await loadScript(index + "pyodide.js");
    }
    var py = await window.loadPyodide(options);
    setStatus("loading", "Loading gradekit…");
    var texts = await Promise.all(SUITE_FILES.map(fetchText));
    SUITE_FILES.forEach(function (path, i) {
      var full = "/suite/" + path;
      py.FS.mkdirTree(full.substring(0, full.lastIndexOf("/")));
      py.FS.writeFile(full, texts[i]);
    });
    py.FS.mkdirTree("/work");
    py.runPython("import sys, json\nsys.path.insert(0, '/suite/tools')\nimport gradekit");
    var n = 0, tried = {};
    return {
      call: async function (name, payload) {
        var pkgs = (CALL_PACKAGES[name] || []).filter(function (p) { return !tried[p]; });
        if (pkgs.length) {
          pkgs.forEach(function (p) { tried[p] = true; });
          try { await py.loadPackage(pkgs, { messageCallback: function () {} }); } catch (e) { /* optional: gradekit reports the skipped check */ }
        }
        py.globals.set("_gk_name", name);
        py.globals.set("_gk_payload", JSON.stringify(payload || {}));
        var out = py.runPython("json.dumps(gradekit.web_api(_gk_name, json.loads(_gk_payload)))");
        return JSON.parse(out);
      },
      putFile: async function (bytes, ext) {
        var path = "/work/upload-" + (++n) + (ext || "");
        py.FS.writeFile(path, bytes);
        return path;
      }
    };
  }

  async function startHttp() {
    // Test harness only: the same gradekit.py, run by a local CPython server.
    setStatus("loading", "Connecting to the test engine…");
    var base = new URL("__engine/", SITE).href;
    return {
      call: async function (name, payload) {
        var res = await fetch(base + encodeURIComponent(name), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}) });
        return res.json();
      },
      putFile: async function (bytes, ext) {
        var res = await fetch(base + "__file?ext=" + encodeURIComponent(ext || ""), { method: "POST", body: bytes });
        return (await res.json()).path;
      }
    };
  }

  function load() {
    if (readyPromise) return readyPromise;
    if (location.protocol === "file:") {
      setStatus("failed", "Open this page from a web server, not as a file.");
      readyPromise = Promise.reject(new Error("file:// pages can't load the engine"));
      readyPromise.catch(function () {});
      return readyPromise;
    }
    var cfg = window.GK_CONFIG || {};
    readyPromise = (cfg.engine === "http" ? startHttp() : startPyodide()).then(function (i) {
      impl = i;
      setStatus("ready", "Ready");
      return i;
    }, function (err) {
      setStatus("failed", "Couldn't start the engine: " + (err && err.message ? err.message : err));
      readyPromise = null;
      throw err;
    });
    return readyPromise;
  }

  window.GK = {
    site: SITE,
    load: load,
    onStatus: function (fn) { listeners.push(fn); fn(state); },
    call: async function (name, payload) {
      var i = await load();
      var res = await i.call(name, payload);
      if (!res || res.ok === false) {
        var e = new Error((res && res.error) || "unknown error");
        e.gk = true;
        throw e;
      }
      return res;
    },
    putFile: async function (bytes, ext) { var i = await load(); return i.putFile(bytes, ext); }
  };
})();
