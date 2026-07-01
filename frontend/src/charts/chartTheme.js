// Safe high-level chart spec -> themed ECharts option. Mirrors Frappe Insights'
// look (palette, dashed gridlines, no ticks, rounded bars, smooth/gradient).
// PURE: no echarts import (gradients use plain colorStops objects), so it is
// unit-testable under `node --test`. The chat owns the theme; the agent never
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
		axisLine: { lineStyle: { color: grid } }, axisLabel: { color: text, hideOverlap: true },
	}
	const val = {
		type: "value", axisLabel: { color: text },
		splitLine: { lineStyle: { type: "dashed", color: grid } },
	}
	return {
		backgroundColor: "transparent",
		color: PALETTE,
		title,
		grid: { left: 8, right: 16, top: title ? 36 : 20, bottom: 8, containLabel: true },
		tooltip: { trigger: "axis", confine: true },
		legend: series.length > 1
			? { type: "scroll", top: title ? 4 : 0, right: 8, textStyle: { color: text } }
			: undefined,
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
			color: {
				type: "linear", x: 0, y: 0, x2: 0, y2: 1,
				colorStops: [{ offset: 0, color }, { offset: 1, color: "rgba(255,255,255,0)" }],
			},
		}
	}
	return out
}

function pieOption(spec, series, text, title) {
	const labels = Array.isArray(spec.x) ? spec.x.map(String) : []
	const d0 = Array.isArray(series[0] && series[0].data) ? series[0].data : []
	const data = d0.map((v, i) => ({ name: labels[i] != null ? labels[i] : `#${i + 1}`, value: Number(v) || 0 }))
	return {
		backgroundColor: "transparent",
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
