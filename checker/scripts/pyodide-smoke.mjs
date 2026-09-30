// Runs the browser bundle in real Pyodide (Node) on a synthetic brief and prints
// the extracted citations. Proves the zip loads without the C extensions.
import { readFile } from "node:fs/promises"
import { loadPyodide, version } from "pyodide"

const CDN = `https://cdn.jsdelivr.net/pyodide/v${version}/full/`
const t0 = Date.now()
const py = await loadPyodide({ packageBaseUrl: CDN })
await py.loadPackage(["lxml", "regex"])
const zip = await readFile(new URL("../public/py/checker.zip", import.meta.url))
py.unpackArchive(new Uint8Array(zip), "zip", { extractDir: "/home/pyodide/checker" })
py.runPython("import sys; sys.path.insert(0, '/home/pyodide/checker')")
const browser = py.pyimport("browser")
console.log(`loaded in ${((Date.now() - t0) / 1000).toFixed(1)}s`)

const brief = await readFile(new URL("../../corpus/synthetic/docs/brief-001.md", import.meta.url), "utf8")
const t1 = Date.now()
const cites = JSON.parse(browser.extract_json(brief))
console.log(`extracted ${cites.length} citations in ${Date.now() - t1}ms`)
for (const c of cites) console.log(" ", c.text, "|", c.written_name)

const r = JSON.parse(browser.classify_json(0, JSON.stringify({
  found: true, case_name: "Celotex Corp. v. Catrett", court: "scotus", date_filed: "1986-06-25",
})))
console.log("classify:", r.verdict, r.confidence, r.explanation)
const m = JSON.parse(browser.classify_json(4, JSON.stringify({ found: true, case_name: "Minnick v. California Department of Corrections" })))
console.log("classify:", m.verdict, m.explanation)
if (cites.length !== 5 || r.verdict !== "RESOLVED" || m.verdict !== "NAME_MISMATCH") process.exit(1)
