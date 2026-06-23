import { createApp } from "vue"
import { setConfig, frappeRequest, resourcesPlugin } from "frappe-ui"

import App from "./App.vue"
import router from "./router"
import { initSocket } from "./socket"
import { session, requireLogin } from "./data/session"
import "./main.css"

// Bounce to Frappe login if there's no session (cookie) — same auth as Desk.
requireLogin()

setConfig("resourceFetcher", frappeRequest)

const app = createApp(App)
app.use(resourcesPlugin)
app.use(router)

// `?nosocket` skips the realtime connection — handy for headless screenshots,
// where an open websocket otherwise keeps the page from ever going idle.
const socket = window.location.search.includes("nosocket") ? null : initSocket()
app.provide("$socket", socket)
app.provide("$session", session)

app.mount("#app")
