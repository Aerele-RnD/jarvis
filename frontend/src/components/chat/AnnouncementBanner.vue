<template>
	<!-- Soft, dismissible operator announcement: top-of-chat, coloured by severity
	     (Info -> blue, Warning -> amber). Title + body render as PLAIN TEXT through
	     Banner's {{ }} interpolation - NEVER v-html - so untrusted operator prose
	     can't inject markup. The CTA is scheme-gated (isSafeLink) and only ever an
	     http(s) link. Visibility (yield to greeting/booting/urgent alerts; win the
	     top slot over the update banner) is decided by the caller's v-if. -->
	<div class="jv-announcementbanner">
		<Banner
			:type="tone"
			:title="announcement.title"
			:message="announcement.message"
			align="start"
		>
			<template #action>
				<a
					v-if="isSafeLink(announcement.link_url)"
					class="jv-an-link"
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
					<FeatherIcon name="x" class="size-3.5" />
				</button>
			</template>
		</Banner>
	</div>
</template>

<script setup>
// AnnouncementBanner: the fleet-wide operator announcement as a soft strip. Unlike
// UpdateBanner it has no minimise-into-pill FLIP - dismiss just snoozes per-device
// (announcementGate.dismissAnnouncement) and the reactive showAnnouncement hides it.
// `announcement` is the stable, non-reactive boot payload, so `tone` is a plain
// const, not computed().
import Banner from "@/components/Banner.vue";
import { FeatherIcon } from "frappe-ui";
import { bannerToneFor, isSafeLink } from "@/announcementNudge";
import { announcement, dismissAnnouncement } from "@/announcementGate";

const tone = bannerToneFor(announcement);
</script>

<style scoped>
.jv-announcementbanner {
	margin: 12px 18px 0;
}

/* The CTA link + dismiss ×, styled here since Banner is a child scope. Real
   controls (keyboard-reachable); neutral ink so they don't fight the tonal fill. */
.jv-an-link {
	height: 26px;
	display: inline-flex;
	align-items: center;
	padding: 0 10px;
	border: 1px solid color-mix(in srgb, var(--text) 20%, transparent);
	border-radius: 7px;
	font-size: 12px;
	font-weight: 500;
	color: var(--text-2);
	text-decoration: none;
	white-space: nowrap;
}
.jv-an-link:hover {
	background: color-mix(in srgb, var(--text) 8%, transparent);
}
.jv-an-x {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	width: 26px;
	height: 26px;
	border: none;
	border-radius: 7px;
	background: transparent;
	color: var(--text-2);
	cursor: pointer;
}
.jv-an-x:hover {
	background: color-mix(in srgb, var(--text) 12%, transparent);
}
.jv-an-link:focus-visible,
.jv-an-x:focus-visible {
	outline: 2px solid var(--text-2);
	outline-offset: 2px;
}
</style>
