# Inline Chat Charts (ECharts) - Implementation Plan

> Execute task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Render attractive, readable charts inline in the chat response - the agent emits a ` ```jarvis-chart ` block with a safe high-level spec; the chat draws it with Apache ECharts (the same engine + look as Frappe Insights), themed by the chat (never raw ECharts options from the model).

**Architecture:** Mirror the existing ` ```jarvis-cards ` pattern in the chat SPA (`apps/jarvis/frontend`). A pure `chartTheme.js` maps the spec to a themed ECharts option (Insights-grade); a `JvChart.vue` component owns the echarts lifecycle; `ChatView.vue` parses ` ```jarvis-chart ` blocks (like `cardsOf`), strips them from the prose, and renders one `<JvChart>` per spec. The persona learns to emit the block after it has the data.

**Tech stack:** Vue 3 + Vite, `echarts ^5.5.0` (same as Insights 3.3.1). No frontend test runner exists, so the pure builder is tested with Node's built-in `node:test`; the Vue glue is verified by `vite build` + a sample render.

## Global Constraints

- **Inline only.** Charts render as part of the assistant chat message - no separate page, no Desk dependency. The block lives in the message text, so it persists + re-renders on reload (like ` ```mermaid `).
- **Same engine + look as Insights:** `echarts ^5.5.0`; SVG renderer; curated palette; dashed gridlines; no axis ticks; rounded bars; smooth/gradient lines.
- **Safe spec, theme owned by the chat.** The agent sends a high-level spec (type / x / series / a few options) - NEVER raw ECharts option JSON (no formatters/functions/HTML over the wire). `buildOption` validates and returns `null` on anything malformed; the UI shows a small "couldn't render" note, never throws.
- **Lazy-load echarts** (dynamic `import('echarts')` inside the component) so it never bloats first paint - mirror the mermaid lazy-load already in `ChatView.vue` (~line 1700).
- **Dark-mode aware** - the chat already exposes `effectiveDark`; the theme switches on it.
- **Two repos:** `apps/jarvis/frontend` (render) + `jarvis-persona` (agent emits the block). Frontend node: use the repo's node20 (`export PATH="$HOME/.nvm/versions/node/v20.19.6/bin:$PATH"`). Run frontend cmds from `apps/jarvis/frontend`.

## Spec contract (the persona <-> frontend interface)

```jsonc
{
  "type": "bar" | "line" | "area" | "pie" | "donut",   // required
  "title": "string",                                    // optional
  "x": ["Jan", "Feb", "Mar"],                           // category labels (also pie slice labels)
  "series": [ { "name": "Revenue", "data": [12, 18, 15] } ],  // data aligned to x; pie uses series[0]
  "options": { "stacked": false, "smooth": false, "horizontal": false }  // optional
}
```

---

### Task 1: `chartTheme.js` - safe spec -> themed ECharts option (pure, TDD)

**Files:**
- Create: `apps/jarvis/frontend/src/charts/chartTheme.js`
- Test: `apps/jarvis/frontend/src/charts/chartTheme.test.js`
- Modify: `apps/jarvis/frontend/package.json` (add `echarts`)

**Interfaces:**
- Produces: `buildOption(spec, dark = false) -> echartsOption | null`. `null` for any non-object / unknown `type` / structurally invalid spec.

- [ ] **Step 1: Add the dep**

Edit `package.json` dependencies: add `"echarts": "^5.5.0"`, then `npm install` (node20 PATH).

- [ ] **Step 2: Write the failing test**

