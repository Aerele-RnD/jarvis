<template>
	<!-- Draggable, edge-snapping Jarvis shortcut FAB, floating on every ERP Desk
	     page. Tapping it navigates to the Jarvis chat SPA (a fresh conversation)
	     rather than opening an in-page panel. -->
	<div class="jvw-root">
		<button
			type="button"
			ref="fabEl"
			class="jvw-fab"
			:class="{ 'jvw-fab--snapping': snapping, 'jvw-fab--dragging': dragging, 'jvw-fab--faded': faded && !dragging }"
			:style="fabStyle"
			title="Ask Jarvis"
			aria-label="Ask Jarvis"
			@click="onFabClick"
			@pointerdown="onPointerDown"
			@pointermove="onPointerMove"
			@pointerup="onPointerUp"
			@pointercancel="onPointerCancel"
			@pointerenter="wake"
			@focus="wake"
		>
			<svg viewBox="0 0 24 24" width="24" height="24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg>
		</button>
	</div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import { NEW_CHAT_URL } from "./config.mjs";
import * as fabPos from "./fab_position.mjs";

// ---- FAB: draggable, edge-snapping, idle-fading launcher button.
// fab_position.mjs owns the pure geometry/drag/idle-timer math (unit tested);
// this component only owns the DOM refs, localStorage and pointer events. ----
const fabEl = ref(null);
const side = ref("right");
const yRatio = ref(1);
const fabXY = ref({ x: 0, y: 0 });
const dragging = ref(false);
const snapping = ref(false);
const faded = ref(false);

let dragSession = null;
let suppressClick = false;
let idleTimer = null;
let snapTimeoutHandle = null;

// Access gate: desk boot sets this once for the session (see Task B).
const hasAccess = Boolean(window.frappe?.boot?.jarvis_has_access);

const fabStyle = computed(() => ({
	transform: `translate3d(${fabXY.value.x}px, ${fabXY.value.y}px, 0)`,
}));

function readCssPx(el, prop, fallback) {
	if (!el) return fallback;
	const n = parseFloat(getComputedStyle(el).getPropertyValue(prop));
	return Number.isFinite(n) ? n : fallback;
}

function getViewport() {
	const topInset = readCssPx(document.documentElement, "--navbar-height", 48) + 8;
	// --jvw-safe-bottom is declared on .jvw-root (env(safe-area-inset-bottom, 0px));
	// read it off the FAB itself since it lives inside .jvw-root and inherits it.
	const safeBottom = readCssPx(fabEl.value, "--jvw-safe-bottom", 0);
	return {
		vw: window.innerWidth,
		vh: window.innerHeight,
		topInset,
		bottomInset: 22 + safeBottom,
		edgeInset: fabPos.EDGE_INSET,
		fabSize: fabPos.FAB_SIZE,
	};
}

// Renders the persisted side/ratio dock spot. animate:true flips on the CSS
// snap transition for SNAP_MS, then clears it.
function applyPosition({ animate = false } = {}) {
	const vp = getViewport();
	fabXY.value = {
		x: fabPos.xForSide(side.value, vp),
		y: fabPos.ratioToY(yRatio.value, vp),
	};
	if (snapTimeoutHandle) {
		window.clearTimeout(snapTimeoutHandle);
		snapTimeoutHandle = null;
	}
	if (animate) {
		snapping.value = true;
		snapTimeoutHandle = window.setTimeout(() => {
			snapping.value = false;
			snapTimeoutHandle = null;
		}, fabPos.SNAP_MS);
	} else {
		snapping.value = false;
	}
}

// Setup-time init (synchronous — no flash): resolve the persisted dock spot
// from localStorage before the first render so the FAB never jumps from a
// default position to the saved one.
{
	let savedRaw = null;
	try {
		savedRaw = localStorage.getItem(fabPos.STORAGE_KEY);
	} catch (e) {
		savedRaw = null;
	}
	const resolved = fabPos.resolvePosition(fabPos.parseSavedPosition(savedRaw), getViewport());
	side.value = resolved.side;
	yRatio.value = resolved.yRatio;
	applyPosition({ animate: false });
}

function wake() {
	faded.value = false;
	idleTimer?.poke();
}

// Document-level activity also counts as "not idle": today the FAB only woke
// on FAB-local pointerenter/focus/pointerdown, so moving the mouse anywhere
// else on the page left it faded and feeling disabled. Throttled to at most
// one poke() per ~1s (mousemove fires far more often than that) — when
// already faded, skip the throttle and restore instantly instead.
let lastActivityPoke = 0;
function onDocumentActivity() {
	if (faded.value) {
		wake();
		return;
	}
	const now = Date.now();
	if (now - lastActivityPoke < 1000) return;
	lastActivityPoke = now;
	idleTimer?.poke();
}

function onPointerDown(e) {
	wake();
	suppressClick = false;
	if (e.button !== 0) return;
	dragSession = fabPos.dragStart(fabXY.value.x, fabXY.value.y, e.clientX, e.clientY);
	fabEl.value?.setPointerCapture?.(e.pointerId);
}

