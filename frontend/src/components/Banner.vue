<!--
  Reusable inline banner (approved design: error-toast-system-preview.html,
  section 2 "Inline banner - contextual, actionable errors"). Sits in a fixed
  slot on a screen (a form step, a blocked action) instead of loose colored
  text. Icon tile + title/message body + an optional #action slot for a
  Retry-style button. Ported from the preview's .banner / .banner.error /
  .banner.warning CSS; .banner.info / .banner.success extrapolated from the
  same file's .toast.info / .toast.success color pairing (the preview only
  demoed error + warning banners, but all four states share the toast
  palette).
-->
<template>
	<div class="jv-banner" :class="`jv-banner--${type}`">
		<span class="jv-banner-ic" aria-hidden="true">
			<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
				 :stroke-width="type === 'success' ? 2.6 : 2" stroke-linecap="round" stroke-linejoin="round">
				<template v-if="type === 'error'">
					<circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16h.01" />
				</template>
				<template v-else-if="type === 'warning'">
					<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h16.9a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4M12 17h.01" />
				</template>
				<template v-else-if="type === 'success'">
					<path d="M20 6 9 17l-5-5" />
				</template>
				<template v-else>
					<circle cx="12" cy="12" r="9" /><path d="M12 16v-5M12 8h.01" />
				</template>
			</svg>
		</span>
		<div class="jv-banner-bd">
			<template v-if="title">
				<div class="jv-banner-tt">{{ title }}</div>
				<div v-if="message" class="jv-banner-ms">{{ message }}</div>
			</template>
			<!-- No title: the message reads as the primary line so a message-only
				 banner (the common case here) doesn't look like a blank card with a
				 muted second line. -->
			<div v-else class="jv-banner-tt">{{ message }}</div>
			<!-- Optional extra body (hint line, a details expander): renders nothing
				 when no default slot is passed, so existing message-only callers are
				 unaffected. -->
			<slot />
		</div>
		<div v-if="$slots.action" class="jv-banner-act">
			<slot name="action" />
		</div>
	</div>
</template>

<script setup>
defineProps({
	type: { type: String, default: "error" }, // error | warning | info | success
	title: { type: String, default: "" },
	message: { type: String, default: "" },
})
</script>

<style scoped>
.jv-banner {
	display: flex;
	gap: 11px;
	align-items: flex-start;
	border-radius: 11px;
	padding: 11px 13px;
	animation: jv-banner-in .25s ease;
}
@keyframes jv-banner-in {
	from { opacity: 0; transform: translateY(-4px); }
	to { opacity: 1; transform: none; }
}
.jv-banner-ic { width: 26px; height: 26px; border-radius: 8px; flex: none; display: grid; place-items: center; }
.jv-banner-bd { flex: 1; min-width: 0; }
.jv-banner-tt { font-size: 13px; font-weight: 600; line-height: 1.3; }
.jv-banner-ms { font-size: 12.5px; color: var(--text-2); line-height: 1.5; margin-top: 2px; }
.jv-banner-act { flex: none; display: flex; gap: 8px; align-items: center; margin-top: 1px; }

.jv-banner--error { background: var(--red-bg); border: 1px solid var(--red-bd); }
.jv-banner--error .jv-banner-ic { background: var(--surface); color: var(--red); border: 1px solid var(--red-bd); }
.jv-banner--error .jv-banner-tt { color: var(--red); }

.jv-banner--warning { background: var(--amber-bg); border: 1px solid var(--amber-bd); }
.jv-banner--warning .jv-banner-ic { background: var(--surface); color: var(--amber); border: 1px solid var(--amber-bd); }
.jv-banner--warning .jv-banner-tt { color: var(--amber); }

/* The app palette has no dedicated --info token (only --blue, which doubles
   as the near-black primary-button color in light mode) - fall back to the
   preview's own info blue so the banner still reads as "informational"
   rather than "black/disabled" if --info is ever added upstream, this picks
   it up for free. */
.jv-banner--info { background: var(--blue-bg); border: 1px solid var(--blue-bd); }
.jv-banner--info .jv-banner-ic { background: var(--surface); color: var(--info, #6e8bff); border: 1px solid var(--blue-bd); }
.jv-banner--info .jv-banner-tt { color: var(--info, #6e8bff); }

.jv-banner--success { background: var(--green-bg); border: 1px solid var(--green-bd); }
.jv-banner--success .jv-banner-ic { background: var(--surface); color: var(--green); border: 1px solid var(--green-bd); }
.jv-banner--success .jv-banner-tt { color: var(--green); }

@media (prefers-reduced-motion: reduce) {
	.jv-banner { animation: none; }
}
</style>
