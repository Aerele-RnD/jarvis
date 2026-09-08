<script setup>
// AnnouncementBanner (PWA): the fleet-wide operator announcement as a soft strip,
// mounted at the app shell (App.vue) next to InstallBanner. Hand-rolled markup -
// the PWA has no reusable Banner.vue - but the same guarantees as the desktop SPA:
// title/body render as PLAIN TEXT via {{ }} (never v-html), and the CTA is
// scheme-gated (isSafeLink) with rel="noopener noreferrer". Dismiss snoozes
// per-device (announcementGate.dismissAnnouncement); the reactive showAnnouncement
// hides it. Visibility (yield to InstallBanner + a signed-out visitor) is the
// caller's v-if in App.vue.
import { bannerToneFor, isSafeLink } from "@shared/announcementNudge";
import { announcement, dismissAnnouncement } from "../announcementGate";

// `announcement` is the stable, non-reactive boot payload, so these are plain
// consts, not computed().
const tone = bannerToneFor(announcement);
const showLink = isSafeLink(announcement.link_url);
</script>

<template>
	<!-- Coloured by severity - accent (Info) or amber (Warning). -->
	<div class="jv-announcementbanner" :class="'jv-tone-' + tone">
		<!-- Tone is conveyed by the icon shape (triangle vs circle) as well as colour,
		     not colour alone. Decorative: the severity is also in the visible prose. -->
		<svg
			v-if="tone === 'warning'"
			class="jv-an-icon"
			aria-hidden="true"
			viewBox="0 0 24 24"
			width="16"
			height="16"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			stroke-linejoin="round"
		>
			<path
				d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
			/>
			<path d="M12 9v4M12 17h.01" />
		</svg>
		<svg
			v-else
			class="jv-an-icon"
			aria-hidden="true"
			viewBox="0 0 24 24"
			width="16"
			height="16"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
		>
			<circle cx="12" cy="12" r="9" />
			<path d="M12 8v5M12 16h.01" />
		</svg>
		<div class="jv-an-body">
			<div v-if="announcement.title" class="jv-an-title">{{ announcement.title }}</div>
			<div v-if="announcement.message" class="jv-an-msg">{{ announcement.message }}</div>
		</div>
		<div class="jv-an-actions">
			<a
				v-if="showLink"
				class="jv-an-btn"
				:href="announcement.link_url"
				target="_blank"
				rel="noopener noreferrer"
				>{{ announcement.link_label || "Learn more" }}</a
			>
			<button
				class="jv-an-x"
				type="button"
				aria-label="Dismiss announcement"
				@click="dismissAnnouncement"
			>
				<svg
					viewBox="0 0 24 24"
					width="14"
					height="14"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
				>
					<path d="M18 6 6 18M6 6l12 12" />
				</svg>
			</button>
		</div>
	</div>
</template>

<style scoped>
/* Tone (accent/amber) resolves per severity class; reused by the fill, border,
   ink AND the CTA so the whole banner stays one coherent colour. */
.jv-tone-info {
	--jv-tone: var(--accent);
	--jv-tone-bg: var(--accent-bg);
}
.jv-tone-warning {
	--jv-tone: var(--amber);
	--jv-tone-bg: var(--amber-bg);
}
.jv-announcementbanner {
	flex: none;
	display: flex;
	flex-wrap: wrap;
	align-items: flex-start;
	gap: 10px;
	margin: 8px 12px 0;
	padding: 12px;
	border-radius: 14px;
	background: var(--jv-tone-bg);
	border: 1px solid color-mix(in srgb, var(--jv-tone) 35%, transparent);
	color: var(--jv-tone);
}
.jv-an-icon {
	flex: none;
	margin-top: 1px;
}
.jv-an-body {
	flex: 1;
	min-width: 160px;
}
.jv-an-title {
	font-size: 13px;
	font-weight: 600;
	line-height: 1.4;
	/* High-contrast neutral ink, not the tone colour: the Info tone (accent) on its
	   tinted bg misses WCAG AA for text. Tone reads via the icon + border instead. */
	color: var(--ink9);
}
.jv-an-msg {
	font-size: 13px;
	line-height: 1.4;
	color: var(--ink7);
}
.jv-an-actions {
	display: flex;
	align-items: center;
	gap: 6px;
	flex: none;
}
.jv-an-btn {
	height: 30px;
	display: inline-flex;
	align-items: center;
	padding: 0 11px;
	border: 1px solid color-mix(in srgb, var(--jv-tone) 40%, transparent);
	border-radius: 8px;
	background: transparent;
	font-family: inherit;
	font-size: 12.5px;
	font-weight: 600;
	/* Neutral high-contrast ink (AA), tonal border keeps it on-theme. */
	color: var(--ink9);
	text-decoration: none;
	white-space: nowrap;
}
.jv-an-btn:active {
	background: color-mix(in srgb, var(--jv-tone) 16%, transparent);
}
.jv-an-x {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	width: 30px;
	height: 30px;
	flex: none;
	border: none;
	border-radius: 8px;
	background: transparent;
	color: var(--ink5);
	cursor: pointer;
}
.jv-an-x:active {
	background: color-mix(in srgb, var(--ink9) 10%, transparent);
}
.jv-an-btn:focus-visible,
.jv-an-x:focus-visible {
	outline: 2px solid var(--jv-tone);
	outline-offset: 2px;
}
</style>
