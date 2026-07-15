<script setup>
import { ref } from "vue"
import BrandMark from "../components/BrandMark.vue"
import { call } from "frappe-ui"

// The app's own sign-in, inside the PWA's scope.
//
// Without it, a logged-out visit redirected to the Desk's /login — outside the
// manifest scope, which an installed PWA hands off to the browser. The user
// taps the Jarvis icon and lands in a Chrome tab. Signing in here keeps them in
// the app, which is the whole point of installing it.
const email = ref("")
const password = ref("")
const busy = ref(false)
const error = ref("")

async function submit() {
	if (busy.value || !email.value.trim() || !password.value) return
	busy.value = true
	error.value = ""
	try {
		const r = await call("login", { usr: email.value.trim(), pwd: password.value })

		// Two-factor is a multi-step flow (tmp_id + OTP) this screen doesn't
		// implement. Say so plainly instead of leaving the user on a form that
		// will never succeed.
		if (r?.verification || r?.tmp_id) {
			error.value = "This account uses two-factor sign-in. Please sign in on the web first."
			busy.value = false
			return
		}

		// A full navigation, not a router push: the CSRF token is bound to the
		// session, and logging in mints a NEW session. The token this page was
		// rendered with died with the guest session, so every write after an
		// in-page transition would fail CSRF. Reloading re-renders the shell with
		// the new session's token — and it stays inside /jarvis-mobile, so an
		// installed app never leaves itself.
		window.location.href = "/jarvis-mobile"
	} catch (e) {
		// Frappe throws AuthenticationError (401) for bad credentials; anything
		// else is worth showing verbatim rather than flattening to "login failed".
		const msg = String(e?.message || e || "")
		error.value = /auth|password|incorrect|invalid login/i.test(msg)
			? "That email or password isn't right."
			: msg || "Couldn't sign in. Try again."
		busy.value = false
	}
}
</script>

<template>
	<div class="jv-login jv-safe-bottom">
		<div class="jv-login-head">
			<BrandMark :size="56" />
			<h1>Jarvis</h1>
			<p>Your AI teammate. Sign in to pick up where you left off.</p>
		</div>

		<form class="jv-login-form" @submit.prevent="submit">
			<label>
				<span>Email</span>
				<input
					v-model="email"
					type="email"
					name="email"
					autocomplete="username"
					inputmode="email"
					autocapitalize="none"
					autocorrect="off"
					placeholder="you@company.com"
					required
				/>
			</label>

			<label>
				<span>Password</span>
				<input
					v-model="password"
					type="password"
					name="password"
					autocomplete="current-password"
					placeholder="••••••••"
					required
				/>
			</label>

			<div v-if="error" class="jv-login-error">{{ error }}</div>

			<button class="jv-login-btn" type="submit" :disabled="busy || !email.trim() || !password">
				<span v-if="busy" class="jv-spinner" />
				<span v-else>Sign in</span>
			</button>
		</form>

		<!-- Password reset is a Desk flow and lives outside the PWA scope, so it is
		     a plain link: an installed app opens it in the browser deliberately,
		     rather than appearing to break. -->
		<a class="jv-login-alt" href="/login#forgot">Forgot your password?</a>
	</div>
</template>

<style scoped>
.jv-login {
	flex: 1;
	min-height: 0;
	overflow-y: auto;
	display: flex;
	flex-direction: column;
	justify-content: center;
	gap: 22px;
	padding: 32px 24px;
}
.jv-login-head {
	display: flex;
	flex-direction: column;
	align-items: center;
	gap: 10px;
	text-align: center;
}
.jv-login-head h1 {
	margin: 4px 0 0;
	font-size: 24px;
	font-weight: 600;
	letter-spacing: -0.3px;
	color: var(--ink9);
}
.jv-login-head p {
	margin: 0;
	max-width: 280px;
	font-size: 14px;
	line-height: 1.5;
	color: var(--ink5);
}
.jv-login-form {
	display: flex;
	flex-direction: column;
	gap: 14px;
}
.jv-login-form label {
	display: flex;
	flex-direction: column;
	gap: 6px;
}
.jv-login-form span {
	font-size: 13px;
	font-weight: 500;
	color: var(--ink7);
}
.jv-login-form input {
	height: 48px;
	padding: 0 14px;
	border: 1px solid var(--border2);
	border-radius: 12px;
	background: var(--card);
	color: var(--ink9);
	font: inherit;
	font-size: 15px;
	outline: none;
}
.jv-login-form input:focus {
	border-color: var(--accent);
}
.jv-login-error {
	padding: 11px 12px;
	border-radius: 10px;
	background: var(--red-bg);
	color: var(--red);
	font-size: 13px;
	line-height: 1.4;
}
.jv-login-btn {
	display: grid;
	place-items: center;
	height: 50px;
	margin-top: 2px;
	border: 0;
	border-radius: 12px;
	background: var(--accent-solid);
	color: #fff;
	font: inherit;
	font-size: 15px;
	font-weight: 600;
	cursor: pointer;
}
.jv-login-btn:disabled {
	opacity: 0.55;
	cursor: default;
}
.jv-login-alt {
	align-self: center;
	font-size: 13px;
	color: var(--ink5);
	text-decoration: none;
}
.jv-spinner {
	width: 18px;
	height: 18px;
	border-radius: 50%;
	border: 2px solid rgba(255, 255, 255, 0.35);
	border-top-color: #fff;
	animation: jv-spin 0.7s linear infinite;
}
@keyframes jv-spin {
	to {
		transform: rotate(360deg);
	}
}
</style>
