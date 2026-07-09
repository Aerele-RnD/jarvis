<template>
	<div class="wg-detail" v-if="node">
		<div class="wg-detail-head">
			<span class="wg-kind" :class="'k-' + node.kind">{{ node.kind }}</span>
			<strong>{{ node.label || node.id }}</strong>
		</div>
		<table class="wg-kv">
			<tr v-if="node.page_type"><td>Type</td><td>{{ node.page_type }}</td></tr>
			<tr v-if="node.scope"><td>Scope</td><td>{{ node.scope }}</td></tr>
			<tr v-if="m.degree != null"><td>Connections</td><td>{{ m.degree }}</td></tr>
			<tr v-if="node.kind === 'page'"><td>Reads (demand)</td><td>{{ node.demand || 0 }}</td></tr>
			<tr v-if="node.last_read"><td>Last read</td><td>{{ shortDate(node.last_read) }}</td></tr>
			<tr v-if="node.kind === 'page'"><td>Cluster</td><td>{{ clusterLabel }}</td></tr>
			<tr v-if="m.betweenness > 0"><td>Broker</td><td class="warn">bridges clusters</td></tr>
			<tr v-if="node.stale"><td>Stale</td><td class="warn">yes</td></tr>
			<tr v-if="node.contradiction"><td>Contradiction</td><td class="warn">flagged</td></tr>
			<tr v-if="node.debt"><td>Knowledge debt</td><td class="warn">hot + stale</td></tr>
			<tr v-if="m.orphan"><td>Orphan</td><td class="warn">no links</td></tr>
		</table>
		<div class="wg-actions" v-if="showActions && node.kind === 'page'">
			<button class="wg-act" @click="$emit('focus', node.id)">Focus</button>
			<button class="wg-act" v-if="siteUrl" @click="openPage">Open page ↗</button>
			<button class="wg-act" @click="copySlug">Copy slug</button>
		</div>
	</div>
	<div class="wg-detail empty text-muted" v-else><i>Click a node for details.</i></div>
</template>

<script>
export default {
	name: "DetailPanel",
	props: {
		node: { type: Object, default: null },
		metrics: { type: Object, default: () => ({}) },
		communities: { type: Object, default: () => ({}) },
		siteUrl: { type: String, default: null },
		// Focus / Copy slug / Open page actions. On for the operator graph; the
		// tenant graph turns them off for a read-only detail view.
		showActions: { type: Boolean, default: true },
	},
	emits: ["focus"],
	computed: {
		m() { return (this.node && this.metrics[this.node.id]) || {}; },
		clusterLabel() {
			const c = this.communities[this.m.community];
			return c ? c.label : this.m.community;
		},
	},
	methods: {
		shortDate(v) { return String(v || "").slice(0, 10); },
		openPage() {
			const url = `${this.siteUrl.replace(/\/$/, "")}/app/jarvis-wiki-page/${encodeURIComponent(this.node.slug)}`;
			window.open(url, "_blank", "noopener");
		},
		copySlug() {
			try { navigator.clipboard.writeText(this.node.slug); frappe.show_alert("Slug copied"); } catch (_) {}
		},
	},
};
</script>

<style scoped>
.wg-detail { border: 1px solid var(--border-color, #e2e6ea); border-radius: 8px; padding: 12px; }
.wg-detail.empty { text-align: center; padding: 20px 12px; }
.wg-detail-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.wg-kind { font-size: 10px; text-transform: uppercase; padding: 1px 6px; border-radius: 4px; color: #fff; }
.k-org { background: #a970ff; } .k-role { background: #f2b134; }
.k-user { background: #4c9aff; } .k-page { background: #8892b0; }
.wg-kv { width: 100%; font-size: 12px; }
.wg-kv td:first-child { color: var(--text-muted, #888); padding-right: 10px; white-space: nowrap; }
.wg-kv .warn { color: #d9534f; }
.wg-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.wg-act { font-size: 11px; padding: 2px 8px; border: 1px solid var(--border-color, #d1d8dd); border-radius: 6px; background: var(--card-bg, #fff); cursor: pointer; }
.wg-act:hover { background: var(--control-bg, #f3f4f6); }
</style>
