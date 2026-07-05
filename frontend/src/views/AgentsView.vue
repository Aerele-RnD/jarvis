<template>
	<div class="ag-root" :class="{ 'jv-dark': effectiveDark }" :style="paletteVars">
		<!-- ============ TOP BAR: brand / back to chat ============ -->
		<header class="ag-top">
			<router-link to="/" class="ag-brand" title="Back to chat">
				<span class="ag-logo">
					<svg width="15" height="15" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg>
				</span>
				<span class="ag-brand-txt">Jarvis</span>
			</router-link>
			<span class="ag-crumb-sep">/</span>
			<span class="ag-crumb">Agents</span>
			<div style="flex:1;"></div>
			<router-link to="/" class="jv-btn jv-btn--ghost jv-btn--sm">
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
				Back to chat
			</router-link>
			<button class="jv-btn jv-btn--icon" @click="toggleTheme" :title="effectiveDark ? 'Switch to light theme' : 'Switch to dark theme'">
				<svg v-if="effectiveDark" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
				<svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
			</button>
		</header>

		<!-- ============ PAGE HEAD: title + tabs ============ -->
		<div class="ag-head">
			<div class="ag-head-in">
				<h1 class="ag-title">Agents</h1>
				<p class="ag-sub">Specialist auditors and operators for your ERP — install them, schedule them, and review what they find.</p>
				<nav class="ag-tabs" role="tablist">
					<button v-for="t in tabsShown" :key="t.id" class="ag-tab" :class="{ on: tab === t.id }" role="tab" :aria-selected="String(tab === t.id)" @click="goTab(t.id)">
						{{ t.label }}<span v-if="t.id === 'mine' && mineRows.length" class="ag-tab-n">{{ mineRows.length }}</span>
					</button>
				</nav>
			</div>
		</div>

		<!-- ============ CONTENT ============ -->
		<main class="ag-main">
			<div class="ag-content">
				<div v-if="loadError" class="jv-skill-err">{{ loadError }}</div>
				<div v-if="actionError" class="jv-skill-err">{{ actionError }}</div>

				<!-- ── MARKETPLACE ─────────────────────────────────────────── -->
				<section v-if="tab === 'marketplace'">
					<div class="ag-toolbar">
						<div class="ag-search">
							<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
							<input v-model="search" placeholder="Search agents" />
						</div>
						<select class="jv-skill-in ag-filter" v-model="fNature" title="Filter by nature">
							<option value="">All natures</option>
							<option value="Auditor">Auditor · read-only</option>
							<option value="Operator">Operator · drafts</option>
						</select>
						<select class="jv-skill-in ag-filter" v-model="fStatus" title="Filter by status">
							<option value="">All statuses</option>
							<option value="Published">Published</option>
							<option value="Coming Soon">Coming soon</option>
							<option value="Deprecated">Deprecated (installed)</option>
						</select>
					</div>

					<div v-if="loading" class="ag-empty">Loading the catalog…</div>
					<div v-else-if="!domainGroups.length" class="ag-empty">
						<b>No agents match.</b>
						<span>Try clearing the search or filters — the catalog grows domain by domain.</span>
					</div>

					<section v-for="g in domainGroups" :key="g.slug" class="ag-domain">
						<div class="ag-domain-head">
							<h2 class="ag-domain-title">{{ g.title }}</h2>
							<span class="ag-domain-blurb">{{ g.blurb }}</span>
						</div>
						<div class="ag-grid">
							<article v-for="a in g.agents" :key="a.agent_slug" class="ag-card" :class="{ dim: a.status === 'Coming Soon', expanded: expanded === a.agent_slug }">
								<div class="ag-card-top">
									<div class="ag-card-title">{{ a.title }}</div>
									<span class="ag-chip" :class="a.nature === 'Auditor' ? 'ag-chip--auditor' : 'ag-chip--operator'">
										{{ a.nature }} · {{ a.nature === "Auditor" ? "read-only" : "writes drafts" }}
									</span>
									<span v-if="a.status !== 'Published'" class="ag-chip ag-chip--muted">{{ a.status }}</span>
									<span v-if="a.update_available" class="ag-chip ag-chip--red">Update</span>
								</div>
								<div class="ag-card-meta">
									<span class="ag-chip ag-chip--domain">{{ domainTitle(a.category) }}</span>
									<span v-if="a.version && a.version !== '0.0.0'">v{{ a.version }}</span>
									<span v-if="a.validated_for_fy">validated FY {{ a.validated_for_fy }}</span>
									<span v-if="a.publisher">{{ a.publisher }}</span>
								</div>
								<div v-if="a.description" class="ag-card-desc" :class="{ full: expanded === a.agent_slug }">{{ a.description }}</div>

								<!-- lock: visible in catalog, install refused (server enforces too) -->
								<div v-if="!a.allowed" class="ag-lock">
									<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
									<span>Available to: <b>{{ (a.allowed_roles || []).join(", ") || "—" }}</b> — ask your administrator.</span>
								</div>

								<div class="ag-card-foot">
									<button v-if="!a.installed && a.status === 'Coming Soon'" class="jv-btn jv-btn--ghost jv-btn--sm" disabled>Coming soon</button>
									<button v-else-if="!a.installed" class="jv-btn jv-btn--primary jv-btn--sm"
										:disabled="a.status !== 'Published' || !a.allowed || busy === a.agent_slug"
										:title="!a.allowed ? 'Your roles do not permit this agent' : ''"
										@click="installNow(a)">{{ busy === a.agent_slug ? "Installing…" : "Install" }}</button>
									<span v-else class="ag-installed">
										<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
										Installed
									</span>
									<button v-if="a.installed" class="jv-btn jv-btn--ghost jv-btn--sm" @click="goTab('mine')">Manage</button>
									<div style="flex:1;"></div>
									<button class="jv-btn jv-btn--sm ag-details-btn" @click="expanded = expanded === a.agent_slug ? '' : a.agent_slug">
										{{ expanded === a.agent_slug ? "Less" : "Details" }}
										<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" :style="expanded === a.agent_slug ? 'transform:rotate(180deg);' : ''"><path d="m6 9 6 6 6-6" /></svg>
									</button>
								</div>

								<!-- expanded details -->
								<div v-if="expanded === a.agent_slug" class="ag-card-detail">
									<div class="ag-detail-row" v-if="a.rule_pack">
										<span class="jv-skill-l">Rule pack</span>
										<div>{{ a.rule_pack }} — versioned, dated rules bundled with the agent and reviewed before shipping. Statutory rules carry their section and effective date.</div>
									</div>
									<div class="ag-detail-row" v-if="agentTools(a).length">
										<span class="jv-skill-l">Tools it uses</span>
										<div class="ag-tools"><code v-for="t in agentTools(a)" :key="t" class="ag-tool">{{ t }}</code></div>
									</div>
									<div class="ag-detail-row">
										<span class="jv-skill-l">Default schedule</span>
										<div>{{ defaultScheduleText(a) }}</div>
									</div>
									<div class="ag-detail-row" v-if="(a.allowed_roles || []).length">
										<span class="jv-skill-l">Restricted to</span>
										<div>{{ a.allowed_roles.join(", ") }}</div>
									</div>
								</div>
							</article>
						</div>
					</section>
				</section>

				<!-- ── MINE ───────────────────────────────────────────────── -->
				<section v-else-if="tab === 'mine'" class="ag-mine">
					<div v-if="loading" class="ag-empty">Loading your agents…</div>
					<div v-else-if="!mineRows.length" class="ag-empty">
						<b>No agents installed yet.</b>
						<span>Auditors scrutinise your ledgers read-only; operators draft documents up to the Approval Board.</span>
						<button class="jv-btn jv-btn--primary jv-btn--sm" style="margin-top:10px;" @click="goTab('marketplace')">Browse the marketplace</button>
					</div>

					<article v-for="a in mineRows" :key="a.installation" class="ag-inst">
						<div class="ag-inst-head">
							<div class="ag-card-title">{{ a.title }}</div>
							<span class="ag-chip" :class="a.nature === 'Auditor' ? 'ag-chip--auditor' : 'ag-chip--operator'">{{ a.nature }}</span>
							<span v-if="a.status === 'Deprecated'" class="ag-chip ag-chip--red">Deprecated</span>
							<span v-if="a.update_available" class="ag-chip ag-chip--red">Update on next Apply</span>
							<span v-if="a.sync_status" class="ag-chip" :class="a.sync_status === 'synced' ? 'ag-chip--green' : 'ag-chip--muted'">{{ a.sync_status }}</span>
							<div style="flex:1;"></div>
							<label class="ag-enable">
								<button class="jv-switch" :class="{ on: a.enabled }" :disabled="busy === a.installation" role="switch" :aria-checked="String(!!a.enabled)" @click="toggleEnabled(a)"><span class="jv-switch-knob"></span></button>
								{{ a.enabled ? "Enabled" : "Disabled" }}
							</label>
						</div>
						<div class="ag-card-meta" style="margin:4px 0 0;">
							<span v-if="a.installed_version">v{{ a.installed_version }}</span>
							<span v-if="a.last_run_at">last run {{ ago(a.last_run_at) }}</span>
							<span v-if="a.next_run_at">next run {{ fmtDt(a.next_run_at) }}</span>
						</div>
						<div v-if="!a.allowed" class="ag-lock" style="margin-top:8px;">
							<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
							<span>Your roles no longer permit this agent — scheduled and manual runs are refused. Ask your administrator.</span>
						</div>

						<!-- auditor: schedule + materiality (instant saves; no Apply needed) -->
						<div v-if="a.nature === 'Auditor' && schedDrafts[a.installation]" class="ag-inst-body">
							<div class="ag-inst-col">
								<div class="ag-inst-col-title">Schedule</div>
								<label class="ag-enable" style="margin-bottom:8px;">
									<button class="jv-switch" :class="{ on: schedDrafts[a.installation].schedule_enabled }" role="switch" :aria-checked="String(!!schedDrafts[a.installation].schedule_enabled)" @click="schedDrafts[a.installation].schedule_enabled = schedDrafts[a.installation].schedule_enabled ? 0 : 1"><span class="jv-switch-knob"></span></button>
									Run automatically
								</label>
								<div v-if="schedDrafts[a.installation].schedule_enabled" class="ag-fields">
									<div>
										<label class="jv-skill-l">Frequency</label>
										<select class="jv-skill-in" v-model="schedDrafts[a.installation].schedule_frequency">
											<option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option>
										</select>
									</div>
									<div>
										<label class="jv-skill-l">Time</label>
										<input type="time" class="jv-skill-in" v-model="schedDrafts[a.installation].schedule_time" />
									</div>
								</div>
								<button class="jv-btn jv-btn--sm jv-btn--primary" style="margin-top:10px;" :disabled="busy === a.installation" @click="saveSchedule(a)">Save schedule</button>
							</div>
							<div class="ag-inst-col" v-if="cfgDrafts[a.installation]">
								<div class="ag-inst-col-title">Materiality (SA 320)</div>
								<div class="ag-fields">
									<div>
										<label class="jv-skill-l">Benchmark value</label>
										<input type="number" class="jv-skill-in" v-model="cfgDrafts[a.installation].benchmark_value" placeholder="e.g. 5000000" />
									</div>
									<div>
										<label class="jv-skill-l">Percentage (%)</label>
										<input type="number" step="0.1" class="jv-skill-in" v-model="cfgDrafts[a.installation].percentage" placeholder="e.g. 5" />
									</div>
								</div>
								<div class="ag-fields" style="margin-top:8px;">
									<div>
										<label class="jv-skill-l">Engagement risk</label>
										<select class="jv-skill-in" v-model="cfgDrafts[a.installation].engagement_risk_level">
											<option value="High">High</option><option value="Medium">Medium</option><option value="Low">Low</option>
										</select>
									</div>
									<div>
										<label class="jv-skill-l">Rounding step</label>
										<input type="number" class="jv-skill-in" v-model="cfgDrafts[a.installation].rounding_step" placeholder="e.g. 1000" />
									</div>
								</div>
								<button class="jv-btn jv-btn--sm jv-btn--primary" style="margin-top:10px;" :disabled="busy === a.installation" @click="saveConfig(a)">Save materiality</button>
							</div>
						</div>

						<div class="ag-inst-actions">
							<button v-if="a.nature === 'Auditor'" class="jv-btn jv-btn--sm" :disabled="!a.enabled || !a.allowed || busy === a.installation"
								:title="!a.enabled ? 'Enable the agent first' : (!a.allowed ? 'Your roles do not permit this agent' : 'Run this audit now')"
								@click="runNow(a)">Run now</button>
							<button class="jv-btn jv-btn--sm jv-btn--danger" :disabled="busy === a.installation" @click="uninstallNow(a)">Uninstall</button>
						</div>
					</article>

					<!-- ONE sticky Apply bar -->
					<div v-if="mineRows.length" class="ag-applybar">
						<span class="ag-applypill" :class="{ pending: sync.pending, err: syncFailed, ok: syncOk && !sync.pending }">
							<span v-if="sync.pending" class="ag-dot spin"></span>
							<span v-else-if="syncFailed" class="ag-dot err"></span>
							<span v-else-if="syncOk" class="ag-dot ok"></span>
							<span v-else class="ag-dot"></span>
							<template v-if="sync.pending">Applying to your assistant… (~30s, one restart)</template>
							<template v-else-if="syncFailed">Couldn't apply. {{ sync.last_sync_status.replace("failed:", "").trim() }}</template>
							<template v-else-if="syncOk">Agents applied</template>
							<template v-else>Not applied yet</template>
						</span>
						<span class="ag-applycopy">Enable, schedule and materiality changes are <b>instant</b>. Apply ships installs, uninstalls and updates to your assistant — one brief restart.</span>
						<button class="jv-btn jv-btn--primary jv-btn--sm" :disabled="sync.pending" @click="applyNow()">Apply</button>
					</div>
				</section>

				<!-- ── ACTIVITY ───────────────────────────────────────────── -->
				<section v-else-if="tab === 'activity'">
					<div v-if="activityError" class="jv-skill-err">{{ activityError }}</div>
					<div class="ag-toolbar">
						<select class="jv-skill-in ag-filter" v-model="aAgent" title="Filter by agent">
							<option value="">All agents</option>
							<option v-for="a in catalog" :key="a.agent_slug" :value="a.name">{{ a.title }}</option>
						</select>
						<select class="jv-skill-in ag-filter" v-model="aSeverity" title="Filter findings by severity">
							<option value="">All severities</option>
							<option value="blocker">Blocker</option><option value="warning">Warning</option><option value="note">Note</option>
						</select>
						<select class="jv-skill-in ag-filter" v-model="aState" title="Filter findings by state">
							<option value="">All states</option>
							<option value="open">Open</option><option value="acknowledged">Acknowledged</option><option value="resolved">Resolved</option>
						</select>
					</div>

					<div class="ag-activity">
						<!-- runs timeline -->
						<div>
							<h3 class="ag-h3">Runs</h3>
							<div v-if="!activityLoaded" class="ag-empty">Loading runs…</div>
							<div v-else-if="!runsShown.length" class="ag-empty">
								<b>No runs yet.</b>
								<span>Install an auditor, enable it, then use <i>Run now</i> or a schedule — every run lands here with its findings.</span>
							</div>
							<div v-for="r in runsShown" :key="r.name" class="ag-run">
								<span class="ag-chip" :class="runChipClass(r.status)">{{ r.status }}</span>
								<div class="ag-run-main">
									<div class="ag-run-title">{{ agentTitle(r.agent) }} <span class="ag-run-trigger">· {{ r.trigger }}</span></div>
									<div class="ag-run-sub">
										<span>{{ ago(r.started_at) }}</span>
										<span :class="{ 'ag-blockers': r.blocker_count > 0 }">{{ r.findings_count || 0 }} finding{{ (r.findings_count || 0) === 1 ? "" : "s" }}<template v-if="r.blocker_count"> · {{ r.blocker_count }} blocker{{ r.blocker_count === 1 ? "" : "s" }}</template></span>
									</div>
									<div v-if="r.status === 'partial' && r.coverage_note" class="ag-run-note">{{ r.coverage_note }}</div>
									<div v-if="r.status === 'failed' && r.error" class="ag-run-err">{{ r.error }}</div>
								</div>
								<router-link v-if="r.conversation" class="ag-run-link" :to="`/c/${r.conversation}`">Open conversation</router-link>
							</div>
						</div>

						<!-- findings board -->
						<div>
							<h3 class="ag-h3">Findings</h3>
							<div v-if="!activityLoaded" class="ag-empty">Loading findings…</div>
							<div v-else-if="!findingGroups.length" class="ag-empty">
								<b>No findings{{ aSeverity || aState || aAgent ? " match these filters" : " yet" }}.</b>
								<span>Runs that surface issues list them here, grouped by severity, so you can acknowledge or resolve each one.</span>
							</div>
							<template v-for="[sev, items] in findingGroups" :key="sev">
								<div class="ag-sevhead">
									<span class="ag-chip" :class="sevChipClass(sev)">{{ sev }}</span>
									<span class="ag-sevcount">{{ items.length }}</span>
								</div>
								<div v-for="f in items" :key="f.name" class="ag-finding" :class="{ resolved: f.state === 'resolved' }">
									<div class="ag-finding-top">
										<div class="ag-finding-title">{{ f.title }}</div>
										<span v-if="f.rule_id" class="ag-chip ag-chip--muted mono">{{ f.rule_id }}</span>
										<span v-if="f.first_seen_run && f.first_seen_run === f.last_seen_run" class="ag-chip ag-chip--auditor">NEW</span>
										<span v-else-if="f.first_seen_run" class="ag-chip ag-chip--muted">recurring</span>
										<span class="ag-chip" :class="f.state === 'resolved' ? 'ag-chip--green' : f.state === 'acknowledged' ? 'ag-chip--muted' : 'ag-chip--red'">{{ f.state }}</span>
									</div>
									<div v-if="f.detail_md" class="ag-finding-detail">{{ f.detail_md }}</div>
									<div v-if="f.ref_doctype" class="ag-finding-ref">
										{{ f.ref_doctype }}<span v-if="f.ref_name">: {{ f.ref_name }}</span><span v-if="f.amount != null && f.amount !== ''"> · {{ fmtAmount(f.amount) }}</span>
									</div>
									<div v-if="f.section" class="ag-statutory">
										<b>{{ f.section }}</b><span v-if="f.effective_date"> · effective {{ f.effective_date }}</span>
										— automated finding, informational only. Not professional, legal, or audit assurance; verify against the source records and applicable law before acting.
									</div>
									<div class="ag-finding-actions">
										<button v-if="f.state === 'open'" class="jv-btn jv-btn--sm" :disabled="busy === f.name" @click="moveFinding(f, 'acknowledged')">Acknowledge</button>
										<button v-if="f.state !== 'resolved'" class="jv-btn jv-btn--sm jv-btn--primary" :disabled="busy === f.name" @click="moveFinding(f, 'resolved')">Resolve</button>
										<button v-if="f.state !== 'open'" class="jv-btn jv-btn--sm" :disabled="busy === f.name" @click="moveFinding(f, 'open')">Reopen</button>
									</div>
								</div>
							</template>
						</div>
					</div>
				</section>

				<!-- ── ADMIN (System Manager only; server enforces every call) ── -->
				<section v-else-if="tab === 'admin' && adminAllowed">
					<div v-if="adminError" class="jv-skill-err">{{ adminError }}</div>
					<div class="ag-admin-note">
						<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 16v-5M12 8v.01" /></svg>
						Role gating is enforced <b>server-side</b> on every path — install, run-now, the scheduler and the container payload. This page only edits who is allowed; an empty role list means everyone.
					</div>

					<article v-for="l in admin.listings" :key="l.agent_slug" class="ag-inst">
						<div class="ag-inst-head">
							<div class="ag-card-title">{{ l.title }}</div>
							<span class="ag-chip" :class="l.nature === 'Auditor' ? 'ag-chip--auditor' : 'ag-chip--operator'">{{ l.nature }}</span>
							<span class="ag-chip ag-chip--domain">{{ domainTitle(l.category) }}</span>
							<span v-if="l.version && l.version !== '0.0.0'" class="ag-run-trigger">v{{ l.version }}</span>
							<div style="flex:1;"></div>
							<label class="jv-skill-l" style="margin:0;">Status</label>
							<select class="jv-skill-in ag-status-sel" :value="l.status" :disabled="busy === 'status:' + l.agent_slug" @change="onStatusChange(l, $event)">
								<option v-if="!ADMIN_STATUSES.includes(l.status)" :value="l.status" disabled>{{ l.status }}</option>
								<option value="Published">Published</option>
								<option value="Coming Soon">Coming Soon</option>
								<option value="Deprecated">Deprecated</option>
							</select>
						</div>

						<div class="ag-roles">
							<div class="ag-inst-col-title" style="margin-bottom:6px;">
								Allowed roles
								<span v-if="!(l.allowed_roles || []).length" class="ag-chip ag-chip--green" style="margin-left:6px;">Everyone — no restriction</span>
							</div>
							<div class="ag-roles-grid">
								<label v-for="r in admin.roles" :key="r" class="ag-role">
									<input type="checkbox" :checked="(roleDrafts[l.agent_slug] || []).includes(r)" @change="toggleRole(l, r)" />
									<span>{{ r }}</span>
								</label>
							</div>
							<div v-if="rolesDirty(l)" class="ag-roles-save">
								<button class="jv-btn jv-btn--sm jv-btn--primary" :disabled="busy === 'roles:' + l.agent_slug" @click="saveRoles(l)">Save roles</button>
								<button class="jv-btn jv-btn--ghost jv-btn--sm" @click="roleDrafts[l.agent_slug] = [...(l.allowed_roles || [])]">Reset</button>
								<span v-if="!(roleDrafts[l.agent_slug] || []).length" class="ag-run-trigger">Saving with none selected clears the restriction (everyone).</span>
							</div>
						</div>

						<div class="ag-inst-col-title" style="margin:12px 0 6px;">Installs ({{ (l.installs || []).length }})</div>
						<div v-if="!(l.installs || []).length" class="ag-empty" style="padding:10px 0;">No installs yet.</div>
						<div v-else class="ag-table-wrap">
							<table class="ag-table">
								<thead><tr><th>Owner</th><th>Enabled</th><th>Schedule</th><th>Next run</th><th>Last run</th><th>Sync</th></tr></thead>
								<tbody>
									<tr v-for="i in l.installs" :key="i.installation">
										<td>{{ i.owner }}</td>
										<td>{{ i.enabled ? "Yes" : "No" }}</td>
										<td>{{ i.schedule_enabled ? (i.schedule_frequency || "on") : "off" }}</td>
										<td>{{ i.next_run_at ? fmtDt(i.next_run_at) : "—" }}</td>
										<td>{{ i.last_run_at ? ago(i.last_run_at) : "—" }}</td>
										<td>{{ i.sync_status || "—" }}</td>
									</tr>
								</tbody>
							</table>
						</div>
					</article>
				</section>
			</div>
		</main>

		<!-- ============ TOASTS ============ -->
		<div class="jv-notes" aria-live="polite">
			<transition-group name="jv-note">
				<div v-for="n in notes" :key="n.id" class="jv-note" :class="n.type" role="status">
					<span class="jv-note-ic" aria-hidden="true">
						<svg v-if="n.type === 'success'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
						<svg v-else-if="n.type === 'error'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16.4v.01" /></svg>
						<svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 16v-5M12 8v.01" /></svg>
					</span>
					<div class="jv-note-msg">{{ n.message }}</div>
					<button class="jv-note-x" @click="dismissNote(n.id)" title="Dismiss" aria-label="Dismiss"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg></button>
				</div>
			</transition-group>
		</div>

		<!-- ============ CONFIRM DIALOG ============ -->
		<transition name="jv-fade">
			<div v-if="confirmBox" class="ag-overlay" @click.self="_settleConfirm(false)">
				<div class="jv-cdialog" role="alertdialog" aria-modal="true">
					<div class="jv-cdialog-title">{{ confirmBox.title }}</div>
					<div v-if="confirmBox.message" class="jv-cdialog-msg">{{ confirmBox.message }}</div>
					<div class="jv-cdialog-foot">
						<button class="jv-btn jv-btn--ghost" @click="_settleConfirm(false)">Cancel</button>
						<button class="jv-btn jv-btn--danger" @click="_settleConfirm(true)">{{ confirmBox.confirmLabel }}</button>
					</div>
				</div>
			</div>
		</transition>
	</div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import * as api from "@/api"
