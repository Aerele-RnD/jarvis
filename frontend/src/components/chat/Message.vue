<!--
  A single chat/thread message, presentational only — all state and business
  logic (which message is "copied", failed-send retry, edit-and-resend, the
  markdown/HTML renderer) live in the parent. Two variants:
    - "bubble": right-aligned chat user message (implemented here, Task 2 of
      the PR1 extraction — see docs/superpowers/plans/2026-07-24-support-ui-
      pr1-extraction.md).
    - "row": left-aligned assistant/support-agent message with an identity
      line + markdown/HTML body (Task 3; stubbed here so the props/emits
      interface is final and Task 3 only has to fill in the template).
  Shared with the standalone Support page (PR2): a support customer message
  is also variant="bubble"; a support agent reply is variant="row" with a
  round human avatar via the #avatar slot (vs. chat's JarvisMark).
-->
<template>
	<template v-if="variant === 'bubble'">
		<div class="jv-umsg" style="display: flex; flex-direction: column; align-items: flex-end">
			<div
				v-if="text"
				class="jv-ububble"
				style="
					max-width: 78%;
					min-width: 0;
					background: var(--surface-2);
					border: 1px solid var(--border);
					border-radius: 14px 14px 4px 14px;
					padding: 10px 14px;
					font-size: 14px;
					line-height: 1.5;
					color: var(--text);
					white-space: pre-wrap;
					overflow-wrap: anywhere;
				"
			>
				{{ text }}
			</div>
			<div
				v-if="failed"
				style="
					display: flex;
					align-items: center;
					gap: 8px;
					margin-top: 4px;
					font-size: 11.5px;
					color: var(--red);
				"
			>
				<span>Not sent</span>
				<button
					@click="emit('retry')"
					style="
						background: none;
						border: none;
						color: var(--link);
						font: inherit;
						cursor: pointer;
						padding: 0;
						text-decoration: underline;
					"
				>
					Retry
				</button>
			</div>
			<!-- attached images → same clickable thumbnail + preview as generated ones -->
			<template v-for="cv in attachments || []" :key="cv.name">
				<button
					v-if="cv.type === 'image' && cv.file_url"
					class="jv-img-artifact"
					@click="emit('open-attachment', cv)"
					:title="'Open ' + cv.title"
					style="margin-top: 8px; cursor: zoom-in"
				>
					<img :src="cv.file_url" :alt="cv.title" loading="lazy" />
				</button>
			</template>
			<div class="jv-msgbar">
				<!-- sent-time: revealed with the bar on hover; its own hover
				     (native title) gives the full day-date-month-year-time.
				     Order: time → edit → copy (edit before copy). -->
				<span v-if="timestamp" class="jv-msgtime" :title="timestampFull">{{
					timestamp
				}}</span>
				<button
					v-if="editable"
					class="jv-msgbtn"
					@click="emit('edit')"
					title="Edit & resend"
				>
					<svg
						width="14"
						height="14"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.8"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
						<path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
					</svg>
				</button>
				<button
					v-if="copyable"
					class="jv-msgbtn"
					@click="emit('copy')"
					:title="copied ? 'Copied' : 'Copy'"
				>
					<svg
						v-if="copied"
						width="14"
						height="14"
						viewBox="0 0 24 24"
						fill="none"
						stroke="var(--green)"
						stroke-width="2.2"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<path d="M20 6 9 17l-5-5" />
					</svg>
					<svg
						v-else
						width="14"
						height="14"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.8"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<rect x="9" y="9" width="13" height="13" rx="2" />
						<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
					</svg>
				</button>
			</div>
		</div>
	</template>
	<template v-else>
		<!-- variant="row" (assistant / support-agent): implemented in Task 3.
		     Interface (avatar/above-body/below-body slots, html, bodyClass,
		     sender, role) is already final above; only the template is
		     pending. -->
	</template>
</template>

