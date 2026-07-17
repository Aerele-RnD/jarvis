import { test } from "node:test"
import assert from "node:assert/strict"
import { buildSrcdoc, parseSourcesBlock, CSP_META, RUNTIME_JS } from "./dashboardSrcdoc.js"

// A stable marker that only appears where the runtime was inlined.
const RUNTIME_MARK = "window.jarvis = {"

test("full document with <head>: injection lands right after the head tag", () => {
  const out = buildSrcdoc("<!DOCTYPE html><html><head><title>t</title></head><body>USER</body></html>", {})
  const head = out.indexOf("<head>")
  assert.ok(head >= 0)
  // CSP is the FIRST head child (immediately after the opening head tag)
  assert.equal(out.indexOf(CSP_META), head + "<head>".length)
  // runtime precedes the user's own head content and all user markup
  assert.ok(out.indexOf(RUNTIME_MARK) < out.indexOf("<title>t</title>"))
  assert.ok(out.indexOf(RUNTIME_MARK) < out.indexOf("USER"))
})

test("<html> but no <head>: a head is inserted after the html tag, CSP first", () => {
  const out = buildSrcdoc('<html lang="en"><body>USER</body></html>', {})
  const htmlTag = /<html[^>]*>/.exec(out)[0]
  const afterHtml = out.indexOf(htmlTag) + htmlTag.length
  assert.equal(out.indexOf("<head>"), afterHtml)
  assert.equal(out.indexOf(CSP_META), afterHtml + "<head>".length)
  assert.ok(out.indexOf("</head>") < out.indexOf("USER"))
  assert.ok(out.indexOf(RUNTIME_MARK) < out.indexOf("USER"))
})

test("fragment: doctype stripped, skeleton wrap, charset present, CSP first", () => {
  const out = buildSrcdoc("<!doctype html>\n<div>USER</div>", {})
  assert.ok(out.startsWith("<!DOCTYPE html><html"))
  // the leading user doctype was stripped (only our own remains)
  assert.equal(out.match(/<!doctype/gi).length, 1)
  const head = out.indexOf("<head>")
  assert.equal(out.indexOf(CSP_META), head + "<head>".length)
  // charset comes right after the CSP (fragment wrap only)
  assert.equal(out.indexOf('<meta charset="utf-8">'), head + "<head>".length + CSP_META.length)
  assert.ok(out.includes("<body><div>USER</div></body>"))
  assert.ok(out.indexOf(RUNTIME_MARK) < out.indexOf("USER"))
})

test("charset is only added on the fragment wrap", () => {
  const full = buildSrcdoc("<html><head></head><body></body></html>", {})
  assert.ok(!full.includes('<meta charset="utf-8">'))
})

test("runtime script precedes user markup in all three cases", () => {
  for (const html of [
    "<html><head></head><body><p>USER</p></body></html>",
    "<html><body><p>USER</p></body></html>",
    "<p>USER</p>",
  ]) {
    const out = buildSrcdoc(html, {})
    assert.ok(out.indexOf(RUNTIME_MARK) < out.indexOf("USER"), `runtime after markup for: ${html}`)
  }
})

test("</script> in inlined sources is escaped so the wrapper cannot terminate early", () => {
  const evil = 'console.log("</script><img src=x>")'
  const out = buildSrcdoc("<div>ok</div>", { echartsSource: evil })
  assert.ok(out.includes('console.log("<\\/script><img src=x>")'))
  // the only raw </script> occurrences are our own wrapper closers (2 scripts)
  assert.equal(out.match(/<\/script>/g).length, 2)
})

test("runtime itself carries no unescaped </script>", () => {
  assert.ok(!/<\/script/i.test(RUNTIME_JS))
})

test("echarts toggle: absent by default, present (before the runtime) when passed", () => {
  const without = buildSrcdoc("<div></div>", {})
  assert.ok(!without.includes("ECHARTS_SRC"))
  const withE = buildSrcdoc("<div></div>", { echartsSource: "/*ECHARTS_SRC*/" })
  assert.ok(withE.includes("/*ECHARTS_SRC*/"))
  assert.ok(withE.indexOf("/*ECHARTS_SRC*/") < withE.indexOf(RUNTIME_MARK))
  assert.ok(withE.indexOf(CSP_META) < withE.indexOf("/*ECHARTS_SRC*/"))
})

