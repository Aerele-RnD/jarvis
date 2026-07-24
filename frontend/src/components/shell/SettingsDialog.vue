<template>
	<!-- Hoisted, shell-level settings dialog (DESIGN §Architecture). Owns the
	     scrim, the grouped rail, the header and the active pane. Applies
	     paletteVars + .jv-dark on the root so every jv-* class inside (and in the
	     panes) resolves the shared palette. -->
	<!-- Modal via role="dialog" + aria-modal="true" + a focus trap (Tab
	     cycling, see _onDialogKeydown) + focus return on close — not
	     Teleport/inert. The dialog stays inside #app (AppShell renders it as
	     a normal sibling next to Sidebar/router-view/Dialogs/
	     JarvisCommandPalette/NotifyToaster), so the shell's in-#app
	     <ConfirmDialog> (z-index 200) still stacks above this overlay
	     (z-index 60, settings.css) when a confirm opens on top of
	     settings. -->
	<transition name="jv-fade">
		<div
			v-if="store.settingsOpen"
			class="jv-settings-overlay jv-root"
			:class="{ 'jv-dark': dark }"
			:style="paletteVars"
			@click.self="close"
		>
			<div
				class="jv-settings"
				role="dialog"
				aria-modal="true"
				aria-labelledby="jv-settings-title"
				ref="dialogEl"
				tabindex="-1"
				@keydown="_onDialogKeydown"
			>
				<!-- ===== grouped left rail ===== -->
				<div class="jv-settings-nav">
					<div class="jv-settings-nav-title">Settings</div>

					<!-- WORKSPACE (all users) -->
					<div class="jv-settings-group">Workspace</div>
					<button
						class="jv-settings-navitem"
						:class="{ on: section === 'general' }"
						@click="go('general')"
					>
						<svg
							width="15"
							height="15"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<circle cx="12" cy="12" r="3" />
							<path
								d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"
							/>
						</svg>
						<span>General</span>
					</button>
					<button
						class="jv-settings-navitem"
						:class="{ on: section === 'usage' }"
						@click="go('usage')"
					>
						<svg
							width="15"
							height="15"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<path d="M3 3v18h18" />
							<rect x="7" y="10" width="3" height="7" />
							<rect x="13" y="6" width="3" height="11" />
						</svg>
						<span>Usage</span>
					</button>
					<button
						class="jv-settings-navitem"
						:class="{ on: section === 'activity' }"
						@click="go('activity')"
					>
						<svg
							width="15"
							height="15"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<path d="M22 12h-4l-3 9L9 3l-3 9H2" />
						</svg>
						<span>Activity</span>
					</button>
					<button
						class="jv-settings-navitem"
						:class="{ on: section === 'shortcuts' }"
						@click="go('shortcuts')"
					>
						<svg
							width="15"
							height="15"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<rect x="2" y="4" width="20" height="16" rx="2" />
							<path
								d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M6 12h.01M10 12h.01M14 12h.01M18 12h.01M7 16h10"
							/>
						</svg>
						<span>Shortcuts</span>
					</button>

					<!-- ACCOUNT & BILLING (the tenant-admin tier — System Manager OR
				     Jarvis Admin; PART 4 REVISED TASK 49(c). The rail and the server
				     both gate it (require_jarvis_admin), so no badge is needed) -->
					<template v-if="isSM || isAdmin">
						<div class="jv-settings-group">Account &amp; billing</div>
						<button
							class="jv-settings-navitem"
							:class="{ on: section === 'plan' }"
							@click="go('plan')"
						>
							<svg
								width="15"
								height="15"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<rect x="1" y="4" width="22" height="16" rx="2" />
								<path d="M1 10h22" />
							</svg>
							<span>Plan &amp; billing</span>
						</button>
						<button
							class="jv-settings-navitem"
							:class="{ on: section === 'aimodels' }"
							@click="go('aimodels')"
						>
							<svg
								width="15"
								height="15"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<rect x="4" y="4" width="16" height="16" rx="2" />
								<rect x="9" y="9" width="6" height="6" />
								<path
									d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"
								/>
							</svg>
							<span>AI models</span>
						</button>
						<button
							class="jv-settings-navitem"
							:class="{ on: section === 'connection' }"
							@click="go('connection')"
						>
							<svg
								width="15"
								height="15"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<path d="M5 12.55a11 11 0 0 1 14.08 0" />
								<path d="M1.42 9a16 16 0 0 1 21.16 0" />
								<path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
								<path d="M12 20h.01" />
							</svg>
							<span>Connection</span>
						</button>
						<button
							class="jv-settings-navitem"
							:class="{ on: section === 'billing' }"
							@click="go('billing')"
						>
							<svg
								width="15"
								height="15"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<path d="M12 1v22" />
								<path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
							</svg>
							<span>Billing &amp; metering</span>
						</button>
						<button
							class="jv-settings-navitem"
							:class="{ on: section === 'branding' }"
							@click="go('branding')"
						>
							<svg
								width="15"
								height="15"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<rect x="3" y="3" width="18" height="18" rx="2" />
								<circle cx="8.5" cy="8.5" r="1.5" />
								<path d="M21 15l-5-5L5 21" />
							</svg>
							<span>Branding</span>
						</button>
					</template>

					<!-- ADMINISTRATION (Jarvis Admin role, or System Manager — server
				     re-checks require_jarvis_admin() independently either way) -->
					<template v-if="isAdmin">
						<div class="jv-settings-group">
							Administration<span class="sm-tag">Admin</span>
						</div>
						<button
							class="jv-settings-navitem"
							:class="{ on: section === 'usageadmin' }"
							@click="go('usageadmin')"
						>
							<svg
								width="15"
								height="15"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.7"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
								<circle cx="9" cy="7" r="4" />
								<path d="M23 21v-2a4 4 0 0 0-3-3.87" />
								<path d="M16 3.13a4 4 0 0 1 0 7.75" />
							</svg>
							<span>User usage</span>
						</button>
					</template>
				</div>

				<!-- ===== main ===== -->
				<div class="jv-settings-main">
					<!-- Pane-owned header (design.md §4.1): single title + description;
					     panes render no duplicate heading of their own. -->
					<div class="jv-settings-head">
						<div>
							<div class="jv-settings-head-title" id="jv-settings-title">
								{{ label }}
							</div>
							<div v-if="description" class="jv-settings-head-desc">
								{{ description }}
							</div>
						</div>
						<button
							class="jv-iconbtn"
							@click="close"
							title="Close"
							aria-label="Close settings"
						>
							<svg
								width="16"
								height="16"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<path d="M18 6 6 18M6 6l12 12" />
							</svg>
						</button>
					</div>
					<component :is="pane" />
				</div>
			</div>
		</div>
	</transition>