<script setup>
defineProps({
	// 'bubble' (right-aligned chat/support-customer message) | 'row'
	// (left-aligned assistant/support-agent message with identity + body).
	variant: { type: String, default: "bubble" },
	// Pre-rendered, sanitized HTML body for variant="row". Chat passes
	// `render()` + linkify output; support passes DOMPurify'd Helpdesk
	// Communication HTML (with the /files/ → proxy rewrite already applied).
	html: { type: String, default: "" },
	// Which body-style block `html` gets: 'jv-md' (markdown, chat) or
	// 'jv-html' (bare element HTML, support tickets). variant="row" only.
	bodyClass: { type: String, default: "jv-md" },
	// Plain bubble text. variant="bubble" only.
	text: { type: String, default: "" },
	// Canvas/attachment records: { name, type, title, file_url, ... }.
	attachments: { type: Array, default: () => [] },
	// Identity line for variant="row" — sender name + role (support agent).
	sender: { type: String, default: "" },
	role: { type: String, default: "" },
	// Rendered short time (hover bar) and full date/time (native title).
	timestamp: { type: String, default: "" },
	timestampFull: { type: String, default: "" },
	// Show the Edit-and-resend button (chat user bubbles only).
	editable: { type: Boolean, default: false },
	// Show the Copy button.
	copyable: { type: Boolean, default: true },
	// The just-copied tick state (parent owns the "which message" bookkeeping).
	copied: { type: Boolean, default: false },
	// A failed-to-send user message: shows "Not sent" + Retry instead of the
	// hover bar.
	failed: { type: Boolean, default: false },
});

const emit = defineEmits(["edit", "copy", "retry", "open-attachment"]);
</script>

<style scoped>
/* per-message Copy/Edit bar — revealed on hover. Shared with variant="row"
   (Task 3), which reuses this exact rule set once the assistant row moves
   in; ChatView.vue keeps its own copy until that row is extracted, since
   the not-yet-moved assistant message still needs it there too. */
.jv-msgbar {
	display: flex;
	align-items: center;
	gap: 3px;
	margin-top: 0;
	opacity: 0;
	transition: opacity 0.12s ease;
}
.jv-umsg:hover .jv-msgbar {
	opacity: 1;
}
.jv-msgtime {
	font-size: 11.5px;
	color: var(--text-3);
	padding: 0 3px;
	cursor: default;
	user-select: none;
}
.jv-msgbtn {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 26px;
	height: 26px;
	border: none;
	background: transparent;
	border-radius: 6px;
	cursor: pointer;
	color: var(--text-3);
}
.jv-msgbtn:hover {
	background: var(--surface-2);
	color: var(--text);
}
.jv-msgbtn:focus-visible {
	outline: 2px solid var(--cta);
	outline-offset: 2px;
}
/* mobile layout (UX #12): inline styles win over class rules, so this
   overrides with !important, same as ChatView's other mobile overrides. */
@media (max-width: 640px) {
	.jv-ububble {
		max-width: 92% !important;
	}
}
/* touch devices can't hover, so always show per-message actions/timestamps */
@media (hover: none) {
	.jv-msgbar {
		opacity: 1 !important;
	}
}
/* artifact card (in the message) — generated/attached-image thumbnail.
   Shared with the not-yet-extracted assistant canvas loop in ChatView.vue
   (which also renders a caption span there), so only the rules this
   variant="bubble" markup uses (no caption) are duplicated here. */
.jv-img-artifact {
	display: block;
	position: relative;
	margin-top: 12px;
	padding: 0;
	border: 1px solid var(--border);
	border-radius: 12px;
	background: var(--surface-1);
	cursor: zoom-in;
	overflow: hidden;
	max-width: 380px;
	line-height: 0;
}
.jv-img-artifact:hover {
	border-color: var(--border-2);
}
.jv-img-artifact img {
	display: block;
	width: 100%;
	max-height: 320px;
	object-fit: cover;
}
</style>