import { useJarvisTheme } from "@/theme"

const route = useRoute()
const router = useRouter()
const { effectiveDark, paletteVars, toggleTheme } = useJarvisTheme()

// ── static display metadata ─────────────────────────────────────────────────
// Mirrors jarvis/agents/registry.json "domains" (display-only: grouping titles
// + blurbs; the backend keys listings by domain slug in `category`). New
// domains added to the registry fall back to a prettified slug until mirrored.
const DOMAINS = [
	{ slug: "audit", title: "Audit & Ledger Scrutiny", blurb: "Reproducible ledger scrutiny with materiality-parameterised rules." },
	{ slug: "compliance", title: "Statutory Compliance", blurb: "India GST/TDS/Income-Tax checks. Statutory thresholds are dated & law-review gated." },
	{ slug: "close", title: "Close & Reporting", blurb: "Period-end: trial-balance integrity, materiality, misstatement aggregation." },
	{ slug: "ap", title: "Accounts Payable", blurb: "Payables & expense: draft inbound documents through to the Approval Board." },
	{ slug: "ar", title: "AR & Collections", blurb: "Order-to-cash and collections." },
	{ slug: "bank-recon", title: "Bank & Reconciliation", blurb: "Bank & cash reconciliation." },
	{ slug: "analytical-review", title: "Analytical Review", blurb: "Schedule III ratios and year-over-year variance review." },
]
// Display-only fallback for "tools it uses" (mirrors registry tools_required;
// used when list_agents doesn't carry a tools_required field — prefer the API
// value whenever the backend starts returning it).
const TOOLS_FALLBACK = {
	"audit-auditor": ["jarvis__compute_materiality", "jarvis__run_scrutiny", "jarvis__get_list", "jarvis__run_report"],
	"compliance-auditor": ["jarvis__compute_materiality", "jarvis__run_scrutiny", "jarvis__get_list", "jarvis__run_report"],
	"close-auditor": ["jarvis__compute_materiality", "jarvis__run_scrutiny", "jarvis__run_report", "jarvis__get_balance_on"],
	"ap-operator": ["jarvis__get_schema", "jarvis__get_list", "jarvis__get_doc", "jarvis__create_doc", "jarvis__update_doc", "jarvis__query"],
}
const ADMIN_STATUSES = ["Published", "Coming Soon", "Deprecated"]
const VALID_TABS = ["marketplace", "mine", "activity", "admin"]
const TABS = [
	{ id: "marketplace", label: "Marketplace" },
	{ id: "mine", label: "My agents" },
	{ id: "activity", label: "Activity" },
	{ id: "admin", label: "Admin" },
]

