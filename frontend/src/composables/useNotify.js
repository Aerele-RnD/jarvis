// useNotify — toast notifications + a promise-based confirm dialog, extracted
// from AgentsView.vue's copies (AgentsView.vue:496-523) so every feature page
// shares one behavior. Module-level singleton state: `notify()` / `confirmDialog()`
// called from anywhere surface in the toasts + dialog that PageShell renders
// (there is only ever one PageShell mounted at a time). Behavior is identical to
// the AgentsView vocabulary — same auto-dismiss timing, same default labels.
import { ref } from "vue"

// ── toasts ──────────────────────────────────────────────────────────────────
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

// ── confirm dialog (promise resolves true/false) ────────────────────────────
const confirmBox = ref(null)
let _confirmResolve = null
function confirmDialog(opts = {}) {
	return new Promise((resolve) => {
		_confirmResolve = resolve
		confirmBox.value = {
			title: opts.title || "Are you sure?",
			message: opts.message || "",
			confirmLabel: opts.confirmLabel || "Confirm",
		}
	})
}
function settleConfirm(val) {
	confirmBox.value = null
	const r = _confirmResolve
	_confirmResolve = null
	if (r) r(val)
}

// ── shared error extractor (same shape as AgentsView.errMsg) ────────────────
function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

export function useNotify() {
	return { notes, notify, dismissNote, confirmBox, confirmDialog, settleConfirm, errMsg }
}
