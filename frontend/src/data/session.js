// Auth = the Frappe session cookie (same as Desk). We just read who's logged in;
// if nobody is, the SPA bounces to Frappe's /login with a redirect back.
import { reactive, computed } from "vue"

export function sessionUser() {
	const cookies = new URLSearchParams(document.cookie.split("; ").join("&"))
	let user = cookies.get("user_id")
	if (user === "Guest") user = null
	return user ? decodeURIComponent(user) : null
}

export const session = reactive({
	user: sessionUser(),
	isLoggedIn: computed(() => !!session.user),
	logout() {
		window.location.href = "/api/method/logout"
	},
})

export function requireLogin() {
	if (!session.isLoggedIn) {
		window.location.href = `/login?redirect-to=${encodeURIComponent(
			window.location.pathname,
		)}`
		return false
	}
	return true
}