// ── state ───────────────────────────────────────────────────────────────────
const tab = ref("marketplace")
const loading = ref(true)
const loadError = ref("")
const actionError = ref("")
const catalog = ref([]) // list_agents rows (listing + this owner's install state + allowed/allowed_roles)
const installs = ref([]) // get_installations rows (config JSON, sync_status, …)
const busy = ref("") // slug / installation / "roles:<slug>" currently mutating
const expanded = ref("") // agent_slug whose marketplace card shows full details
const search = ref("")
const fNature = ref("")
const fStatus = ref("")
const sync = ref({ last_sync_status: "", pending: false })
let syncPoll = null
const schedDrafts = ref({}) // installation -> { schedule_enabled, schedule_frequency, schedule_time }
const cfgDrafts = ref({}) // installation -> { benchmark_value, percentage, engagement_risk_level, rounding_step }
// activity
const runs = ref([])
const findings = ref([])
const activityLoaded = ref(false)
const activityError = ref("")
const aAgent = ref("")
const aSeverity = ref("")
const aState = ref("")
// admin (probed once on mount; PermissionError = hide the tab entirely)
const adminAllowed = ref(false)
const adminProbed = ref(false)
const admin = ref({ roles: [], listings: [] })
const adminError = ref("")
const roleDrafts = ref({}) // agent_slug -> [role, ...] (checkbox draft)

