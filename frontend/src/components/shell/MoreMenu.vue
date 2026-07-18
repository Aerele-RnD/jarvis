<template>
	<Dialog v-model="open" :options="{ size: 'xl', position: 'top' }" @after-leave="reset">
		<template #body>
			<div>
				<div class="relative">
					<div class="absolute inset-y-0 left-0 flex items-center pl-4.5">
						<FeatherIcon name="search" class="h-4 w-4 text-ink-gray-5" />
					</div>
					<input
						ref="inputEl"
						v-model="searchQuery"
						type="text"
						placeholder="Search"
						autocomplete="off"
						spellcheck="false"
						class="w-full border-none bg-transparent py-3 pl-11.5 pr-4.5 text-base text-ink-gray-8 placeholder-ink-gray-4 focus:ring-0"
						@keydown="onKeydown"
					/>
				</div>
				<div ref="listEl" class="max-h-96 overflow-auto border-t">
					<div v-for="group in groups" :key="group.title" class="mb-2 mt-4.5 first:mt-3">
						<div class="mb-2.5 px-4.5 text-base text-ink-gray-5">{{ group.title }}</div>
						<div
							v-for="item in group.items"
							:key="item.name"
							class="px-2.5"
							:data-cp-active="item === activeItem || undefined"
							@mousedown.prevent
							@mousemove="!item.disabled && setActive(item)"
							@click="select(item)"
						>
							<PaletteItem :item="item" :active="item === activeItem" />
						</div>
					</div>
					<div v-if="empty" class="px-4.5 pb-4 pt-3 text-base text-ink-gray-4">
						No results
					</div>
				</div>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
// Sidebar "More" palette — a clone-and-trim of JarvisCommandPalette.vue for
// the overflow destinations (Dashboards today). Same Dialog anatomy, same
// keyboard nav, same PaletteItem rows; bound to store.moreMenuOpen. Empty
// query lists the static destinations; typing filters them and also runs the
// server search_workspace, keeping ONLY its "dashboards" group (whose items
// carry spa_route, not a desk route).
//
// NOTE (dedupe-later): this is the second palette sharing the input +
// flatItems/activeIndex/scrollIntoView machinery with JarvisCommandPalette.
// When a third palette appears, extract a shared usePaletteNav composable
// rather than cloning a third time.
import { ref, computed, watch, nextTick } from "vue"
import { useRouter } from "vue-router"
import { Dialog, FeatherIcon } from "frappe-ui"
import { useShellStore } from "@/stores/shell"
import * as apiShell from "@/api/shell"
import PaletteItem from "./PaletteItem.vue"

const store = useShellStore()
const router = useRouter()

const open = computed({
	get: () => store.moreMenuOpen,
	set: (v) => (store.moreMenuOpen = v),
})

const inputEl = ref(null)
const listEl = ref(null)
const searchQuery = ref("")
const serverGroups = ref([])
const searching = ref(false)
const activeIndex = ref(0)

// Focus the input once the Dialog's portal content is in the DOM (reka-ui's
// autofocus usually lands on it anyway - this covers re-opens reliably).
watch(open, (v) => {
	if (v) nextTick(() => inputEl.value?.focus())
})

let _debounce = null
let _seq = 0
watch(searchQuery, (q) => {
	clearTimeout(_debounce)
	const query = (q || "").trim()
	if (!query) {
		searching.value = false
		serverGroups.value = []
		return
	}
	searching.value = true
	_debounce = setTimeout(async () => {
		const seq = ++_seq
		try {
			const ws = await apiShell.searchWorkspace({ search: query, limit: 6 })
			if (seq !== _seq) return // stale response
			// Only the SPA-native dashboards group belongs in this palette.
			serverGroups.value = ((ws && ws.groups) || []).filter((g) => g.key === "dashboards")
		} catch (e) {
			if (seq === _seq) serverGroups.value = []
		} finally {
			if (seq === _seq) searching.value = false
		}
	}, 300)
})

const destinations = computed(() => [
	{
		name: "dest-dashboards",
		label: "Dashboards",
		icon: "bar-chart-2",
		action: () => router.push("/dashboards"),
	},
])

const groups = computed(() => {
	const q = (searchQuery.value || "").trim().toLowerCase()
	if (!q) {
		return [{ title: "Destinations", items: destinations.value }]
	}
	const out = []
	const dest = destinations.value.filter((it) => it.label.toLowerCase().includes(q))
	if (dest.length) out.push({ title: "Destinations", items: dest })
	if (searching.value) {
		out.push({
			title: "Dashboards",
			items: [{ name: "-loading", label: "Searching…", icon: "loader", disabled: true }],
		})
	} else {
		for (const g of serverGroups.value) {
			if (g.items && g.items.length) out.push({ title: g.title, items: g.items })
		}
	}
	return out
})

// Keyboard cursor runs over the selectable (non-disabled) rows in list order.
const flatItems = computed(() => groups.value.flatMap((g) => g.items).filter((it) => !it.disabled))
const activeItem = computed(() => flatItems.value[activeIndex.value] || null)
const empty = computed(() => !!searchQuery.value.trim() && !searching.value && !flatItems.value.length)

// Any result change (typing, search landing) resets the cursor to the top row.
watch(groups, () => {
	activeIndex.value = 0
})

function setActive(item) {
	const i = flatItems.value.indexOf(item)
	if (i >= 0) activeIndex.value = i
}

function move(delta) {
	const n = flatItems.value.length
	if (!n) return
	activeIndex.value = (activeIndex.value + delta + n) % n
	nextTick(() => {
		listEl.value?.querySelector("[data-cp-active]")?.scrollIntoView({ block: "nearest" })
	})
}

function onKeydown(e) {
	if (e.key === "ArrowDown") {
		e.preventDefault()
		move(1)
	} else if (e.key === "ArrowUp") {
		e.preventDefault()
		move(-1)
	} else if (e.key === "Enter") {
		e.preventDefault()
		select(activeItem.value)
	}
}

function select(item) {
	if (!item || item.disabled) return
	open.value = false
	if (item.action) item.action()
	// Server dashboard rows carry spa_route ("/dashboards/<name>") and no route.
	else if (item.spa_route) router.push(item.spa_route)
}

// after-leave (Dialog's overlay finished its exit) - wipe for the next open.
function reset() {
	clearTimeout(_debounce)
	_seq++ // invalidate any in-flight search
	searchQuery.value = ""
	serverGroups.value = []
	searching.value = false
	activeIndex.value = 0
}
</script>