```js
// apps/jarvis/frontend/src/charts/chartTheme.test.js
import { test } from "node:test"
import assert from "node:assert/strict"
import { buildOption } from "./chartTheme.js"

test("rejects malformed / unknown specs -> null", () => {
  assert.equal(buildOption(null), null)
  assert.equal(buildOption({}), null)
  assert.equal(buildOption({ type: "pie3d" }), null)
  assert.equal(buildOption("nope"), null)
})

test("bar: category x, rounded bars, palette, dashed value split", () => {
  const o = buildOption({ type: "bar", x: ["A", "B"], series: [{ name: "R", data: [1, 2] }] })
  assert.equal(o.xAxis.type, "category")
  assert.deepEqual(o.xAxis.data, ["A", "B"])
  assert.equal(o.xAxis.axisTick.show, false)
  assert.equal(o.yAxis.splitLine.lineStyle.type, "dashed")
  assert.equal(o.series[0].type, "bar")
  assert.ok(Array.isArray(o.series[0].itemStyle.borderRadius))
  assert.ok(Array.isArray(o.color) && o.color.length > 0)
})

test("horizontal bar swaps axes", () => {
  const o = buildOption({ type: "bar", x: ["A"], series: [{ data: [1] }], options: { horizontal: true } })
  assert.equal(o.yAxis.type, "category")
  assert.equal(o.xAxis.type, "value")
})

test("line + smooth + area gradient", () => {
  const o = buildOption({ type: "area", x: ["A", "B"], series: [{ name: "R", data: [1, 2] }], options: { smooth: true } })
  assert.equal(o.series[0].type, "line")
  assert.equal(o.series[0].smooth, 0.4)
  assert.equal(o.series[0].areaStyle.color.type, "linear")  // plain-object gradient, no echarts import
})

test("stacked sets a shared stack key on every series", () => {
  const o = buildOption({ type: "bar", x: ["A"], series: [{ data: [1] }, { data: [2] }], options: { stacked: true } })
  assert.equal(o.series[0].stack, o.series[1].stack)
  assert.ok(o.series[0].stack)
})

test("pie maps x+series[0] to {name,value}; donut has inner radius", () => {
  const pie = buildOption({ type: "pie", x: ["A", "B"], series: [{ data: [3, 7] }] })
  assert.equal(pie.series[0].type, "pie")
  assert.deepEqual(pie.series[0].data, [{ name: "A", value: 3 }, { name: "B", value: 7 }])
  const donut = buildOption({ type: "donut", x: ["A"], series: [{ data: [1] }] })
  assert.ok(Array.isArray(donut.series[0].radius))  // [inner, outer]
})

test("legend only when >1 series; dark text differs from light", () => {
  const one = buildOption({ type: "bar", x: ["A"], series: [{ data: [1] }] })
  assert.equal(one.legend, undefined)
  const dark = buildOption({ type: "bar", x: ["A"], series: [{ data: [1] }], title: "t" }, true)
  const light = buildOption({ type: "bar", x: ["A"], series: [{ data: [1] }], title: "t" }, false)
  assert.notEqual(dark.xAxis.axisLabel.color, light.xAxis.axisLabel.color)
})
```

- [ ] **Step 3: Run it; expect FAIL** (module missing)

Run (node20 PATH, from `apps/jarvis/frontend`): `node --test src/charts/chartTheme.test.js`
Expected: FAIL (cannot find `./chartTheme.js`).

- [ ] **Step 4: Implement `chartTheme.js`**

