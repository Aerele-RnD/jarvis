<template>
	<aside class="jv-app-sidebar" style="width:268px;flex:none;background:var(--surface-1);border-right:1px solid var(--border);display:flex;flex-direction:column;height:100vh;">
		<!-- ============ BRAND ============ -->
		<div style="padding:14px 14px 10px;display:flex;align-items:center;gap:9px;">
			<div class="jv-logo" style="width:28px;height:28px;border-radius:7px;background:var(--blue);display:flex;align-items:center;justify-content:center;flex:none;box-shadow:0 1px 2px rgba(37,99,235,.35);">
				<svg width="16" height="16" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg>
			</div>
			<span style="font-size:14px;font-weight:600;letter-spacing:-.01em;">Jarvis</span>
		</div>

		<!-- ============ NAV ============ -->
		<nav style="padding:6px 12px 10px;display:flex;flex-direction:column;gap:2px;">
			<router-link to="/" class="jv-nav-item" :class="{ on: route.path === '/' || route.path.startsWith('/c/') }">
				<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
				<span>Chat</span>
			</router-link>
			<router-link to="/account" class="jv-nav-item" :class="{ on: route.path.startsWith('/account') }">
				<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
				<span>Account</span>
			</router-link>
		</nav>

		<div style="flex:1;"></div>

		<!-- ============ USER CARD + MENU ============ -->
		<div class="jv-usermenu-wrap" style="position:relative;border-top:1px solid var(--border);">
			<div v-if="userMenuOpen" style="position:absolute;bottom:calc(100% + 6px);left:12px;right:12px;background:var(--surface);border:1px solid var(--border-2);border-radius:10px;box-shadow:0 10px 28px rgba(20,20,30,.16);padding:5px;z-index:20;">
				<button class="jv-menuitem" @click="toggleTheme">
					<svg v-if="effectiveDark" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
					<svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
					<span>Theme: {{ effectiveDark ? "Dark" : "Light" }}</span>
				</button>
				<a class="jv-menuitem" href="/app/jarvis-settings">
					<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
					<span>Settings</span>
				</a>
				<button class="jv-menuitem" @click="goDesk">
					<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /></svg>
					<span>Switch to Desk</span>
				</button>
				<button class="jv-menuitem" @click="session.logout()">
					<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" /></svg>
					<span style="color:var(--red);">Log out</span>
				</button>
			</div>
			<div class="jv-usercard" @click="userMenuOpen = !userMenuOpen" style="padding:10px 12px;display:flex;align-items:center;gap:9px;cursor:pointer;">
				<div style="width:28px;height:28px;border-radius:50%;background:#e7ddcf;color:#8a6d3b;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;flex:none;">{{ initials }}</div>
				<div style="display:flex;flex-direction:column;line-height:1.2;min-width:0;">
					<span style="font-size:12.5px;font-weight:550;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ fullName }}</span>
					<span style="font-size:11px;color:var(--text-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ session.user }}</span>
				</div>
			</div>
		</div>
	</aside>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from "vue"
import { useRoute } from "vue-router"
import { useTheme } from "@/composables/useTheme"
import { session } from "@/data/session"

const route = useRoute()

// Same shared composable ChatView/AccountView use — singleton-backed (see
// useTheme.js) so toggling here re-themes the rest of the page immediately.
const { effectiveDark, toggleTheme } = useTheme()

// Same derivation as ChatView.vue's fullName/initials so both sidebars show
// an identical avatar/name for the same logged-in user.
function cookie(name) {
	return new URLSearchParams(document.cookie.split("; ").join("&")).get(name)
}
const fullName = (cookie("full_name") ? decodeURIComponent(cookie("full_name")) : "") || session.user || "User"
const initials = computed(
	() => fullName.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase() || "U",
)

const userMenuOpen = ref(false)
function goDesk() {
	window.location.assign("/app")
}
function onDocClick(e) {
	if (!e.target.closest(".jv-usermenu-wrap")) userMenuOpen.value = false
}
onMounted(() => document.addEventListener("pointerdown", onDocClick))
onBeforeUnmount(() => document.removeEventListener("pointerdown", onDocClick))
</script>

<style scoped>
.jv-nav-item {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 7px 10px;
	border-radius: 7px;
	font-size: 13px;
	font-weight: 500;
	color: var(--text-2);
	text-decoration: none;
}
.jv-nav-item:hover { background: var(--surface-2); color: var(--text); }
.jv-nav-item.on { background: var(--surface-2); color: var(--text); }

.jv-menuitem {
	display: flex;
	align-items: center;
	gap: 9px;
	width: 100%;
	padding: 7px 9px;
	border: none;
	background: transparent;
	border-radius: 7px;
	font-family: inherit;
	font-size: 12.5px;
	color: var(--text);
	cursor: pointer;
	text-align: left;
	text-decoration: none;
	box-sizing: border-box;
}
.jv-menuitem:hover { background: var(--surface-1); }

.jv-usercard { transition: background 0.12s; }
.jv-usercard:hover { background: var(--surface-2); }

@media (max-width: 768px) {
	.jv-app-sidebar { display: none; }
}
</style>
