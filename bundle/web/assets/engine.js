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

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src; s.async = true;
      s.onload = resolve;
      s.onerror = function () { reject(new Error("couldn't load " + src)); };
      document.head.appendChild(s);
    });
  }

  async function fetchText(path) {
    var res = await fetch(new URL("suite/" + path, SITE).href, { cache: "no-cache" });
    if (!res.ok) throw new Error("couldn't fetch suite/" + path + " (" + res.status + ")");
    return res.text();
  }

  async function startPyodide() {
    var cfg = window.GK_CONFIG || {};
    var index = cfg.pyodideIndexURL || "https://cdn.jsdelivr.net/pyodide/v0.29.3/full/";
    if (!/\/$/.test(index)) index += "/";
    setStatus("loading", "Loading Python…");
    if (typeof window.loadPyodide !== "function") await loadScript(index + "pyodide.js");
    var py = await window.loadPyodide({ indexURL: index });
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