function onPointerMove(e) {
	if (!dragSession) return;
	dragSession = fabPos.dragMove(dragSession, e.clientX, e.clientY, fabPos.TAP_THRESHOLD_PX);
	dragging.value = dragSession.dragging;
	if (!dragSession.dragging) return; // still under the tap threshold
	const vp = getViewport();
	const x = dragSession.startFabX + (e.clientX - dragSession.startPx);
	const y = fabPos.clampY(dragSession.startFabY + (e.clientY - dragSession.startPy), vp);
	fabXY.value = { x, y };
}

function onPointerUp(e) {
	fabEl.value?.releasePointerCapture?.(e.pointerId);
	if (!dragSession) return;
	const vp = getViewport();
	const result = fabPos.dragEnd(dragSession, vp);
	dragSession = null;
	dragging.value = false;
	wake(); // re-arm the idle timer now that the drag (which blocked it) is over
	if (result.tap) return; // native click follows; onFabClick handles it
	suppressClick = true;
	side.value = result.side;
	yRatio.value = result.yRatio;
	try {
		localStorage.setItem(
			fabPos.STORAGE_KEY,
			fabPos.serializePosition({ side: result.side, yRatio: result.yRatio }),
		);
	} catch (e) {
		/* localStorage unavailable */
	}
	applyPosition({ animate: true });
}

function onPointerCancel(e) {
	fabEl.value?.releasePointerCapture?.(e.pointerId);
	if (!dragSession) return;
	dragSession = null;
	dragging.value = false;
	wake(); // re-arm the idle timer now that the drag (which blocked it) is over
	applyPosition({ animate: true }); // revert to the last committed spot
}

function onFabClick() {
	if (suppressClick) {
		suppressClick = false;
		return;
	}
	wake();
	if (!hasAccess) window.location.assign("/jarvis-no-access");
	else window.location.assign(NEW_CHAT_URL);
}

// Re-clamps the FAB into the (possibly resized) dockable band; ratio-based
// storage means this is enough to keep it on-screen after a viewport change.
function onResize() {
	applyPosition({ animate: false });
}

onMounted(() => {
	// Setup-time applyPosition() ran before fabEl was live, so getViewport()
	// couldn't read the real --jvw-safe-bottom off it and fell back to 0. Now
	// that the DOM ref exists, correct the position so notched devices don't
	// keep the pre-mount fallback spot.
	applyPosition({ animate: false });

	idleTimer = fabPos.createIdleTimer({
		delayMs: fabPos.IDLE_FADE_MS,
		onIdle: () => {
			if (!dragging.value) faded.value = true;
		},
	});
	window.addEventListener("resize", onResize);
	window.addEventListener("orientationchange", onResize);
	document.addEventListener("mousemove", onDocumentActivity, { passive: true });
	document.addEventListener("touchstart", onDocumentActivity, { passive: true });
	document.addEventListener("keydown", onDocumentActivity, { passive: true });
});

onBeforeUnmount(() => {
	window.removeEventListener("resize", onResize);
	window.removeEventListener("orientationchange", onResize);
	document.removeEventListener("mousemove", onDocumentActivity);
	document.removeEventListener("touchstart", onDocumentActivity);
	document.removeEventListener("keydown", onDocumentActivity);
	idleTimer?.dispose();
	if (snapTimeoutHandle) {
		window.clearTimeout(snapTimeoutHandle);
		snapTimeoutHandle = null;
	}
});
</script>

<style scoped>
/* Scoped tokens for the FAB (it lives in <body>). */
.jvw-root {
	--accent: #171717;
	--jvw-safe-bottom: env(safe-area-inset-bottom, 0px);
	font-family: "Inter", system-ui, -apple-system, sans-serif;
}

/* Follow the Desk theme. Frappe's theme switcher stamps data-theme="dark" on
   <html>, which is an ancestor of this body-mounted widget: the accent becomes
   the indigo brand blue (the SPA's theme.js DARK_VARS accent) so the FAB stays
   visible against dark surfaces. */
:global([data-theme="dark"]) .jvw-root {
	--accent: #6e8bff;
}

/* ---- launcher bubble ---- */
.jvw-fab {
	width: 54px;
	height: 54px;
	border-radius: 16px;
	background: var(--accent);
	border: none;
	cursor: pointer;
	display: flex;
	align-items: center;
	justify-content: center;
	box-shadow: 0 6px 20px rgba(23, 23, 23, 0.32);
	position: fixed;
	left: 0;
	top: 0;
	z-index: 1121;
	touch-action: none;
	will-change: transform;
	transition: opacity 0.25s ease;
}
.jvw-fab:hover {
	filter: brightness(1.06);
}
.jvw-fab:focus-visible {
	outline: 2px solid var(--accent);
	outline-offset: 3px;
}
.jvw-fab--snapping {
	transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.25s ease;
}
.jvw-fab--dragging {
	transition: none;
	cursor: grabbing;
}
.jvw-fab--faded {
	opacity: 0.4;
}
@media (prefers-reduced-motion: reduce) {
	.jvw-fab,
	.jvw-fab--snapping {
		transition: opacity 0.2s ease;
	}
}
</style>