</template>

<script setup>
import {
	computed,
	defineAsyncComponent,
	onMounted,
	onBeforeUnmount,
	ref,
	watch,
	nextTick,
} from "vue";
import { useJarvisTheme } from "@/theme";
import { useShellStore } from "@/stores/shell";
import "@/assets/settings.css";
import { agentName } from "@/branding";

// Panes are lazy: this dialog is mounted eagerly by AppShell for EVERY user, so
// static imports would pull each pane's dependency tree (charts + usageCharts
// for billing, LlmPoolEditor for AI models) into the initial shell bundle — even
// for non-SM users who can never open those sections. defineAsyncComponent defers
// each pane's code to the first time that section is opened.
const GeneralPane = defineAsyncComponent(() => import("@/components/settings/GeneralPane.vue"));
const UsagePane = defineAsyncComponent(() => import("@/components/settings/UsagePane.vue"));
const ActivityPane = defineAsyncComponent(() => import("@/components/settings/ActivityPane.vue"));
const ShortcutsPane = defineAsyncComponent(() =>
	import("@/components/settings/ShortcutsPane.vue")
);
const PlanBillingPane = defineAsyncComponent(() =>
	import("@/components/settings/PlanBillingPane.vue")
);
const AiModelsPane = defineAsyncComponent(() => import("@/components/settings/AiModelsPane.vue"));
const ConnectionPane = defineAsyncComponent(() =>
	import("@/components/settings/ConnectionPane.vue")
);
const BillingMeteringPane = defineAsyncComponent(() =>
	import("@/components/settings/BillingMeteringPane.vue")
);
const UsageAdminPane = defineAsyncComponent(() =>
	import("@/components/settings/UsageAdminPane.vue")
);
const BrandingPane = defineAsyncComponent(() => import("@/components/settings/BrandingPane.vue"));

// Theme MUST come from the same singleton the header toggle WRITES to
// (@/theme's useJarvisTheme) — @/composables/useTheme is a separate
// module-level singleton that never reconciles same-tab, so reading it would
// leave the dialog stuck in its page-load theme when the user toggles.
const { effectiveDark: dark, paletteVars } = useJarvisTheme();
const store = useShellStore();