test("theme attribute: set in all cases, replaced when already present", () => {
  // fragment
  assert.ok(buildSrcdoc("<p>x</p>", { dark: true }).includes('<html data-theme="dark">'))
  assert.ok(buildSrcdoc("<p>x</p>", { dark: false }).includes('<html data-theme="light">'))
  // full doc without the attr
  const a = buildSrcdoc("<html><head></head><body></body></html>", { dark: true })
  assert.ok(/<html[^>]*data-theme="dark"[^>]*>/.test(a))
  // existing attr replaced, not duplicated
  const b = buildSrcdoc('<html data-theme="light"><head></head><body></body></html>', { dark: true })
  assert.ok(b.includes('data-theme="dark"'))
  assert.ok(!b.includes('data-theme="light"'))
  // html-no-head case too
  const c = buildSrcdoc("<html><body></body></html>", { dark: true })
  assert.ok(/<html[^>]*data-theme="dark"[^>]*>/.test(c))
})

test("parseSourcesBlock: reads the #jarvis-sources block; tolerates absence + bad JSON", () => {
  const html =
    '<div></div><script type="application/json" id="jarvis-sources">' +
    '{"sources":[{"source_name":"overdue","tool":"query","spec":{"q":1}},{"tool":"query"}]}' +
    "</script>"
  const sources = parseSourcesBlock(html)
  assert.equal(sources.length, 1) // the entry without source_name is dropped
  assert.deepEqual(sources[0], { source_name: "overdue", tool: "query", spec: { q: 1 } })
  assert.deepEqual(parseSourcesBlock("<div>none</div>"), [])
  assert.deepEqual(
    parseSourcesBlock('<script type="application/json" id="jarvis-sources">{oops</script>'),
    [],
  )
})

test("parseSourcesBlock: normalizes the LLM tool-call dialect (id / jarvis__ prefix / args.spec)", () => {
  const html =
    '<script type="application/json" id="jarvis-sources">' +
    '{"sources":[' +
    '{"id":"monthly_sales","tool":"jarvis__query","refresh":"view","args":{"spec":{"from":"Sales Invoice"}}},' +
    '{"name":"top5","tool":"jarvis__run_report","args":{"report_name":"Foo","filters":{"a":1}}}' +
    "]}</script>"
  const sources = parseSourcesBlock(html)
  assert.equal(sources.length, 2)
  assert.deepEqual(sources[0], {
    source_name: "monthly_sales",
    tool: "query",
    spec: { from: "Sales Invoice" },
  })
  assert.deepEqual(sources[1], {
    source_name: "top5",
    tool: "run_report",
    spec: { report_name: "Foo", filters: { a: 1 } },
  })
})

test("RUNTIME_JS: contains the same dialect normalization", () => {
  assert.ok(RUNTIME_JS.includes("jarvis__"))
  assert.ok(RUNTIME_JS.includes("s.args"))
})

test("buildSrcdoc: named theme injects vars + JARVIS_THEME and owns data-theme", async () => {
  const { THEMES } = await import("./dashboardThemes.js")
  const out = buildSrcdoc("<html><head></head><body><p>x</p></body></html>", {
    theme: THEMES.jarvis,
  })
  assert.ok(out.includes('<style id="jarvis-theme">'))
  assert.ok(out.includes("--jd-bg:"))
  assert.ok(out.includes("window.JARVIS_THEME="))
  assert.ok(out.includes('"name":"jarvis"'))
  assert.ok(/<html[^>]*data-theme="light"/.test(out))
  // theme style must precede the runtime so vars exist before user scripts
  assert.ok(out.indexOf('id="jarvis-theme"') < out.indexOf("window.jarvis ="))
  // a dark theme drives data-theme
  const dark = buildSrcdoc("<p>x</p>", { theme: THEMES.graphite })
  assert.ok(dark.includes('data-theme="dark"'))
  // no theme → legacy dark flag behavior unchanged
  const legacy = buildSrcdoc("<p>x</p>", { dark: true })
  assert.ok(legacy.includes('data-theme="dark"'))
  assert.ok(!legacy.includes("jarvis-theme"))
})
