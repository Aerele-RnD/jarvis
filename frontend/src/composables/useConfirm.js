import { ref } from "vue"

// App-wide confirmation dialog — a promise-based, drop-in replacement for the
// native window.confirm(). A SINGLE <ConfirmDialog> mounted in the app shell
// (components/shell/ConfirmDialog.vue) renders from this shared state, so any
// component can:
//
//   import { useConfirm } from "@/composables/useConfirm"
//   const { confirm } = useConfirm()
//   if (await confirm({ title: "Remove model?", message: "…", danger: true,
//                       confirmLabel: "Remove" })) { …destructive action… }
//
// confirm() resolves true when the user confirms and false on Cancel / backdrop
// click / Escape. This was extracted from ChatView's former inline confirmDialog
// so there is one implementation, not several.

// The live request, or null when no dialog is open. The mounted ConfirmDialog is
// the only reader; call sites never touch it directly.
export const confirmState = ref(null) // { title, message, confirmLabel, cancelLabel, danger }
let _resolve = null

export function confirm(opts = {}) {
  // Only one dialog can be open at a time. If a second confirm() arrives while one
  // is live, resolve the previous as cancelled so its awaiter never hangs.
  if (_resolve) { const prev = _resolve; _resolve = null; prev(false) }
  return new Promise((resolve) => {
    _resolve = resolve
    confirmState.value = {
      title: opts.title || "Are you sure?",
      message: opts.message || "",
      confirmLabel: opts.confirmLabel || "Confirm",
      cancelLabel: opts.cancelLabel || "Cancel",
      // General-purpose: neutral (primary) by default. Destructive call sites opt
      // in with danger:true to get the red confirm button.
      danger: opts.danger === true,
    }
  })
}

// Called by <ConfirmDialog> when the user resolves the dialog (button, backdrop,
// or Escape). Safe to call when nothing is open.
export function settleConfirm(val) {
  confirmState.value = null
  const r = _resolve
  _resolve = null
  if (r) r(val)
}

export function useConfirm() {
  return { confirm }
}