// ── toasts + confirm (same vocabulary as ChatView's notifier/dialog) ────────
const notes = ref([])
let _noteSeq = 0
function notify(message, opts = {}) {
	const id = ++_noteSeq
	notes.value = [...notes.value, { id, message, type: opts.type || "info" }]
	setTimeout(() => dismissNote(id), opts.duration || 3200)
}
function dismissNote(id) {
	notes.value = notes.value.filter((n) => n.id !== id)
}
const confirmBox = ref(null)
let _confirmResolve = null
function confirmDialog(opts = {}) {
	return new Promise((resolve) => {
		_confirmResolve = resolve
		confirmBox.value = { title: opts.title || "Are you sure?", message: opts.message || "", confirmLabel: opts.confirmLabel || "Confirm" }
	})
}
function _settleConfirm(val) {
	confirmBox.value = null
	const r = _confirmResolve
	_confirmResolve = null
	if (r) r(val)
}
function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

// ── tab routing (deep-linkable: /agents, /agents/mine, /activity, /admin) ──
const tabsShown = computed(() => TABS.filter((t) => t.id !== "admin" || adminAllowed.value))
function goTab(t) {
	router.push(t === "marketplace" ? "/agents" : `/agents/${t}`)
}
function applyRouteTab() {
	if (route.name !== "Agents") return // leaving the page — don't touch state
	const t = route.params.tab || "marketplace"
	if (!VALID_TABS.includes(t)) {
		router.replace("/agents")
		return
	}
	// Admin deep link before/without permission: bounce silently to marketplace.
	if (t === "admin" && adminProbed.value && !adminAllowed.value) {
		router.replace("/agents")
		return
	}
	tab.value = t
	if (t === "activity") loadActivity()
}
watch(() => route.params.tab, applyRouteTab)

