// Shared shell state (DESIGN-V3 §4) - a module-scope singleton, house style
// (no pinia). The shell (Sidebar/UserMenu/palette) and ChatView both consume
// it; write ownership is split by contract:
//   - only ChatView writes currentConvId / streamingConvId
//   - only shell components write paletteOpen / sidebar preference
//   - both sides may call loadConversations (idempotent, in-flight de-duped)
//   - ChatView's socket handlers are the ONLY external writers of
//     `conversations`, and only via applyRemoteRename/applyRemoteNew (DA-04).
import { reactive, ref, computed } from "vue"
import { useStorage } from "@vueuse/core"
import { toast } from "frappe-ui"
import * as api from "@/api"

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

// ---- state ------------------------------------------------------------------
const conversations = ref([]) // [{name,title,last_active_at,starred,message_count}]
const conversationsLoading = ref(false)
const currentConvId = ref(null) // written by ChatView only
const streamingConvId = ref(null) // written by ChatView only
const approvalsCount = ref(0)
const settingsOpen = ref(false) // ChatView binds its settings overlay to this
const pendingNewChat = ref(false) // consumed + cleared by ChatView
const paletteOpen = ref(false)

// Sidebar collapse: persisted preference (same localStorage key/values as
// today - existing prefs survive, D5) + a non-persisted narrow-screen
// override (auto-collapse at ≤820px; manual toggles there are temporary, D8).
const sidebarPref = useStorage("jarvis-sidebar", "open") // 'open' | 'collapsed'
const _narrow = ref(false)
const _narrowOverride = ref(null) // null | 'open' | 'collapsed' (narrow-only, not persisted)
if (typeof window !== "undefined") {
	const mq = window.matchMedia("(max-width: 820px)")
	_narrow.value = mq.matches
	mq.addEventListener("change", (e) => {
		_narrow.value = e.matches
		_narrowOverride.value = null // crossing the breakpoint resets to width-driven default
	})
}
const sidebarCollapsed = computed({
	get() {
		if (_narrow.value) {
			return _narrowOverride.value ? _narrowOverride.value === "collapsed" : true
		}
		return sidebarPref.value === "collapsed"
	},
	set(v) {
		if (_narrow.value) _narrowOverride.value = v ? "collapsed" : "open"
		else sidebarPref.value = v ? "collapsed" : "open"
	},
})

// ---- actions (all errors → toast; never throw to callers) -------------------
let _convsInflight = null
async function loadConversations() {
	if (_convsInflight) return _convsInflight
	conversationsLoading.value = true
	_convsInflight = (async () => {
		try {
			conversations.value = (await api.listConversations()) || []
			refreshApprovalsCount() // poll-on-activity parity (D12)
		} catch (e) {
			toast.error(errMsg(e))
		} finally {
			conversationsLoading.value = false
			_convsInflight = null
		}
	})()
	return _convsInflight
}

// AppShell fires this from four triggers (mount · route change · visibility ·
// 60s interval) that often co-fire; the in-flight de-dupe coalesces them into
// one request, and a hidden tab skips entirely (the visibility trigger
// refreshes on return).
let _approvalsInflight = null
function refreshApprovalsCount() {
	if (typeof document !== "undefined" && document.hidden) return Promise.resolve()
	if (_approvalsInflight) return _approvalsInflight
	_approvalsInflight = (async () => {
		try {
			approvalsCount.value = (await api.approvalsPendingCount()) || 0
		} catch (e) {
			/* badge is best-effort */
		} finally {
			_approvalsInflight = null
		}
	})()
	return _approvalsInflight
}

async function renameConversation(name, title) {
	const conv = conversations.value.find((c) => c.name === name)
	const prev = conv ? conv.title : ""
	if (conv) conv.title = title // optimistic
	try {
		await api.renameConversation(name, title)
	} catch (e) {
		if (conv) conv.title = prev
		toast.error(errMsg(e))
	}
}

async function toggleStar(name) {
	const conv = conversations.value.find((c) => c.name === name)
	if (!conv) return
	const next = conv.starred ? 0 : 1
	conv.starred = next // optimistic - regroups instantly
	try {
		await api.setStar(name, next)
	} catch (e) {
		conv.starred = next ? 0 : 1
		toast.error(errMsg(e))
	}
}

// Confirm is handled by the caller (ConversationRow uses frappe-ui
// confirmDialog). ChatView reacts to the removal via its store watcher.
async function archiveConversation(name) {
	try {
		await api.archiveConversation(name)
		conversations.value = conversations.value.filter((c) => c.name !== name)
		toast.success("Chat deleted")
	} catch (e) {
		toast.error(errMsg(e))
	}
}

// D10 - New Chat from any route: one mechanism for on-chat and cross-route.
function requestNewChat(router) {
	pendingNewChat.value = true
	const name = router.currentRoute.value.name
	if (name !== "Chat" && name !== "Conversation") router.push({ name: "Chat" })
}

// D9 - settings dialog lives inside ChatView; reach it from any route.
function openSettings(router) {
	settingsOpen.value = true
	const name = router.currentRoute.value.name
	if (name !== "Chat" && name !== "Conversation") router.push({ name: "Chat" })
}

// ---- socket contract (§14 DA-04) - called by ChatView's handlers only ------
function applyRemoteRename(name, title) {
	const conv = conversations.value.find((c) => c.name === name)
	if (conv && title) conv.title = title
}

let _remoteNewTimer = null
function applyRemoteNew() {
	if (_remoteNewTimer) return
	_remoteNewTimer = setTimeout(() => {
		_remoteNewTimer = null
		loadConversations()
	}, 500)
}

// reactive() unwraps the refs/computeds, so consumers read and write plain
// properties: `store.pendingNewChat = false`, `watch(() => store.paletteOpen)`.
const store = reactive({
	// state
	conversations,
	conversationsLoading,
	currentConvId,
	streamingConvId,
	approvalsCount,
	settingsOpen,
	pendingNewChat,
	paletteOpen,
	sidebarPref,
	sidebarCollapsed,
	// actions
	loadConversations,
	refreshApprovalsCount,
	renameConversation,
	toggleStar,
	archiveConversation,
	requestNewChat,
	openSettings,
	applyRemoteRename,
	applyRemoteNew,
})

export function useShellStore() {
	return store
}
