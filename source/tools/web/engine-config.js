// Code Grading Suite: where the website loads its Python runtime from.
//
// The "Set up a project" and "Review a report" pages run the suite's own gradekit.py
// inside your browser using Pyodide (Python compiled to WebAssembly). Nothing is
// uploaded anywhere: your files stay in the browser.
//
// By default Pyodide is loaded from the jsDelivr CDN (about 10 MB, cached after the
// first visit). To self-host instead, download the matching Pyodide release from
// https://github.com/pyodide/pyodide/releases, put its files in a folder on your
// server (e.g. /grading/pyodide/), and point pyodideIndexURL at that folder.
window.GK_CONFIG = {
  engine: "pyodide",
  pyodideIndexURL: "https://cdn.jsdelivr.net/pyodide/v0.29.3/full/"
};