// ── loading ─────────────────────────────────────────────────────────────────
async function loadCatalog() {
	try {
		const [cat, inst] = await Promise.all([api.listAgents(), api.getAgentInstallations()])
		catalog.value = cat || []
		installs.value = inst || []
		loadError.value = ""
		seedDrafts()
	} catch (e) {
		loadError.value = "Could not load the agent catalog."
	} finally {
		loading.value = false
	}
}
// Seed per-install editor drafts once (don't clobber in-progress edits when an
// unrelated action reloads the catalog); drop drafts for gone installations.
function seedDrafts() {
	const live = new Set()
	for (const a of catalog.value) {
		if (!a.installed || !a.installation) continue
		live.add(a.installation)
		if (!schedDrafts.value[a.installation]) {
			schedDrafts.value[a.installation] = {
				schedule_enabled: a.schedule_enabled ? 1 : 0,
				schedule_frequency: a.schedule_frequency || "daily",
				schedule_time: timeHHMM(a.schedule_time) || "09:00",
			}
		}
		if (!cfgDrafts.value[a.installation]) {
			let cfg = {}
			const inst = installs.value.find((i) => i.name === a.installation)
			if (inst && inst.config) {
				try { cfg = JSON.parse(inst.config) || {} } catch (e) { cfg = {} }
			}
			cfgDrafts.value[a.installation] = {
				benchmark_value: cfg.benchmark_value ?? "",
				percentage: cfg.percentage ?? "",
				engagement_risk_level: cfg.engagement_risk_level || "Medium",
				rounding_step: cfg.rounding_step ?? "",
			}
		}
	}
	for (const k of Object.keys(schedDrafts.value)) if (!live.has(k)) delete schedDrafts.value[k]
	for (const k of Object.keys(cfgDrafts.value)) if (!live.has(k)) delete cfgDrafts.value[k]
}
async function loadSync() {
	try {
		const s = (await api.getAgentsSyncStatus()) || {}
		sync.value = { last_sync_status: s.last_sync_status || "", pending: !!s.pending }
		if (sync.value.pending) startSyncPoll()
	} catch (e) { /* pill is best-effort */ }
}
function startSyncPoll() {
	if (syncPoll) return
	syncPoll = setInterval(async () => {
		await loadSync()
		if (!sync.value.pending) {
			clearInterval(syncPoll)
			syncPoll = null
			loadCatalog() // per-install sync_status may have changed
		}
	}, 3000)
}
const syncFailed = computed(() => sync.value.last_sync_status.startsWith("failed"))
const syncOk = computed(() => sync.value.last_sync_status.startsWith("ok"))

async function probeAdmin() {
	try {
		const o = await api.getAgentAdminOverview()
		admin.value = { roles: o?.roles || [], listings: o?.listings || [] }
		for (const l of admin.value.listings) roleDrafts.value[l.agent_slug] = [...(l.allowed_roles || [])]
		adminAllowed.value = true
	} catch (e) {
		adminAllowed.value = false // not a System Manager — hide the tab, no noise
	} finally {
		adminProbed.value = true
		if (tab.value === "admin" && !adminAllowed.value) router.replace("/agents")
	}
}

// ── marketplace ─────────────────────────────────────────────────────────────
const visibleCatalog = computed(() => {
	const q = search.value.trim().toLowerCase()
	return catalog.value.filter((a) => {
		// Deprecated listings are hidden unless the user has them installed.
		if (a.status === "Deprecated" && !a.installed) return false
		if (fNature.value && a.nature !== fNature.value) return false
		if (fStatus.value && a.status !== fStatus.value) return false
		if (q) {
			const hay = `${a.title} ${a.description || ""} ${a.category || ""} ${a.agent_slug}`.toLowerCase()
			if (!hay.includes(q)) return false
		}
		return true
	})
})
const domainGroups = computed(() => {
	const bySlug = {}
	for (const a of visibleCatalog.value) {
		const k = a.category || "other"
		;(bySlug[k] || (bySlug[k] = [])).push(a)
	}
	const groups = []
	for (const d of DOMAINS) {
		if (bySlug[d.slug]?.length) {
			groups.push({ ...d, agents: bySlug[d.slug] })
			delete bySlug[d.slug]
		}
	}
	for (const [slug, agents] of Object.entries(bySlug)) {
		groups.push({ slug, title: prettySlug(slug), blurb: "", agents })
	}
	return groups
})
function domainTitle(slug) {
	return DOMAINS.find((d) => d.slug === slug)?.title || prettySlug(slug || "other")
}
function prettySlug(s) {
	return String(s).split("-").map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(" ")
}
function agentTools(a) {
	let t = a.tools_required
	if (typeof t === "string") {
		try { t = JSON.parse(t) } catch (e) { t = null }
	}
	if (Array.isArray(t) && t.length) return t
	return TOOLS_FALLBACK[a.agent_slug] || []
}
function defaultScheduleText(a) {
	let s = {}
	try { s = JSON.parse(a.default_schedule || "{}") || {} } catch (e) { s = {} }
	const freq = String(s.schedule_frequency || "").toLowerCase()
	if (!freq) return "None — runs on demand."
	return s.schedule_enabled ? `On by default · ${freq}` : `Off by default · suggested ${freq}`
}

// ── mine ────────────────────────────────────────────────────────────────────
const mineRows = computed(() =>
	catalog.value
		.filter((a) => a.installed && a.installation)
		.map((a) => {
			const inst = installs.value.find((i) => i.name === a.installation)
			return { ...a, sync_status: inst?.sync_status || "", last_run_at: inst?.last_run_at || null, installed_version: a.installed_version || inst?.installed_version }
		}),
)

// ── mutations (enable/schedule/config are INSTANT; Apply ships the bundle) ──
async function installNow(a) {
	if (a.status !== "Published" || a.installed || !a.allowed) return
	busy.value = a.agent_slug
	actionError.value = ""
	try {
		await api.installAgent(a.agent_slug)
		await loadCatalog()
		notify(`${a.title} installed — enable it and Apply when ready`, { type: "success" })
	} catch (e) { actionError.value = errMsg(e) } finally { busy.value = "" }
}
async function uninstallNow(a) {
	if (!a.installation) return
	if (!(await confirmDialog({ title: "Uninstall agent?", message: `Remove “${a.title}”? It leaves the container on the next Apply. Runs and findings are kept.`, confirmLabel: "Uninstall" }))) return
	busy.value = a.installation
	actionError.value = ""
	try {
		await api.uninstallAgent(a.installation)
		await loadCatalog()
		notify("Uninstalled — Apply to remove it from your assistant", { type: "success" })
	} catch (e) { actionError.value = errMsg(e) } finally { busy.value = "" }
}
async function toggleEnabled(a) {
	if (!a.installation) return
	busy.value = a.installation
	actionError.value = ""
	try {
		await api.setAgentEnabled(a.installation, a.enabled ? 0 : 1)
		await loadCatalog()
	} catch (e) { actionError.value = errMsg(e) } finally { busy.value = "" }
}
async function saveSchedule(a) {
	const d = schedDrafts.value[a.installation]
	if (!d) return
	busy.value = a.installation
	actionError.value = ""
	try {
		await api.setAgentSchedule(a.installation, {
			schedule_enabled: d.schedule_enabled ? 1 : 0,
			schedule_frequency: d.schedule_frequency,
			schedule_time: d.schedule_time || "",
		})
		await loadCatalog()
		notify("Schedule saved", { type: "success" })
	} catch (e) { actionError.value = errMsg(e) } finally { busy.value = "" }
}
async function saveConfig(a) {
	const d = cfgDrafts.value[a.installation]
	if (!d) return
	busy.value = a.installation
	actionError.value = ""
	// Coerce numeric materiality inputs; leave blanks out of the payload.
	const cfg = { engagement_risk_level: d.engagement_risk_level || "Medium" }
	for (const k of ["benchmark_value", "percentage", "rounding_step"]) {
		const v = String(d[k] ?? "").trim()
		if (v !== "") cfg[k] = Number(v)
	}
	try {
		await api.setAgentConfig(a.installation, cfg)
		await loadCatalog()
		notify("Materiality config saved", { type: "success" })
	} catch (e) { actionError.value = errMsg(e) } finally { busy.value = "" }
}
async function runNow(a) {
	busy.value = a.installation
	actionError.value = ""
	try {
		const r = await api.runAgentNow(a.installation)
		notify("Audit started", { type: "success" })
		const conv = r && r.data && (r.data.conversation || r.data.conversation_id)
		if (conv) router.push(`/c/${conv}`) // the run narrates in its own chat
		else {
			await loadCatalog()
			loadActivity(true)
		}
	} catch (e) { actionError.value = errMsg(e) } finally { busy.value = "" }
}
async function applyNow() {
	actionError.value = ""
	try {
		await api.applyAgents()
		sync.value = { last_sync_status: "pending: applying agents", pending: true }
		startSyncPoll()
	} catch (e) { actionError.value = errMsg(e) }
}

