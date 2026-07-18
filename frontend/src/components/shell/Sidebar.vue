<template>
	<div
		class="relative flex h-full flex-col ease-in-out"
		:class="[resizing ? '' : 'transition-all duration-300', collapsed ? 'w-12' : '']"
		:style="collapsed ? undefined : { width: sidebarWidth + 'px' }"
	>
		<!-- 1. brand + user menu -->
		<div class="p-2">
			<UserMenu :is-collapsed="collapsed" />
		</div>

		<!-- 2. action links -->
		<nav class="flex flex-col">
			<SidebarLink
				label="New Chat"
				icon="plus"
				class="mx-2 my-[1.5px]"
				:is-collapsed="collapsed"
				:on-click="() => store.requestNewChat(router)"
			>
				<template v-if="!collapsed" #right>
					<KeyboardShortcut combo="Ctrl+Shift+O" />
				</template>
			</SidebarLink>
			<SidebarLink
				label="Search Chat"
				icon="search"
				class="mx-2 my-[1.5px]"
				:is-collapsed="collapsed"
				:on-click="() => (store.paletteOpen = true)"
			>
				<template v-if="!collapsed" #right>
					<KeyboardShortcut combo="Mod+K" />
				</template>
			</SidebarLink>
		</nav>

		<!-- 3. nav links -->
		<nav class="flex flex-col">
			<div v-for="link in navLinks" :key="link.label" class="relative flex flex-col">
				<SidebarLink
					:label="link.label"
					:icon="link.icon"
					:to="link.to"
					:is-active="link.isActive()"
					class="mx-2 my-[1.5px]"
					:is-collapsed="collapsed"
				>
					<template v-if="link.badge && !collapsed && store.approvalsCount" #right>
						<Badge
							:label="store.approvalsCount > 9 ? '9+' : String(store.approvalsCount)"
							theme="red"
							variant="subtle"
						/>
					</template>
				</SidebarLink>
				<!-- collapsed badge → floating dot (HD pattern; red = pending action;
				     semantic token so the dot tracks data-theme: #CC2929 light / #E43838 dark) -->
				<div
					v-if="link.badge && collapsed && store.approvalsCount"
					class="absolute size-1.5 translate-x-6 translate-y-1 rounded-full bg-surface-red-5"
				/>
			</div>
		</nav>

		<!-- 3b. overflow destinations (Dashboards, …) — opens the MoreMenu palette.
		     Deliberately NOT a navLinks entry: that loop binds :to and this row is
		     an action. But it DOES light up when the user is on one of its
		     destinations, so a first-class page reached via More still reads as a
		     section (not a transient action). -->
		<nav class="flex flex-col">
			<SidebarLink
				label="More"
				icon="more-horizontal"
				class="mx-2 my-[1.5px]"
				:is-collapsed="collapsed"
				:is-active="onMoreDestination"
				:on-click="() => (store.moreMenuOpen = true)"
			/>
		</nav>

		<!-- 4. recent chats (hidden entirely when collapsed, D6) -->
		<template v-if="!collapsed">
			<div class="px-4 pb-2.5 pt-[11px] text-sm text-ink-gray-5">Recent chats</div>
			<div class="min-h-0 flex-1 overflow-y-auto pb-2">
				<template v-if="starred.length">
					<div class="px-4 pb-1 text-2xs font-medium uppercase tracking-wide text-ink-gray-4">
						Starred
					</div>
					<ConversationRow v-for="c in starred" :key="c.name" :conv="c" />
				</template>
				<template v-if="recent.length">
					<div
						v-if="starred.length"
						class="px-4 pb-1 pt-2 text-2xs font-medium uppercase tracking-wide text-ink-gray-4"
					>
						Recent
					</div>
					<ConversationRow v-for="c in recent" :key="c.name" :conv="c" />
				</template>
				<div
					v-if="!store.conversations.length && !store.conversationsLoading"
					class="px-4 py-3 text-sm text-ink-gray-4"
				>
					No chats yet
				</div>
				<!-- tail row: beyond the 50-row cap, retrieval moves to the palette -->
				<nav v-if="store.conversations.length > 50" class="flex flex-col">
					<SidebarLink
						label="Search chats…"
						icon="search"
						class="mx-2 my-[1.5px]"
						:is-collapsed="false"
						:on-click="() => (store.paletteOpen = true)"
					/>
				</nav>
			</div>
		</template>
		<div v-else class="flex-1" />

		<!-- 5. footer: collapse toggle -->
		<div class="m-2 flex flex-col gap-1">
			<SidebarLink
				label="Collapse"
				:is-collapsed="collapsed"
				:on-click="toggleCollapse"
			>
				<template #icon>
					<FeatherIcon
						name="chevrons-left"
						class="size-4 text-ink-gray-8 duration-300 ease-in-out"
						:class="{ '[transform:rotateY(180deg)]': collapsed }"
					/>
				</template>
			</SidebarLink>
		</div>

		<!-- 6. drag-to-resize handle (expanded only): grab the right edge to set
		     the width, double-click to reset. The collapsed rail is a fixed 48px,
		     so the handle is hidden there. -->
		<div
			v-if="!collapsed"
			class="group absolute inset-y-0 right-0 z-20 flex w-2.5 translate-x-1/2 cursor-col-resize items-center justify-center"
			role="separator"
			aria-orientation="vertical"
			title="Drag to resize · double-click to reset"
			@mousedown.prevent="startResize"
			@dblclick="resetWidth"
		>
			<!-- full-height hairline: appears on hover / while dragging -->
			<span
				class="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors"
				:class="resizing ? 'bg-surface-gray-4' : 'bg-transparent group-hover:bg-surface-gray-4'"
			/>
			<!-- grip pill: always faintly visible so the edge reads as adjustable,
			     solid on hover / while dragging -->
			<span
				class="relative h-7 w-1 rounded-full bg-surface-gray-4 transition-opacity"
				:class="resizing ? 'opacity-100' : 'opacity-30 group-hover:opacity-100'"
			/>
		</div>
	</div>
</template>

<script setup>
// App-shell sidebar (DESIGN-V3 §3.2): 220px expanded / 48px rail (D5),
// user menu · New Chat/Search · nav links (Approvals badge, D12) · recent
// chats (starred pinned, capped 50, D6/D7) · collapse toggle (persisted via
// the store; ≤820px auto-collapse, D8).
import { computed, ref, onBeforeUnmount } from "vue"
import { useRoute, useRouter } from "vue-router"
import { Badge, FeatherIcon, KeyboardShortcut } from "frappe-ui"
import { useShellStore } from "@/stores/shell"
import UserMenu from "./UserMenu.vue"
import SidebarLink from "./SidebarLink.vue"
import ConversationRow from "./ConversationRow.vue"

const store = useShellStore()
const route = useRoute()
const router = useRouter()

const collapsed = computed(() => store.sidebarCollapsed)

// The "More" overflow row lights up on any of its destinations (currently the
// Dashboards page + detail). Extend the prefix list as destinations are added.
const onMoreDestination = computed(() => route.path.startsWith("/dashboards"))
function toggleCollapse() {
	store.sidebarCollapsed = !store.sidebarCollapsed
}

// ── drag-to-resize (expanded width, persisted in the store, D5-adjacent) ──────
// The store getter/setter clamps to [SIDEBAR_MIN_W, SIDEBAR_MAX_W], so we can
// feed it raw deltas. `resizing` suppresses the width transition mid-drag so the
// edge tracks the cursor 1:1 instead of lagging behind the 300ms ease.
const sidebarWidth = computed(() => store.sidebarWidth)
const resizing = ref(false)
let startX = 0
let startW = 0

function startResize(e) {
	if (e.button !== 0 || collapsed.value) return
	resizing.value = true
	startX = e.clientX
	startW = store.sidebarWidth
	window.addEventListener("mousemove", onResize)
	window.addEventListener("mouseup", stopResize)
	document.body.style.userSelect = "none"
	document.body.style.cursor = "col-resize"
}
function onResize(e) {
	store.sidebarWidth = startW + (e.clientX - startX)
}
function stopResize() {
	if (!resizing.value) return
	resizing.value = false
	window.removeEventListener("mousemove", onResize)
	window.removeEventListener("mouseup", stopResize)
	document.body.style.userSelect = ""
	document.body.style.cursor = ""
}
function resetWidth() {
	store.sidebarWidth = 220
}
onBeforeUnmount(stopResize)

const navLinks = [
	{
		label: "Chat",
		icon: "message-circle",
		to: { name: "Chat" },
		isActive: () => route.name === "Chat" || route.name === "Conversation",
	},
	{
		label: "Skills",
		icon: "zap",
		to: { name: "SkillsList" },
		isActive: () => route.path.startsWith("/skills"),
	},
	{
		label: "Macros",
		icon: "layers",
		to: { name: "MacrosList" },
		isActive: () => route.path.startsWith("/macros"),
	},
	{
		label: "Triggers",
		icon: "git-branch",
		to: { name: "TriggersPage" },
		isActive: () => route.path.startsWith("/triggers"),
	},
	{
		label: "File Box",
		icon: "inbox",
		to: { name: "FilesList" },
		isActive: () => route.path.startsWith("/files"),
	},
	{
		label: "Approval Board",
		icon: "check-square",
		to: { name: "ApprovalsList" },
		isActive: () => route.path.startsWith("/approvals"),
		badge: true,
	},
	{
		label: "Agents",
		icon: "cpu",
		to: { name: "AgentsList" },
		isActive: () => route.path.startsWith("/agents"),
	},
]

// Starred pinned on top; starred + recent capped at 50 rows total (D6).
const starred = computed(() => store.conversations.filter((c) => c.starred).slice(0, 50))
const recent = computed(() =>
	store.conversations
		.filter((c) => !c.starred)
		.slice(0, Math.max(0, 50 - starred.value.length)),
)
</script>
