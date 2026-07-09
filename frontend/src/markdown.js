// Compact GFM renderer - enough for agent replies: paragraphs, bold/italic,
// inline code, links, bullet/number lists, and pipe tables (rendered into the
// imported design's table look via the .jv-md classes in ChatView's styles).
function esc(s) {
	return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]))
}

function inline(s) {
	let t = esc(s)
	t = t.replace(/`([^`]+)`/g, '<code class="jv-md-code">$1</code>')
	t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
	t = t.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>")
	t = t.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener" class="jv-md-link">$1</a>')
	return t
}

function renderTable(rows) {
	const cells = (r) => r.replace(/^\||\|$/g, "").split("|").map((c) => c.trim())
	const head = cells(rows[0])
	const aligns = cells(rows[1]).map((s) => (/^:-+:$/.test(s) ? "center" : /-+:$/.test(s) ? "right" : "left"))
	const body = rows.slice(2).map(cells)
	let h = '<div class="jv-md-tablewrap"><table class="jv-md-table"><thead><tr>'
	head.forEach((c, i) => (h += `<th style="text-align:${aligns[i] || "left"}">${inline(c)}</th>`))
	h += "</tr></thead><tbody>"
	body.forEach((r) => {
		h += "<tr>"
		r.forEach((c, i) => (h += `<td style="text-align:${aligns[i] || "left"}">${inline(c)}</td>`))
		h += "</tr>"
	})
	return h + "</tbody></table></div>"
}

export function renderMarkdown(src) {
	if (!src) return ""
	const lines = String(src).replace(/\r\n/g, "\n").split("\n")
	const out = []
	let i = 0
	let para = []
	let list = null
	const flushPara = () => {
		if (para.length) {
			out.push(`<p class="jv-md-p">${inline(para.join(" "))}</p>`)
			para = []
		}
	}
	const flushList = () => {
		if (list) {
			out.push(`<${list.tag} class="jv-md-list">${list.items.map((x) => `<li>${inline(x)}</li>`).join("")}</${list.tag}>`)
			list = null
		}
	}
	while (i < lines.length) {
		const line = lines[i]
		// fenced code block: ``` or ```lang - mermaid renders as a diagram,
		// everything else as a styled code block.
		const fence = line.match(/^\s*```\s*([\w-]*)\s*$/)
		if (fence) {
			flushPara()
			flushList()
			const lang = (fence[1] || "").toLowerCase()
			const body = []
			i++
			while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) body.push(lines[i++])
			i++ // consume closing fence
			const code = body.join("\n")
			if (lang === "mermaid") {
				out.push(`<div class="jv-mermaid">${esc(code)}</div>`)
			} else {
				out.push(`<pre class="jv-md-pre"><code>${esc(code)}</code></pre>`)
			}
			continue
		}
		// table: a header row followed by a |---| separator
		if (/\|/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:-]+\|[\s:|-]*$/.test(lines[i + 1])) {
			flushPara()
			flushList()
			const tbl = [line, lines[i + 1]]
			i += 2
			while (i < lines.length && /\|/.test(lines[i]) && lines[i].trim()) tbl.push(lines[i++])
			out.push(renderTable(tbl))
			continue
		}
		// ATX headings (#-####): wiki page bodies lead with them, and a
		// knowledge base that shows raw hashes reads as broken.
		const heading = line.match(/^\s*(#{1,4})\s+(.*)/)
		if (heading) {
			flushPara()
			flushList()
			const level = Math.min(heading[1].length + 2, 6)
			out.push(`<h${level} class="jv-md-h">${inline(heading[2])}</h${level}>`)
			i++
			continue
		}
		const ul = line.match(/^\s*[-*]\s+(.*)/)
		const ol = line.match(/^\s*\d+\.\s+(.*)/)
		if (ul || ol) {
			flushPara()
			const tag = ul ? "ul" : "ol"
			if (!list || list.tag !== tag) {
				flushList()
				list = { tag, items: [] }
			}
			list.items.push((ul || ol)[1])
			i++
			continue
		}
		if (!line.trim()) {
			flushPara()
			flushList()
			i++
			continue
		}
		flushList()
		para.push(line.trim())
		i++
	}
	flushPara()
	flushList()
	return out.join("\n")
}