// ── activity ────────────────────────────────────────────────────────────────
async function loadActivity(force) {
	if (activityLoaded.value && !force) return
	activityError.value = ""
	try {
		const [r, f] = await Promise.all([api.listAgentRuns("", 50), api.listAgentFindings({ limit: 200 })])
		runs.value = r || []
		findings.value = f || []
		activityLoaded.value = true
	} catch (e) {
		activityError.value = "Could not load runs and findings."
		activityLoaded.value = true
	}
}
const runsShown = computed(() => runs.value.filter((r) => !aAgent.value || r.agent === aAgent.value))
const findingsShown = computed(() =>
	findings.value.filter(
		(f) =>
			(!aAgent.value || f.agent === aAgent.value) &&
			(!aSeverity.value || f.severity === aSeverity.value) &&
			(!aState.value || f.state === aState.value),
	),
)
const findingGroups = computed(() => {
	const order = ["blocker", "warning", "note"]
	const by = { blocker: [], warning: [], note: [] }
	for (const f of findingsShown.value) (by[f.severity] || (by[f.severity] = [])).push(f)
	return order.filter((s) => (by[s] || []).length).map((s) => [s, by[s]])
})
async function moveFinding(f, state) {
	busy.value = f.name
	try {
		await api.setFindingState(f.name, state)
		f.state = state // optimistic
	} catch (e) { notify(errMsg(e), { type: "error" }) } finally { busy.value = "" }
}
function agentTitle(name) {
	return catalog.value.find((a) => a.name === name)?.title || name
}
function runChipClass(s) {
	return s === "completed" ? "ag-chip--green" : s === "failed" ? "ag-chip--red" : s === "partial" ? "ag-chip--amber" : "ag-chip--muted"
}
function sevChipClass(s) {
	return s === "blocker" ? "ag-chip--red" : s === "warning" ? "ag-chip--amber" : "ag-chip--muted"
}

// ── admin mutations ─────────────────────────────────────────────────────────
async function onStatusChange(l, ev) {
	const status = ev.target.value
	if (status === l.status) return
	busy.value = "status:" + l.agent_slug
	adminError.value = ""
	try {
		const r = await api.setListingStatus(l.agent_slug, status)
		l.status = (r && r.status) || status
		notify(`${l.title} → ${l.status}`, { type: "success" })
		loadCatalog() // marketplace badges follow
	} catch (e) {
		ev.target.value = l.status // revert the select
		adminError.value = errMsg(e)
	} finally { busy.value = "" }
}
function toggleRole(l, role) {
	const cur = roleDrafts.value[l.agent_slug] || []
	roleDrafts.value[l.agent_slug] = cur.includes(role) ? cur.filter((r) => r !== role) : [...cur, role]
}
function rolesDirty(l) {
	const a = [...(roleDrafts.value[l.agent_slug] || [])].sort().join("|")
	const b = [...(l.allowed_roles || [])].sort().join("|")
	return a !== b
}
async function saveRoles(l) {
	busy.value = "roles:" + l.agent_slug
	adminError.value = ""
	try {
		const r = await api.setAgentRoles(l.agent_slug, roleDrafts.value[l.agent_slug] || [])
		l.allowed_roles = (r && r.allowed_roles) || []
		roleDrafts.value[l.agent_slug] = [...l.allowed_roles]
		notify(l.allowed_roles.length ? "Roles saved" : "Restriction cleared — available to everyone", { type: "success" })
		loadCatalog() // refresh allowed/lock state in the marketplace
	} catch (e) { adminError.value = errMsg(e) } finally { busy.value = "" }
}

// ── formatting helpers ──────────────────────────────────────────────────────
function parseDt(s) {
	if (!s) return null
	const d = new Date(String(s).replace(" ", "T"))
	return isNaN(d.getTime()) ? null : d
}
function ago(s) {
	const d = parseDt(s)
	if (!d) return ""
	const secs = Math.max(0, (Date.now() - d.getTime()) / 1000)
	if (secs < 60) return "just now"
	if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
	if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
	if (secs < 7 * 86400) return `${Math.floor(secs / 86400)}d ago`
	return d.toLocaleDateString()
}
function fmtDt(s) {
	const d = parseDt(s)
	return d ? d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : ""
}
function fmtAmount(v) {
	const n = Number(v)
	return isNaN(n) ? String(v) : n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}
// "9:00:00" (python str(timedelta)) → "09:00" for <input type="time">.
function timeHHMM(s) {
	const m = /^(\d{1,2}):(\d{2})/.exec(String(s || ""))
	return m ? `${m[1].padStart(2, "0")}:${m[2]}` : ""
}

// ── lifecycle ───────────────────────────────────────────────────────────────
function onKey(e) {
	if (e.key !== "Escape") return
	if (confirmBox.value) _settleConfirm(false)
	else if (expanded.value) expanded.value = ""
}
onMounted(async () => {
	applyRouteTab()
	window.addEventListener("keydown", onKey)
	await Promise.all([loadCatalog(), loadSync()])
	probeAdmin() // SM check: success shows the Admin tab, PermissionError hides it
	if (tab.value === "activity") loadActivity()
})
onBeforeUnmount(() => {
	window.removeEventListener("keydown", onKey)
	if (syncPoll) clearInterval(syncPoll)
})
</script>

<style scoped>
/* Native form controls follow the app theme (same as ChatView). */
.ag-root { color-scheme: light; }
.ag-root.jv-dark { color-scheme: dark; }
.ag-root {
	font-family: "Inter", system-ui, sans-serif;
	height: 100vh; width: 100%;
	display: flex; flex-direction: column;
	color: var(--text); background: var(--surface);
	overflow: hidden; position: relative;
}

