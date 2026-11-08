// Code Grading Suite: where the website loads its Python runtime from.
//
// The "Set up a project" and "Review a report" pages run the suite's own gradekit.py
// inside your browser using Pyodide (Python compiled to WebAssembly). Nothing is
// uploaded anywhere: your files stay in the browser.
//
// By default Pyodide is loaded from the jsDelivr CDN (about 12 MB, cached after the
// first visit). Every file is checked against the hashes below before it runs: the
// browser refuses anything that doesn't match, so a changed or compromised CDN can't
// run code here. Packages Pyodide loads later are checked against its lock file, which
// is itself checked.
//
// To self-host, put the same Pyodide release's files in a folder on your server (e.g.
// /grading/pyodide/; the "with Pyodide" download already has them in pyodide/) and point
// pyodideIndexURL at it; the hashes still apply. Keep it on the same server: the pages'
// content-security policy only allows this site and cdn.jsdelivr.net.
// A different Pyodide version needs its own hashes (sha384 of each file, base64).
window.GK_CONFIG = {
  engine: "pyodide",
  pyodideIndexURL: "https://cdn.jsdelivr.net/pyodide/v0.29.3/full/",
  pyodideVersion: "0.29.3",
  pyodideIntegrity: {
    "pyodide.js": "sha384-Hcsv6LxK5rH9vVB+a/+cLJZR3kIIM2Y851r6waxy+9JInvSROiD1bTMk748pYdat",
    "pyodide.asm.js": "sha384-H/2VLTcLlId+2q+XryOhG/nGawPSusslAGPNvqdOA4U5cHJX+UFEzL0fEM1jEf0b",
    "pyodide.asm.wasm": "sha384-W3dDz77bydlUojTtAGEnjta8TodphdFrtejY4+BmoIXgXs1o+W8t6byLJ71jkOyN",
    "python_stdlib.zip": "sha384-N6oQlVvCCt2KTb4E08U9ctVKPkEv8zlBwyOwgAG1fmS3H5XQA4j0lLbWa+kDvlsU",
    "pyodide-lock.json": "sha384-ouUBrsjlVW6VZ9nFEExCgPrCekncxyncvg//bRCwIEv8VMhM/oaPI5OmmCuQcjCW"
  }
};