```js
// apps/jarvis/frontend/src/charts/chartTheme.js
// Safe high-level chart spec -> themed ECharts option. Mirrors Frappe Insights'
// look (palette, dashed gridlines, no ticks, rounded bars, smooth/gradient).
// PURE: no echarts import (gradients use plain colorStops objects), so it is
// unit-testable under node --test. The chat owns the theme; the agent never
// sends raw ECharts options.

const PALETTE = [
  "#2490ef", "#48bb74", "#f6ad55", "#fc8181", "#9f7aea",
  "#38b2ac", "#ed64a6", "#ecc94b", "#667eea", "#a0aec0",
]
const TYPES = new Set(["bar", "line", "area", "pie", "donut"])

export function buildOption(spec, dark = false) {
  if (!spec || typeof spec !== "object" || !TYPES.has(spec.type)) return null
  const series = Array.isArray(spec.series) ? spec.series : []
  if (!series.length) return null
  const text = dark ? "#cbd5e0" : "#333333"
  const grid = dark ? "#2d3748" : "#e2e8f0"
  const title = spec.title
    ? { text: String(spec.title), left: 8, top: 4, textStyle: { fontSize: 13, color: text } }
    : undefined
  if (spec.type === "pie" || spec.type === "donut") return pieOption(spec, series, text, title)
  return axisOption(spec, series, { text, grid, title })
}

function axisOption(spec, series, { text, grid, title }) {
  const x = Array.isArray(spec.x) ? spec.x.map(String) : []
  const opts = spec.options || {}
  const cat = {
    type: "category", data: x, axisTick: { show: false },
    axisLine: { lineStyle: { color: grid } }, axisLabel: { color: text },
  }
  const val = {
    type: "value", axisLabel: { color: text },
    splitLine: { lineStyle: { type: "dashed", color: grid } },
  }
  return {
    color: PALETTE,
    title,
    grid: { left: 8, right: 16, top: title ? 36 : 20, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis", confine: true },
    legend: series.length > 1 ? { type: "scroll", top: title ? 4 : 0, right: 8, textStyle: { color: text } } : undefined,
    xAxis: opts.horizontal ? val : cat,
    yAxis: opts.horizontal ? cat : val,
    series: series.map((s, i) => makeSeries(spec, s, i)),
  }
}

function makeSeries(spec, s, i) {
  const data = Array.isArray(s.data) ? s.data : []
  const color = PALETTE[i % PALETTE.length]
  const opts = spec.options || {}
  const stack = opts.stacked ? "total" : undefined
  if (spec.type === "bar") {
    const r = opts.horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]
    return { name: s.name, type: "bar", data, stack, itemStyle: { borderRadius: r } }
  }
  const out = {
    name: s.name, type: "line", data, stack,
    smooth: opts.smooth ? 0.4 : false, smoothMonotone: "x",
    showSymbol: false, lineStyle: { width: 2 }, itemStyle: { color },
  }
  if (spec.type === "area") {
    out.areaStyle = {
      opacity: 0.85,
      color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [{ offset: 0, color }, { offset: 1, color: "rgba(255,255,255,0)" }] },
    }
  }
  return out
}

function pieOption(spec, series, text, title) {
  const labels = Array.isArray(spec.x) ? spec.x.map(String) : []
  const d0 = Array.isArray(series[0] && series[0].data) ? series[0].data : []
  const data = d0.map((v, i) => ({ name: labels[i] != null ? labels[i] : `#${i + 1}`, value: Number(v) || 0 }))
  return {
    color: PALETTE,
    title,
    tooltip: { trigger: "item", confine: true },
    legend: { type: "scroll", bottom: 0, textStyle: { color: text } },
    series: [{
      type: "pie",
      radius: spec.type === "donut" ? ["45%", "70%"] : "65%",
      center: ["50%", title ? "54%" : "48%"],
      data,
      label: { color: text },
      itemStyle: { borderRadius: 4, borderColor: text === "#333333" ? "#fff" : "#1a202c", borderWidth: 1 },
    }],
  }
}
```

- [ ] **Step 5: Run it; expect PASS**

Run: `node --test src/charts/chartTheme.test.js` -> all tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/jarvis/frontend/package.json apps/jarvis/frontend/package-lock.json apps/jarvis/frontend/src/charts/
git commit -m "feat(chat): echarts + safe chart-spec -> Insights-grade option builder"
```

---

### Task 2: `JvChart.vue` - the echarts lifecycle component

**Files:**
- Create: `apps/jarvis/frontend/src/charts/JvChart.vue`

**Interfaces:**
- Consumes: `buildOption` (Task 1).
- Produces: `<JvChart :spec="Object" :dark="Boolean" />`. Lazy-imports echarts, inits an SVG chart, re-renders on spec/dark change, resizes with the container, disposes on unmount. Renders a small muted note when `buildOption` returns `null`.

- [ ] **Step 1: Implement**