/* ── top bar ── */
.ag-top { height: 52px; flex: none; display: flex; align-items: center; gap: 10px; padding: 0 18px; border-bottom: 1px solid var(--border); background: var(--surface); }
.ag-brand { display: flex; align-items: center; gap: 8px; text-decoration: none; color: var(--text); }
.ag-logo { width: 26px; height: 26px; border-radius: 7px; background: var(--blue); display: flex; align-items: center; justify-content: center; flex: none; box-shadow: 0 1px 2px rgba(37, 99, 235, .35); }
.jv-dark .ag-logo { background: linear-gradient(135deg, #6e8bff, #8b5cf6); box-shadow: 0 2px 10px rgba(110, 139, 255, .35); }
.ag-brand-txt { font-size: 14px; font-weight: 600; letter-spacing: -.01em; }
.ag-crumb-sep { color: var(--text-3); font-size: 13px; }
.ag-crumb { font-size: 13px; font-weight: 550; color: var(--text-2); }

/* ── page head + tabs ── */
.ag-head { flex: none; border-bottom: 1px solid var(--border); background: var(--surface-1); }
.ag-head-in { max-width: 1080px; margin: 0 auto; padding: 22px 24px 0; }
.ag-title { margin: 0; font-size: 21px; font-weight: 650; letter-spacing: -.02em; color: var(--text); }
.ag-sub { margin: 4px 0 14px; font-size: 12.5px; color: var(--text-3); }
.ag-tabs { display: flex; gap: 2px; }
.ag-tab { position: relative; appearance: none; background: transparent; border: none; border-bottom: 2px solid transparent; padding: 8px 12px 10px; font-family: inherit; font-size: 13px; font-weight: 550; color: var(--text-3); cursor: pointer; transition: color .12s; }
.ag-tab:hover { color: var(--text); }
.ag-tab.on { color: var(--text); border-bottom-color: var(--text); }
.ag-tab-n { margin-left: 6px; font-size: 10.5px; font-weight: 600; background: var(--surface-3); color: var(--text-2); border-radius: 8px; padding: 1.5px 6px; }

/* ── content ── */
.ag-main { flex: 1; min-height: 0; overflow-y: auto; }
.ag-content { max-width: 1080px; margin: 0 auto; padding: 20px 24px 40px; }
.ag-h3 { margin: 0 0 10px; font-size: 13px; font-weight: 650; color: var(--text); }

/* toolbar (search + filters) */
.ag-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 18px; }
.ag-search { flex: 1 1 220px; min-width: 180px; display: flex; align-items: center; gap: 8px; padding: 0 10px; height: 34px; background: var(--surface); border: 1px solid var(--border); border-radius: 9px; color: var(--text-3); }
.ag-search input { flex: 1; min-width: 0; border: none; outline: none; background: transparent; font-family: inherit; font-size: 12.5px; color: var(--text); }
.ag-filter { width: auto; flex: none; height: 34px; padding: 0 10px; font-size: 12.5px; }

/* domain sections + card grid */
.ag-domain { margin-bottom: 26px; }
.ag-domain-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.ag-domain-title { margin: 0; font-size: 13px; font-weight: 650; letter-spacing: .02em; color: var(--text); }
.ag-domain-blurb { font-size: 11.5px; color: var(--text-3); }
.ag-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.ag-card { display: flex; flex-direction: column; gap: 7px; border: 1px solid var(--border); border-radius: 12px; padding: 14px; background: var(--surface); transition: border-color .12s, box-shadow .12s; }
.ag-card:hover { border-color: var(--border-2); box-shadow: 0 4px 16px rgba(20, 20, 30, .06); }
.ag-card.dim { opacity: .62; }
.ag-card.expanded { grid-column: 1 / -1; }
.ag-card-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ag-card-title { font-size: 13.5px; font-weight: 600; color: var(--text); flex: 1 1 auto; min-width: 0; }
.ag-card-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 11px; color: var(--text-3); }
.ag-card-desc { font-size: 12.5px; line-height: 1.5; color: var(--text-2); display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.ag-card-desc.full { display: block; -webkit-line-clamp: unset; }
.ag-card-foot { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: auto; padding-top: 4px; }
.ag-installed { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 600; color: var(--green); }
.ag-details-btn { color: var(--text-3); }
.ag-details-btn:hover { color: var(--text); }
.ag-details-btn svg { transition: transform .15s ease; }
.ag-card-detail { border-top: 1px solid var(--border); padding-top: 10px; display: flex; flex-direction: column; gap: 10px; font-size: 12.5px; color: var(--text-2); line-height: 1.5; }
.ag-detail-row .jv-skill-l { margin-bottom: 3px; }
.ag-tools { display: flex; gap: 5px; flex-wrap: wrap; }
.ag-tool { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 10.5px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; padding: 2px 6px; color: var(--text-2); }

/* chips — same vocabulary as the chat surfaces */
.ag-chip { font-size: 10px; font-weight: 600; border-radius: 7px; padding: 2.5px 7px; flex: none; white-space: nowrap; }
.ag-chip.mono { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-weight: 500; }
.ag-chip--auditor { background: rgba(88, 101, 242, .14); color: var(--blue); }
.ag-chip--operator { background: rgba(48, 164, 108, .14); color: var(--green); }
.ag-chip--green { background: rgba(48, 164, 108, .12); color: var(--green); }
.ag-chip--red { background: rgba(229, 72, 77, .12); color: var(--red); }
.ag-chip--amber { background: rgba(245, 158, 11, .14); color: var(--amber); }
.ag-chip--muted { background: var(--surface-2); color: var(--text-2); }
.ag-chip--domain { background: var(--blue-bg); color: var(--text-2); border: 1px solid var(--blue-bd); }

/* lock note */
.ag-lock { display: flex; align-items: flex-start; gap: 7px; font-size: 11.5px; line-height: 1.45; color: var(--text-2); background: var(--surface-1); border: 1px dashed var(--border-2); border-radius: 8px; padding: 7px 9px; }
.ag-lock svg { flex: none; margin-top: 1px; color: var(--text-3); }

/* empty states */
.ag-empty { display: flex; flex-direction: column; align-items: center; gap: 4px; text-align: center; padding: 34px 16px; font-size: 12.5px; color: var(--text-3); }
.ag-empty b { color: var(--text-2); font-weight: 600; }

/* ── mine: installed agent rows ── */
.ag-inst { border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; margin-bottom: 12px; background: var(--surface); }
.ag-inst-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ag-enable { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text-2); cursor: default; }
.ag-inst-body { display: flex; gap: 22px; flex-wrap: wrap; margin-top: 12px; border-top: 1px solid var(--border); padding-top: 12px; }
.ag-inst-col { flex: 1 1 260px; min-width: 230px; }
.ag-inst-col-title { font-size: 12px; font-weight: 600; color: var(--text); margin-bottom: 8px; }
.ag-fields { display: flex; gap: 10px; }
.ag-fields > div { flex: 1; min-width: 0; }
.ag-inst-actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 12px; }

/* sticky apply bar */
.ag-applybar { position: sticky; bottom: 12px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 16px; padding: 10px 14px; background: var(--surface); border: 1px solid var(--border-2); border-radius: 12px; box-shadow: 0 10px 30px rgba(20, 20, 30, .14); }
.ag-applypill { display: inline-flex; align-items: center; gap: 7px; font-size: 11.5px; font-weight: 550; color: var(--text-2); flex: none; }
.ag-applypill.err { color: var(--red); }
.ag-applypill.ok { color: var(--green); }
.ag-applycopy { flex: 1 1 260px; min-width: 200px; font-size: 11.5px; color: var(--text-3); }
.ag-dot { width: 7px; height: 7px; border-radius: 99px; background: var(--text-3); flex: none; }
.ag-dot.ok { background: var(--green); }
.ag-dot.err { background: var(--red); }
.ag-dot.spin { border: 2px solid var(--border-2); border-top-color: var(--blue); background: transparent; width: 11px; height: 11px; animation: ag-spin .7s linear infinite; }
@keyframes ag-spin { to { transform: rotate(360deg); } }