// ACCOUNT & BILLING is shown to System Managers; ADMINISTRATION is shown on
// window.is_jarvis_admin (true for System Managers too — see design doc §2).
// This rail is presentation, NOT a security boundary - each endpoint must gate
// itself, because /api/method is reachable directly.
// Server-enforced today: get_account, preview_upgrade, start_upgrade,
// get_llm_usage, get_llm_connection_status, get_llm_config, and the
// user_settings_api admin_* endpoints (require_jarvis_admin).
// Still ungated: onboarding.get_llm_sync_status (OnboardingView needs it before
// roles settle) and oauth.api.get_direct_subscription_status.
const isSM = !!window.is_system_manager;
const isAdmin = !!window.is_jarvis_admin;

const GATED_SM = ["plan", "aimodels", "connection", "billing", "branding"];
const GATED_ADMIN = ["usageadmin"];
const PANES = {
	general: GeneralPane,
	usage: UsagePane,
	activity: ActivityPane,
	shortcuts: ShortcutsPane,
	plan: PlanBillingPane,
	aimodels: AiModelsPane,
	connection: ConnectionPane,
	billing: BillingMeteringPane,
	branding: BrandingPane,
	usageadmin: UsageAdminPane,
};
const LABELS = {
	general: "General",
	usage: "Usage",
	activity: "Activity",
	shortcuts: "Keyboard shortcuts",
	plan: "Plan & billing",
	aimodels: "AI models",
	connection: "Connection",
	billing: "Billing & metering",
	branding: "Branding",
	usageadmin: "User usage",
};
// One-line pane descriptions under the header title (design.md §4.1) —
// presentational only.
const DESCRIPTIONS = {
	general: "Chat behavior, notifications and token usage.",
	usage: "Message and token counts for this device.",
	activity: "Recent tool calls in this chat.",
	shortcuts: "Keyboard shortcuts available in chat.",
	plan: "Your subscription, renewal and upgrade options.",
	aimodels: `The AI connection that powers ${agentName}.`,
	connection: "Connection status for this workspace.",
	billing: "Live usage and cost across the model pool.",
	branding: "Your assistant's name, logo and favicon.",
};

// Guard: a gated section requested by a non-SM/non-admin user falls back to
// General.
const section = computed(() => {
	const s = store.settingsSection;
	if (!PANES[s]) return "general";
	// PART 4 REVISED TASK 49(c): ACCOUNT & BILLING panes are tenant-admin tier
	// (SM OR Jarvis Admin), matching the widened require_jarvis_admin endpoints.
	if (GATED_SM.includes(s) && !(isSM || isAdmin)) return "general";
	if (GATED_ADMIN.includes(s) && !isAdmin) return "general";
	return s;
});
const pane = computed(() => PANES[section.value]);
const label = computed(() => LABELS[section.value]);
const description = computed(() => DESCRIPTIONS[section.value] || "");

function go(key) {
	store.settingsSection = key;
}
function close() {
	store.settingsOpen = false;
}

function onKey(e) {
	if (e.key === "Escape" && store.settingsOpen) {
		e.stopPropagation();
		close();
	}
}
onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));

// Focus trap (P0-5): the dialog is a real modal — Tab must cycle only within
// it while it's open (see the top-of-file comment for why #app is not made
// `inert` here).
const dialogEl = ref(null);
let _returnFocus = null;

function _focusables() {
	if (!dialogEl.value) return [];
	return Array.from(
		dialogEl.value.querySelectorAll(
			'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
		)
	).filter((el) => el.offsetParent !== null);
}

function _onDialogKeydown(e) {
	if (e.key !== "Tab") return;
	const f = _focusables();
	if (!f.length) return;
	const first = f[0],
		last = f[f.length - 1];
	if (e.shiftKey && document.activeElement === first) {
		e.preventDefault();
		last.focus();
	} else if (!e.shiftKey && document.activeElement === last) {
		e.preventDefault();
		first.focus();
	}
}

watch(
	() => store.settingsOpen,
	(open) => {
		if (open) {
			_returnFocus = document.activeElement;
			nextTick(() => {
				(_focusables()[0] || dialogEl.value)?.focus();
			});
		} else {
			if (_returnFocus && _returnFocus.focus) _returnFocus.focus();
			_returnFocus = null;
		}
	}
);
</script>
