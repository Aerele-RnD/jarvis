<template>
	<div class="flex flex-col gap-5">
		<!-- ══════════════ Learn from custom apps ══════════════ -->
		<section class="rounded-lg border p-4">
			<div class="text-base font-semibold text-ink-gray-9">Learn from custom apps</div>
			<div class="mt-0.5 text-sm text-ink-gray-6">
				Teach Jarvis the workflows your custom apps implement. One-time, token-intensive
				analysis; findings are written straight to the Org wiki and can be proposed as
				org-wide skills for your review.
			</div>

			<!-- first load -->
			<div v-if="loading && !loaded" class="flex justify-center py-8">
				<LoadingIndicator class="size-5 text-ink-gray-5" />
			</div>

			<!-- fetch failed before anything rendered: the one error+retry pattern -->
			<template v-else-if="!loaded && loadError">
				<ErrorMessage :message="loadError" class="mt-3" />
				<Button class="mt-2" label="Retry" :loading="loading" @click="loadOverview" />
			</template>

			<!-- empty: no custom apps on this bench -->
			<div
				v-else-if="loaded && !overview.apps.length"
				class="mt-4 flex flex-col items-center gap-1 rounded-lg border border-dashed py-10 text-center"
			>
				<FeatherIcon name="package" class="size-7 text-ink-gray-5" />
				<span class="mt-1 text-base font-medium text-ink-gray-8">
					No custom apps installed on this bench.
				</span>
			</div>

			<template v-else-if="loaded">
				<!-- apps checklist -->
				<div class="mt-4 divide-y rounded-lg border">
					<Tooltip
						v-for="app in overview.apps"
						:key="app.app"
						text="Source not found on this bench"
						:disabled="!!app.path_ok"
					>
						<div
							class="flex items-center gap-3 px-3 py-2.5"
							:class="
								rowDisabled(app)
									? 'cursor-not-allowed opacity-60'
									: 'cursor-pointer hover:bg-surface-gray-1'
							"
							@click="toggle(app)"
						>
							<!-- @click.stop: the checkbox's own toggle must not bubble into
							     the row-click toggle (double flip) -->
							<Checkbox
								:modelValue="selected.has(app.app)"
								:disabled="rowDisabled(app)"
								@update:modelValue="() => toggle(app)"
								@click.stop
							/>
							<div class="min-w-0 flex-1">
								<div class="flex flex-wrap items-baseline gap-x-2">
									<span class="truncate text-base font-medium text-ink-gray-8">
										{{ app.title || app.app }}
									</span>
									<span
										v-if="app.installed_version"
										class="text-sm text-ink-gray-5"
									>
										v{{ app.installed_version }}
									</span>
								</div>
								<div class="mt-0.5 text-sm text-ink-gray-5">
									{{ sizeLine(app) }}
								</div>
							</div>
							<!-- non-terminal run → status chip (checkbox disabled above);
							     otherwise the last run's terminal status, if any -->
							<Badge
								v-if="runningStatus(app)"
								variant="subtle"
								:theme="STATUS_THEME[runningStatus(app)] || 'blue'"
								:label="runningStatus(app)"
							/>
							<Tooltip
								v-else-if="app.last_run"
								:text="
									app.last_run.finished_at
										? exactDate(app.last_run.finished_at)
										: ''
								"
							>
								<Badge
									variant="subtle"
									:theme="STATUS_THEME[app.last_run.status] || 'gray'"
									:label="app.last_run.status"
								/>
							</Tooltip>
						</div>
					</Tooltip>
				</div>

				<!-- schedule: run now | schedule once (option-chip idiom, the
				     TriggerDetail segmented switch) -->
				<div class="mt-4 flex flex-wrap items-end gap-2">
					<div class="flex gap-2">
						<Button
							v-for="mode in SCHEDULE_MODES"
							:key="mode.value"
							:label="mode.label"
							:variant="scheduleMode === mode.value ? 'solid' : 'subtle'"
							:disabled="scheduling"
							@click="scheduleMode = mode.value"
						/>
					</div>
					<FormControl
						v-if="scheduleMode === 'once'"
						type="datetime-local"
						label="Run at"
						class="w-56"
						:modelValue="whenLocal"
						:disabled="scheduling"
						@update:modelValue="(v) => (whenLocal = v)"
					/>
				</div>
				<ErrorMessage v-if="whenError" :message="whenError" class="mt-2" />

				<div class="mt-4 flex flex-wrap items-center gap-2">
					<Button
						variant="solid"
						:label="analyzeLabel"
						:disabled="!canAnalyze"
						:loading="scheduling"
						@click="openConsent"
					/>
				</div>

				<!-- active run strip -->
				<div
					v-if="overview.active_run"
					class="mt-4 flex flex-wrap items-center gap-2 rounded-lg border bg-surface-gray-1 px-3 py-2"
				>
					<LoadingIndicator class="size-4 shrink-0 text-ink-gray-5" />
					<span class="min-w-0 flex-1 truncate text-sm text-ink-gray-7">
						{{ activeLine }}
					</span>
					<span v-if="overview.queued > 0" class="text-sm text-ink-gray-5">
						+{{ overview.queued }} queued
					</span>
					<router-link
						v-if="overview.active_run.conversation"
						:to="'/c/' + overview.active_run.conversation"
						class="text-sm text-ink-blue-link hover:underline"
					>
						View conversation
					</router-link>
					<!-- Ingesting is not cancellable (backend _CANCELLABLE) -->
					<Button
						v-if="overview.active_run.status !== 'Ingesting'"
						variant="ghost"
						label="Cancel"
						:loading="cancelling"
						@click="cancelActive"
					/>
				</div>
				<!-- runs waiting with nothing active yet (e.g. scheduled for later) -->
				<div
					v-else-if="overview.queued > 0"
					class="mt-4 flex items-center gap-2 rounded-lg border bg-surface-gray-1 px-3 py-2 text-sm text-ink-gray-7"
				>
					<FeatherIcon name="clock" class="size-4 shrink-0 text-ink-gray-5" />
					{{ overview.queued }} analysis run{{ overview.queued === 1 ? "" : "s" }}
					queued.
				</div>
			</template>
		</section>

		<!-- ══════════════ Run history ══════════════ -->
		<section class="rounded-lg border pb-1">
			<AppLearningRunsList
				ref="runsList"
				:app-options="appFilterOptions"
				@changed="loadOverview"
			/>
		</section>

		<!-- mandatory consent gate: schedule_app_learning is only ever called
		     from this dialog's confirm (consent: 1) -->
		<AppLearningConsentDialog
			v-model="consent.show"
			:apps="consent.apps"
			:when="consent.when"
			:loading="scheduling"
			@confirm="confirmSchedule"
		/>
	</div>
