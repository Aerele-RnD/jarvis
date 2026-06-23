// Realtime = the SAME Frappe socketio server the Desk uses. The session cookie
// authenticates the socket and joins us to the user's room, so the backend's
// publish_to_user("jarvis:event", ...) frames arrive here unchanged.
import { io } from "socket.io-client"
import { socketio_port } from "../../../../sites/common_site_config.json"

export function initSocket() {
	const host = window.location.hostname
	const siteName = window.site_name || host
	const port = window.location.port ? `:${socketio_port}` : ""
	const protocol = port ? "http" : "https"
	const url = `${protocol}://${host}${port}/${siteName}`
	return io(url, { withCredentials: true, reconnectionAttempts: 5 })
}
