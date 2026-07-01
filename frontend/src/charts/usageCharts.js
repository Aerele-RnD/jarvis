// Pure builders for the LLM Monitor echarts (plain option objects; node:test-able).
const GREEN = "#48bb74", AMBER = "#f6ad55", RED = "#fc8181"

export function budgetGaugeOption(used, limit, dark = false) {
  const lim = Number(limit) || 0
  if (lim <= 0) return null
  const val = Math.max(0, Number(used) || 0)
  const pct = Math.min(100, Math.round((val / lim) * 100))
  const text = dark ? "#cbd5e0" : "#333333"
  const track = dark ? "#2d3748" : "#e2e8f0"
  const color = pct >= 90 ? RED : pct >= 70 ? AMBER : GREEN
  return {
    series: [{
      type: "gauge", startAngle: 210, endAngle: -30, min: 0, max: 100,
      progress: { show: true, width: 14, itemStyle: { color } },
      axisLine: { lineStyle: { width: 14, color: [[1, track]] } },
      axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
      pointer: { show: false }, anchor: { show: false },
      detail: { valueFormatter: (v) => `${v}%`, color: text, fontSize: 22, offsetCenter: [0, "10%"] },
      data: [{ value: pct }],
    }],
  }
}

export function perModelBarSpec(perModel, metric = "tokens") {
  const rows = Array.isArray(perModel) ? perModel : []
  return {
    type: "bar",
    x: rows.map((r) => String(r.model || "")),
    series: [{ name: metric === "cost" ? "Cost ($)" : "Tokens", data: rows.map((r) => Number(r[metric]) || 0) }],
    options: { horizontal: true },
  }
}
