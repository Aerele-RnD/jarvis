<script setup>
import { computed } from "vue"
import { useRouter } from "vue-router"

const router = useRouter()

// Boot data the www controller injects (jarvis/www/jarvis_mobile.py) — no
// request needed to know who is signed in.
const user = computed(() => window.frappe_user_id || "")
const fullName = computed(() => window.frappe_full_name || user.value)
const initial = computed(() => (fullName.value || "?").trim().charAt(0).toUpperCase())
</script>

<template>
	<div class="jv-bar">
		<button class="jv-icon-btn" aria-label="Back" @click="router.push('/')">
			<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
				<path d="m15 18-6-6 6-6" />
			</svg>
		</button>
		<div class="jv-title">Account</div>
	</div>

	<div class="jv-scroll">
		<div class="jv-profile">
			<div class="jv-avatar">{{ initial }}</div>
			<div class="jv-name">{{ fullName }}</div>
			<div class="jv-mail">{{ user }}</div>
		</div>

		<!-- Jarvis acts as the signed-in user and inherits exactly their ERPNext
		     permissions — worth stating plainly on the account screen. -->
		<p class="jv-note">
			Jarvis works with your permissions. It can only see and change what you can.
		</p>

		<div class="jv-actions">
			<a class="jv-action" href="/jarvis">Open full workspace</a>
			<a class="jv-action is-danger" href="/api/method/logout">Sign out</a>
		</div>
	</div>
</template>

<style scoped>
.jv-profile {
	display: flex;
	flex-direction: column;
	align-items: center;
	gap: 6px;
	padding: 32px 20px 20px;
}
.jv-avatar {
	width: 64px;
	height: 64px;
	display: grid;
	place-items: center;
	border-radius: 50%;
	background: linear-gradient(140deg, #8b7cf7, #6a56e8);
	color: #fff;
	font-size: 24px;
	font-weight: 600;
	margin-bottom: 6px;
}
.jv-name {
	font-size: 17px;
	font-weight: 600;
	color: var(--ink9);
}
.jv-mail {
	font-size: 13px;
	color: var(--ink5);
}
.jv-note {
	margin: 0 16px 20px;
	padding: 12px 14px;
	border-radius: 10px;
	background: var(--accent-bg);
	color: var(--ink7);
	font-size: 13px;
	line-height: 1.5;
	text-align: center;
}
.jv-actions {
	display: flex;
	flex-direction: column;
	gap: 6px;
	padding: 0 8px 16px;
}
.jv-action {
	display: block;
	padding: 14px 12px;
	border: 1px solid var(--border);
	border-radius: 12px;
	background: var(--card);
	color: var(--ink8);
	font-size: 15px;
	text-align: center;
	text-decoration: none;
}
.jv-action.is-danger {
	color: var(--red);
}
</style>