/* ── activity ── */
.ag-activity { display: grid; grid-template-columns: minmax(0, 5fr) minmax(0, 7fr); gap: 26px; }
@media (max-width: 860px) { .ag-activity { grid-template-columns: 1fr; } }
.ag-run { display: flex; gap: 9px; align-items: flex-start; border: 1px solid var(--border); border-radius: 10px; padding: 9px 11px; margin-bottom: 7px; background: var(--surface); }
.ag-run-main { flex: 1; min-width: 0; }
.ag-run-title { font-size: 12.5px; font-weight: 600; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ag-run-trigger { color: var(--text-3); font-weight: 450; font-size: 11.5px; }
.ag-run-sub { display: flex; gap: 10px; flex-wrap: wrap; font-size: 11px; color: var(--text-3); margin-top: 2px; }
.ag-blockers { color: var(--red); font-weight: 600; }
.ag-run-note { font-size: 11px; color: var(--amber); margin-top: 3px; }
.ag-run-err { font-size: 11px; color: var(--red); margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ag-run-link { flex: none; font-size: 11.5px; font-weight: 550; color: var(--blue); text-decoration: none; border-bottom: 1px dashed var(--blue); align-self: center; }
.ag-sevhead { display: flex; align-items: center; gap: 6px; margin: 12px 0 7px; }
.ag-sevhead .ag-chip { text-transform: uppercase; letter-spacing: .05em; }
.ag-sevcount { font-size: 11px; color: var(--text-3); }
.ag-finding { border: 1px solid var(--border); border-radius: 10px; padding: 11px 13px; margin-bottom: 8px; background: var(--surface); }
.ag-finding.resolved { opacity: .6; }
.ag-finding-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ag-finding-title { font-size: 12.5px; font-weight: 600; color: var(--text); flex: 1 1 auto; min-width: 0; }
.ag-finding-detail { font-size: 12px; line-height: 1.5; color: var(--text-2); margin: 5px 0; white-space: pre-wrap; }
.ag-finding-ref { font-size: 11px; color: var(--text-3); margin-bottom: 2px; }
.ag-statutory { font-size: 10.5px; color: var(--text-2); background: var(--blue-bg); border: 1px solid var(--blue-bd); border-left-width: 3px; border-radius: 7px; padding: 7px 9px; margin: 7px 0; line-height: 1.5; }
.ag-finding-actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 7px; }

/* ── admin ── */
.ag-admin-note { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; line-height: 1.5; color: var(--text-2); background: var(--blue-bg); border: 1px solid var(--blue-bd); border-radius: 9px; padding: 9px 12px; margin-bottom: 16px; }
.ag-admin-note svg { flex: none; margin-top: 2px; color: var(--text-3); }
.ag-status-sel { width: auto; flex: none; height: 32px; padding: 0 8px; font-size: 12px; }
.ag-roles { margin-top: 12px; border-top: 1px solid var(--border); padding-top: 12px; }
.ag-roles-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 4px 14px; }
.ag-role { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--text-2); padding: 3px 0; cursor: pointer; }
.ag-role input { accent-color: var(--blue); width: 14px; height: 14px; flex: none; cursor: pointer; }
.ag-roles-save { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.ag-table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 9px; }
.ag-table { border-collapse: collapse; width: 100%; min-width: 560px; font-size: 12px; }
.ag-table th { text-align: left; font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); background: var(--surface-1); padding: 7px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
.ag-table td { padding: 7px 10px; border-bottom: 1px solid var(--border); color: var(--text-2); white-space: nowrap; }
.ag-table tbody tr:last-child td { border-bottom: 0; }

/* ── shared jv- vocabulary (mirrors ChatView's scoped styles) ── */
.jv-btn { flex: none; display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 34px; padding: 0 15px; border-radius: 10px; border: 1px solid transparent; background: transparent; font-family: inherit; font-size: 12.5px; font-weight: 600; line-height: 1; white-space: nowrap; cursor: pointer; user-select: none; color: var(--text-2); text-decoration: none; transition: background .15s ease, color .15s ease, border-color .15s ease, box-shadow .15s ease, transform .12s ease; }
.jv-btn:disabled { opacity: .55; cursor: default; }
.jv-btn:not(.jv-btn--primary):not(.jv-btn--danger):not(.jv-btn--ghost):hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
.jv-btn--primary { background: var(--blue); border-color: var(--blue); color: #fff; box-shadow: 0 1px 2px rgba(20, 20, 30, .12); }
.jv-btn--primary:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(20, 20, 30, .18); }
.jv-btn--primary svg { stroke: #fff; }
.jv-btn--ghost { background: var(--surface); border-color: var(--border-2); color: var(--text-2); }
.jv-btn--ghost:hover:not(:disabled) { background: var(--surface-2); border-color: var(--border); color: var(--text); transform: translateY(-1px); }
.jv-btn--danger { background: var(--red); border-color: var(--red); color: #fff; box-shadow: 0 1px 2px rgba(220, 38, 38, .14); }
.jv-btn--danger:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(220, 38, 38, .24); }
.jv-btn--sm { height: 32px; padding: 0 12px; font-size: 12px; border-radius: 9px; }
.jv-btn--icon { width: 32px; height: 32px; padding: 0; border-radius: 9px; color: var(--text-3); }
.jv-btn--icon:hover { background: var(--surface-2); color: var(--text); transform: none; }
.jv-skill-l { display: block; font-size: 11px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; margin: 0 0 4px; }
.jv-skill-in { width: 100%; box-sizing: border-box; padding: 8px 10px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; font-family: inherit; font-size: 13px; color: var(--text); outline: none; }
.jv-skill-in:focus { border-color: var(--blue); }
.jv-skill-err { font-size: 12px; color: var(--red); background: var(--red-bg); border: 1px solid var(--red-bd); border-radius: 7px; padding: 7px 10px; margin-bottom: 10px; }
.jv-switch { width: 38px; height: 22px; flex: none; border: none; border-radius: 11px; background: var(--surface-3); position: relative; cursor: pointer; padding: 0; transition: background .15s; }
.jv-switch.on { background: var(--green); }
.jv-switch-knob { position: absolute; top: 2px; left: 2px; width: 18px; height: 18px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(0, 0, 0, .25); transition: left .15s; }
.jv-switch.on .jv-switch-knob { left: 18px; }
/* toasts */
.jv-notes { position: absolute; top: 16px; left: 50%; transform: translateX(-50%); z-index: 90; display: flex; flex-direction: column; gap: 8px; align-items: center; pointer-events: none; }
.jv-note { pointer-events: auto; display: flex; align-items: center; gap: 10px; min-width: 220px; max-width: 400px; padding: 10px 12px; background: var(--surface); border: 1px solid var(--border-2); border-radius: 11px; box-shadow: 0 10px 30px rgba(20, 20, 30, .18); }
.jv-note-ic { flex: none; width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: #fff; }
.jv-note.success .jv-note-ic { background: var(--green); }
.jv-note.error .jv-note-ic { background: var(--red); }
.jv-note.info .jv-note-ic { background: var(--blue); }
.jv-note-msg { font-size: 13px; color: var(--text); min-width: 0; flex: 1; }
.jv-note-x { flex: none; width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; background: transparent; border: none; border-radius: 6px; color: var(--text-3); cursor: pointer; }
.jv-note-x:hover { background: var(--surface-2); color: var(--text); }
.jv-note-enter-active, .jv-note-leave-active { transition: opacity .18s ease, transform .18s ease; }
.jv-note-enter-from, .jv-note-leave-to { opacity: 0; transform: translateY(-8px); }
/* confirm dialog */
.ag-overlay { position: absolute; inset: 0; z-index: 62; background: rgba(15, 15, 22, .34); display: flex; align-items: center; justify-content: center; padding: 24px; }
.jv-dark .ag-overlay { background: rgba(0, 0, 0, .55); }
.jv-cdialog { width: 400px; max-width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 20px; box-shadow: 0 24px 70px rgba(20, 20, 30, .28); animation: ag-popin .16s ease; }
.jv-cdialog-title { font-size: 16px; font-weight: 650; color: var(--text); }
.jv-cdialog-msg { margin-top: 8px; font-size: 13.5px; line-height: 1.5; color: var(--text-2); }
.jv-cdialog-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
@keyframes ag-popin { from { transform: scale(.97); opacity: 0; } to { transform: scale(1); opacity: 1; } }
.jv-fade-enter-active, .jv-fade-leave-active { transition: opacity .16s ease; }
.jv-fade-enter-from, .jv-fade-leave-to { opacity: 0; }

/* narrow screens */
@media (max-width: 640px) {
	.ag-head-in { padding: 16px 16px 0; }
	.ag-content { padding: 16px 16px 32px; }
	.ag-tabs { overflow-x: auto; }
	.ag-inst-body { gap: 14px; }
}
</style>