</template>

<script setup>
// AppLearningCard - the "Learn from custom apps" surface inside AnalysisTab
// (M2). Owns the overview state (apps checklist + schedule + active-run strip
// via get_app_learning_overview), the consent-gated schedule flow, the
// realtime refetch (app_learning:update/done frames on the shared jarvis:event
// socket), and hosts AppLearningRunsList for the run history. Rendering is
// admin/SM-gated by placement: AnalysisTab only mounts for caps.analysis
// viewers (SkillsPage), the same gate the Behavioural-learning settings card
// above rides; every endpoint re-checks manage rights server-side.
import { computed, inject, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import {
	Badge,
	Button,
	Checkbox,
	ErrorMessage,
	FeatherIcon,
	FormControl,
	LoadingIndicator,
	Tooltip,
	confirmDialog,
	toast,
} from "frappe-ui";
import { exactDate, toSiteDatetime } from "@/utils/datetime";
import {
	cancelAppLearningRun,
	getAppLearningOverview,
	scheduleAppLearning,
} from "@/api/appLearning";
import AppLearningConsentDialog from "./AppLearningConsentDialog.vue";
import AppLearningRunsList from "./AppLearningRunsList.vue";

const socket = inject("$socket", null);

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong.";
}

// design.md §3.6 map, matched with the runs list: terminal Completed green /
// Failed red / Cancelled gray; Queued pending-orange; in-flight blue.
const STATUS_THEME = {
	Queued: "orange",
	Zipping: "blue",
	Analyzing: "blue",
	Ingesting: "blue",
	Completed: "green",
	Failed: "red",
	Cancelled: "gray",
};
const TERMINAL = ["Completed", "Failed", "Cancelled"];
const SCHEDULE_MODES = [
	{ label: "Run now", value: "now" },
	{ label: "Schedule once", value: "once" },
];