```vue
<!-- apps/jarvis/frontend/src/charts/JvChart.vue -->
<template>
  <div v-if="invalid" class="jv-chart-bad">Couldn't render this chart.</div>
  <div v-else ref="el" class="jv-chart"></div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount, computed, nextTick } from "vue"
import { buildOption } from "./chartTheme.js"

const props = defineProps({ spec: { type: Object, required: true }, dark: { type: Boolean, default: false } })
const el = ref(null)
let chart = null
let ro = null

const option = computed(() => buildOption(props.spec, props.dark))
const invalid = computed(() => option.value === null)

async function ensure() {
  if (invalid.value || !el.value) return
  if (!chart) {
    const echarts = await import("echarts")          // lazy: off the first-paint path
    if (!el.value) return
    chart = echarts.init(el.value, null, { renderer: "svg" })
    ro = new ResizeObserver(() => chart && chart.resize())
    ro.observe(el.value)
  }
  chart.setOption(option.value, true)
}

onMounted(() => nextTick(ensure))
watch(option, ensure)
onBeforeUnmount(() => {
  if (ro && el.value) ro.unobserve(el.value)
  if (chart) { chart.dispose(); chart = null }
})
</script>

<style scoped>
.jv-chart { width: 100%; height: 280px; }
.jv-chart-bad { font-size: 13px; color: var(--text-3); padding: 8px 0; }
</style>
```

- [ ] **Step 2: Verify it compiles**

Run: `npm run build` (node20 PATH) -> build succeeds, `echarts` chunk emitted. (No component unit test - no harness; visual check happens in Task 4.)

- [ ] **Step 3: Commit**

```bash
git add apps/jarvis/frontend/src/charts/JvChart.vue
git commit -m "feat(chat): JvChart.vue - lazy echarts SVG component with resize/dispose"
```

---

### Task 3: Wire ` ```jarvis-chart ` into `ChatView.vue`

**Files:**
- Modify: `apps/jarvis/frontend/src/views/ChatView.vue`

**Interfaces:**
- Consumes: `JvChart` (Task 2).
- Mirrors the existing `cardsOf(m)` parse + the `stripBlocks` strip + the `jv-cards` template slot.

- [ ] **Step 1: Parser + strip (script section, next to `cardsOf`)**

Add the regex (near `_CARDS_RE`):
```js
// A ```jarvis-chart block: a high-level chart spec the chat renders inline with
// ECharts (themed by chartTheme; the agent never sends raw ECharts options).
const _CHART_RE = /```jarvis-chart[ \t]*\n([\s\S]*?)```/g
const _CHART_TYPES = new Set(["bar", "line", "area", "pie", "donut"])
```
Add `jarvis-chart` to `stripBlocks` (so it leaves the prose + the copy text):
```js
		.replace(/```jarvis-chart[ \t]*\n[\s\S]*?```/g, "")
```
Add `chartsOf(m)` (mirror `cardsOf`, but returns an array; cached):
```js
const _chartsCache = new Map()
function chartsOf(m) {
	const content = (m && m.content) || ""
	if (!content.includes("jarvis-chart")) return []
	if (_chartsCache.has(content)) return _chartsCache.get(content)
	const specs = []
	for (const mt of content.matchAll(_CHART_RE)) {
		try {
			const s = JSON.parse(mt[1].trim())
			if (s && typeof s === "object" && _CHART_TYPES.has(s.type) && Array.isArray(s.series)) {
				specs.push(s)
			}
		} catch (e) { /* incomplete mid-stream JSON -> skip until the block closes */ }
	}
	_chartsCache.set(content, specs)
	return specs
}
```

- [ ] **Step 2: Import + register `JvChart`**

In the `<script setup>` imports (near `import { renderMarkdown } from "@/markdown"`):
```js
import JvChart from "@/charts/JvChart.vue"
```

- [ ] **Step 3: Template - render one chart per spec (next to the `jv-cards` block, ~line 312)**

```html
								<div v-for="(spec, ci) in chartsOf(m)" :key="'chart' + ci" class="jv-chartwrap">
									<JvChart :spec="spec" :dark="effectiveDark" />
								</div>
