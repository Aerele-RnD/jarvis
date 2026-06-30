import { test } from "node:test"
import assert from "node:assert/strict"
import { buildOption } from "./chartTheme.js"

test("rejects malformed / unknown specs -> null", () => {
	assert.equal(buildOption(null), null)
	assert.equal(buildOption({}), null)
	assert.equal(buildOption({ type: "pie3d" }), null)
	assert.equal(buildOption("nope"), null)
	assert.equal(buildOption({ type: "bar", series: [] }), null)
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
	assert.equal(o.series[0].areaStyle.color.type, "linear")
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
	assert.ok(Array.isArray(donut.series[0].radius))
})

test("legend only when >1 series; dark text differs from light", () => {
	const one = buildOption({ type: "bar", x: ["A"], series: [{ data: [1] }] })
	assert.equal(one.legend, undefined)
	const dark = buildOption({ type: "bar", x: ["A"], series: [{ data: [1] }], title: "t" }, true)
	const light = buildOption({ type: "bar", x: ["A"], series: [{ data: [1] }], title: "t" }, false)
	assert.notEqual(dark.xAxis.axisLabel.color, light.xAxis.axisLabel.color)
})