// ── overview state ───────────────────────────────────────────────────────────
const overview = reactive({ active_run: null, queued: 0, apps: [] });
const loading = ref(false);
const loaded = ref(false);
const loadError = ref("");

const selected = reactive(new Set());

async function loadOverview() {
	loading.value = true;
	try {
		const d = (await getAppLearningOverview()) || {};
		overview.active_run = d.active_run || null;
		overview.queued = d.queued || 0;
		overview.apps = d.apps || [];
		// prune selections that stopped being schedulable (source vanished /
		// a run started for that app meanwhile)
		for (const name of Array.from(selected)) {
			const app = overview.apps.find((a) => a.app === name);
			if (!app || !app.path_ok || runningStatus(app)) selected.delete(name);
		}
		loadError.value = "";
		loaded.value = true;
	} catch (e) {
		// pre-first-paint failures render the inline ErrorMessage + Retry;
		// later refresh failures keep the last-good card and toast instead
		loadError.value = errMsg(e);
		if (loaded.value) toast.error(loadError.value);
	} finally {
		loading.value = false;
	}
}

// ── checklist helpers ────────────────────────────────────────────────────────
// The app's current NON-TERMINAL status, if any: the overview's active run
// wins; otherwise a last_run still in flight (Queued/Zipping/...).
function runningStatus(app) {
	if (overview.active_run && overview.active_run.app === app.app) {
		return overview.active_run.status || "Analyzing";
	}
	const lr = app.last_run;
	if (lr && lr.status && !TERMINAL.includes(lr.status)) return lr.status;
	return "";
}
function rowDisabled(app) {
	return !app.path_ok || !!runningStatus(app) || scheduling.value;
}
function toggle(app) {
	if (rowDisabled(app)) return;
	if (selected.has(app.app)) selected.delete(app.app);
	else selected.add(app.app);
}
function sizeLine(app) {
	const parts = [];
	if (app.approx_files != null) parts.push(`~${app.approx_files} files`);
	if (app.approx_kb != null) parts.push(fmtKb(app.approx_kb));
	return parts.join(" · ") || "Size unknown";
}
function fmtKb(kb) {
	const n = Number(kb) || 0;
	if (n < 1024) return `${Math.round(n)} KB`;
	return `${(n / 1024).toFixed(1)} MB`;
}

// ── schedule state ───────────────────────────────────────────────────────────
const scheduleMode = ref("now");
const whenLocal = ref(""); // <input type="datetime-local"> value, browser-local
const scheduling = ref(false);

// mirrors the server's validation: future only, capped 30 days out
const whenError = computed(() => {
	if (scheduleMode.value !== "once" || !whenLocal.value) return "";
	const t = new Date(whenLocal.value);
	if (t <= new Date()) return "Pick a time in the future.";
	if (t > new Date(Date.now() + 30 * 24 * 60 * 60 * 1000))
		return "Schedule within the next 30 days.";
	return "";
});
const canAnalyze = computed(
	() =>
		selected.size > 0 &&
		!scheduling.value &&
		(scheduleMode.value === "now" || (!!whenLocal.value && !whenError.value))
);
const analyzeLabel = computed(
	() => `Analyze ${selected.size} app${selected.size === 1 ? "" : "s"}`
);