```

- [ ] **Step 4: CSS (in the component's `<style>`)**

```css
.jv-chartwrap { margin: 10px 0; border: 1px solid var(--border); border-radius: 10px; padding: 8px 10px; background: var(--surface); }
```
(Match the existing `--border` / `--surface` vars used by `jv-cards`.)

- [ ] **Step 5: Build**

Run: `npm run build` -> succeeds.

- [ ] **Step 6: Commit**

```bash
git add apps/jarvis/frontend/src/views/ChatView.vue
git commit -m "feat(chat): render inline jarvis-chart blocks with JvChart"
```

---

### Task 4: End-to-end visual verification (manual - no harness)

- [ ] **Step 1:** `npm run dev` (node20 PATH), open the chat.
- [ ] **Step 2:** In a conversation, have the assistant produce (or paste a test assistant message containing) each block and confirm it renders inline, themed, resizes, and toggles with dark mode:
  - bar: `{"type":"bar","title":"Sales","x":["Jan","Feb","Mar"],"series":[{"name":"Revenue","data":[12,18,15]}]}`
  - multi-series stacked + line smooth + pie + donut + horizontal bar (one each).
  - a malformed block -> shows the muted "Couldn't render this chart." note, no console throw.
- [ ] **Step 3:** Reload the conversation -> charts re-render from the persisted message (block lives in `content`).
- [ ] **Step 4:** Capture a screenshot for the PR. No commit (verification only).

---

### Task 5 (persona repo): teach the agent to emit ` ```jarvis-chart `

**Files:**
- Modify: `jarvis-persona/TOOLS.md` (or a small `skills/frappe-core` analytics note) - document the block + spec contract.
- Modify: `jarvis-persona/version.txt` (bump).

**Interfaces:** the spec contract above; must match `chartsOf`/`buildOption` exactly (`type` in {bar,line,area,pie,donut}; `x`; `series:[{name,data}]`; `options`).

- [ ] **Step 1:** Add a short "Inline charts" section: after gathering data (via `query`/`get_list`/`run_report`), for "chart/plot/visualize/trend X" requests, emit one ` ```jarvis-chart ` block with the spec (one worked example per type). State: prefer this over a ` ```mermaid ` chart for data; keep series small; the chat themes it.
- [ ] **Step 2:** Bump `version.txt`.
- [ ] **Step 3:** Run `./lint.sh` from `jarvis-persona` (ASCII/em-dash/validate.py) -> green. (`jarvis-chart` is not a tool, so validate.py's tool checks don't apply; the text-hygiene checks do.)
- [ ] **Step 4: Commit**
```bash
git add TOOLS.md version.txt
git commit -m "docs(persona): emit jarvis-chart blocks for inline data charts"
```

---

## Self-review

- **Coverage:** spec contract -> Task 1 (`buildOption`) + Task 5 (agent emits it) + Task 3 (`chartsOf` validates the same shape). Render lifecycle -> Task 2. Inline-in-chat + persistence -> Task 3 (parse from `content`, strip from prose) + Task 4 step 3. Insights look -> Task 1 theme. Safety -> Task 1 (`null` on bad spec, no raw options) + Task 3 (skip unparseable). Dark mode -> Tasks 1-3 (`effectiveDark`). Lazy bundle -> Task 2.
- **No raw ECharts option crosses the wire** - the agent's `options` is a fixed allow-list of booleans (`stacked`/`smooth`/`horizontal`); everything else is built chat-side.
- **Streaming-safe:** `chartsOf` skips a block whose JSON doesn't parse yet, so a half-streamed spec simply doesn't render until the closing fence arrives (same as `cardsOf`).
- **Deferred (not v1):** scatter/heatmap/combo types; data-label toggles; per-series colors from the agent; exporting a chart as an image. Add once the v1 shape is in use.
```