// ── consent → schedule ───────────────────────────────────────────────────────
const consent = reactive({ show: false, apps: [], when: "" });

function openConsent() {
	if (!canAnalyze.value) return;
	// freeze the selection + converted site-tz timestamp at open time so what
	// the dialog shows is exactly what confirm sends
	consent.apps = overview.apps
		.filter((a) => selected.has(a.app))
		.map((a) => ({ app: a.app, title: a.title || a.app }));
	consent.when = scheduleMode.value === "once" ? toSiteDatetime(whenLocal.value) : "";
	consent.show = true;
}

async function confirmSchedule() {
	scheduling.value = true;
	try {
		await scheduleAppLearning(
			consent.apps.map((a) => a.app),
			consent.when
		);
		consent.show = false;
		toast.success(consent.when ? "Analysis scheduled" : "Analysis started");
		selected.clear();
		whenLocal.value = "";
		loadOverview();
		runsList.value && runsList.value.reload();
	} catch (e) {
		// keep the dialog open - the viewer can retry or cancel
		toast.error(errMsg(e));
	} finally {
		scheduling.value = false;
	}
}

// ── active run strip ─────────────────────────────────────────────────────────
const cancelling = ref(false);

const activeLine = computed(() => {
	const r = overview.active_run;
	if (!r) return "";
	if (r.status === "Queued") return `Queued: ${r.app}`;
	if (r.status === "Zipping") return `Zipping ${r.app}`;
	if (r.status === "Ingesting") return `Ingesting findings from ${r.app}`;
	const batches = r.batches_total ? ` - batch ${r.batches_done || 0} of ${r.batches_total}` : "";
	return `Analyzing ${r.app}${batches}`;
});

function cancelActive() {
	const r = overview.active_run;
	if (!r) return;
	confirmDialog({
		title: "Cancel this analysis?",
		message: `Stops the active analysis run for ${r.app}. You can schedule it again later.`,
		onConfirm: async ({ hideDialog }) => {
			cancelling.value = true;
			try {
				await cancelAppLearningRun(r.name);
				hideDialog();
				toast.success("Run cancelled");
				refreshAll();
			} catch (e) {
				toast.error(errMsg(e));
			} finally {
				cancelling.value = false;
			}
		},
	});
}

// ── runs list wiring ─────────────────────────────────────────────────────────
const runsList = ref(null);
const appFilterOptions = computed(() =>
	overview.apps.map((a) => ({ label: a.title || a.app, value: a.app }))
);

function refreshAll() {
	loadOverview();
	runsList.value && runsList.value.reload();
}
// AnalysisTab's header Refresh reaches in through this
defineExpose({ reload: refreshAll });

// ── realtime (app_learning:update / app_learning:done → refetch both) ────────
// Both refetches are non-jarring: loadOverview only shows the spinner before
// first paint (loading && !loaded), and refresh() is the silent keep-window
// refetch - so an :update frame just advances the progress strip + the
// Progress column in place. `update` frames (one per batch advance) are
// trailing-debounced so a burst schedules a single refetch; `done` flushes
// immediately (terminal state should land right away).
let updateTimer = null;
function refreshFromEvent() {
	loadOverview();
	runsList.value && runsList.value.refresh(); // silent window refetch
}
function onEvent(p) {
	if (!p || (p.kind !== "app_learning:update" && p.kind !== "app_learning:done")) return;
	clearTimeout(updateTimer);
	updateTimer = null;
	if (p.kind === "app_learning:done") {
		refreshFromEvent();
		return;
	}
	updateTimer = setTimeout(() => {
		updateTimer = null;
		refreshFromEvent();
	}, 300);
}

onMounted(() => {
	loadOverview();
	socket && socket.on && socket.on("jarvis:event", onEvent);
});
onBeforeUnmount(() => {
	clearTimeout(updateTimer);
	socket && socket.off && socket.off("jarvis:event", onEvent);
});
</script>
