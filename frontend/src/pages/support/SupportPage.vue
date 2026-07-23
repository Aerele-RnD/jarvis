<template>
	<div class="flex h-full">
		<!-- Ticket list -->
		<aside class="w-72 shrink-0 border-r border-gray-200 flex flex-col">
			<div class="p-3 border-b border-gray-200 flex items-center justify-between">
				<h2 class="font-semibold text-gray-800">Support</h2>
				<button class="text-sm px-2 py-1 rounded bg-gray-900 text-white" @click="startNew">
					New
				</button>
			</div>
			<div class="flex-1 overflow-y-auto">
				<p v-if="!tickets.length" class="p-3 text-sm text-gray-500">No tickets yet.</p>
				<button
					v-for="t in tickets"
					:key="t.name"
					class="w-full text-left px-3 py-2 border-b border-gray-100 hover:bg-gray-50"
					:class="{ 'bg-gray-100': selected && selected.name === t.name }"
					@click="openTicket(t)"
				>
					<div class="text-sm font-medium text-gray-800 truncate">{{ t.subject }}</div>
					<div class="text-xs text-gray-500">{{ t.status }}</div>
				</button>
			</div>
		</aside>

		<!-- Detail -->
		<section class="flex-1 flex flex-col min-w-0">
			<!-- New ticket -->
			<div v-if="view === 'new'" class="p-4 max-w-2xl">
				<h3 class="font-semibold mb-3">New support ticket</h3>
				<input
					v-model="newSubject"
					placeholder="Subject"
					class="w-full border rounded px-3 py-2 mb-2"
				/>
				<textarea
					v-model="newBody"
					placeholder="Describe your issue…"
					rows="6"
					class="w-full border rounded px-3 py-2 mb-2"
				></textarea>
				<input type="file" class="mb-3 block text-sm" @change="onNewFile" />
				<div class="flex gap-2">
					<button
						class="px-3 py-2 rounded bg-gray-900 text-white text-sm disabled:opacity-50"
						:disabled="!newSubject || busy"
						@click="createTicket"
					>
						Submit
					</button>
					<button class="px-3 py-2 rounded border text-sm" @click="view = 'none'">
						Cancel
					</button>
				</div>
			</div>

			<!-- Thread -->
			<template v-else-if="selected">
				<header class="p-3 border-b border-gray-200 flex items-center justify-between">
					<div class="min-w-0">
						<div class="font-medium text-gray-800 truncate">
							{{ selected.subject }}
						</div>
						<div class="text-xs text-gray-500">{{ selected.status }}</div>
					</div>
					<button
						v-if="selected.status !== 'Closed'"
						class="text-sm px-2 py-1 rounded border"
						:disabled="busy"
						@click="closeTicket"
					>
						Close ticket
					</button>
				</header>

				<div class="flex-1 overflow-y-auto p-4 space-y-4">
					<div v-if="ticketAttachments.length" class="text-sm">
						<div class="text-xs uppercase text-gray-400 mb-1">Attachments</div>
						<ul class="space-y-1">
							<li v-for="a in ticketAttachments" :key="a.file_url">
								<img
									v-if="isImage(a.file_name)"
									:src="dl(a.file_url)"
									:alt="a.file_name"
									class="max-w-xs rounded border"
								/>
								<a
									v-else
									:href="dl(a.file_url)"
									target="_blank"
									rel="noopener"
									class="text-blue-600 underline text-sm"
									>{{ a.file_name }}</a
								>
							</li>
						</ul>
					</div>

					<div
						v-for="(m, i) in messages"
						:key="i"
						class="rounded border border-gray-100 p-3"
						:class="m.sent_or_received === 'Sent' ? 'bg-blue-50' : 'bg-white'"
					>
						<div class="text-xs text-gray-500 mb-1">
							{{ m.sent_or_received === "Sent" ? "Support" : "You" }} ·
							{{ m.creation }}
						</div>
						<!-- Rewrite THEN sanitize (sanitize is the last transform) -->
						<div
							class="prose prose-sm max-w-none"
							v-html="renderMessage(m.content)"
						></div>
						<ul v-if="m.attachments && m.attachments.length" class="mt-2 space-y-1">
							<li v-for="a in m.attachments" :key="a.file_url">
								<img
									v-if="isImage(a.file_name)"
									:src="dl(a.file_url)"
									:alt="a.file_name"
									class="max-w-xs rounded border"
								/>
								<a
									v-else
									:href="dl(a.file_url)"
									target="_blank"
									rel="noopener"
									class="text-blue-600 underline text-sm"
									>{{ a.file_name }}</a
								>
							</li>
						</ul>
					</div>
				</div>

				<footer class="border-t border-gray-200 p-3">
					<textarea
						v-model="replyBody"
						placeholder="Type your reply…"
						rows="2"
						class="w-full border rounded px-3 py-2 mb-2"
					></textarea>
					<div class="flex items-center gap-2">
						<input type="file" class="text-sm" @change="onReplyFile" />
						<button
							class="ml-auto px-3 py-2 rounded bg-gray-900 text-white text-sm disabled:opacity-50"
							:disabled="(!replyBody && !replyFile) || busy"
							@click="sendReply"
						>
							Send
						</button>
					</div>
				</footer>
			</template>

			<div v-else class="flex-1 grid place-items-center text-gray-400 text-sm">
				Select a ticket, or start a new one.
			</div>
		</section>
	</div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import DOMPurify from "dompurify";
import {
	supportListTickets,
	supportGetThread,
	supportCreateTicket,
	supportReply,
	supportCloseTicket,
	supportUpload,
	supportDownloadUrl,
} from "@/api";

const tickets = ref([]);
const selected = ref(null);
const messages = ref([]);
const ticketAttachments = ref([]);
const view = ref("none");
const busy = ref(false);

const newSubject = ref("");
const newBody = ref("");
const newFile = ref(null);
const replyBody = ref("");
const replyFile = ref(null);

function onNewFile(e) {
	newFile.value = e.target.files[0] || null;
}
function onReplyFile(e) {
	replyFile.value = e.target.files[0] || null;
}

function dl(fileUrl) {
	return selected.value ? supportDownloadUrl(selected.value.name, fileUrl) : "";
}
function isImage(name) {
	return /\.(png|jpe?g|gif|webp|avif|bmp)$/i.test(name || "");
}

async function loadTickets() {
	const r = await supportListTickets();
	tickets.value = (r.data && r.data.tickets) || [];
}

async function openTicket(t) {
	selected.value = t;
	view.value = "thread";
	const r = await supportGetThread(t.name);
	messages.value = (r.data && r.data.messages) || [];
	ticketAttachments.value = (r.data && r.data.ticket_attachments) || [];
}

function startNew() {
	view.value = "new";
	selected.value = null;
	newSubject.value = "";
	newBody.value = "";
	newFile.value = null;
}

async function createTicket() {
	busy.value = true;
	try {
		const r = await supportCreateTicket(newSubject.value, newBody.value);
		const ticket = r.data && r.data.ticket;
		if (ticket && newFile.value) await supportUpload(ticket, newFile.value);
		await loadTickets();
		const t = tickets.value.find((x) => x.name === ticket);
		if (t) await openTicket(t);
		else view.value = "none";
	} finally {
		busy.value = false;
	}
}

async function sendReply() {
	busy.value = true;
	try {
		if (replyFile.value) {
			await supportUpload(selected.value.name, replyFile.value);
			replyFile.value = null;
		}
		if (replyBody.value) {
			await supportReply(selected.value.name, replyBody.value);
			replyBody.value = "";
		}
		await openTicket(selected.value);
	} finally {
		busy.value = false;
	}
}

async function closeTicket() {
	busy.value = true;
	try {
		const name = selected.value.name;
		await supportCloseTicket(name);
		await loadTickets();
		// R1-8: re-point `selected` at the refreshed row so the header status reflects Closed.
		const t = tickets.value.find((x) => x.name === name);
		if (t) await openTicket(t);
	} finally {
		busy.value = false;
	}
}

// R1-4: rewrite inline /files/ + /private/files/ src/href to the same-origin download proxy and
// strip srcset FIRST, then DOMPurify.sanitize as the LAST transform (no post-sanitize mutation).
function renderMessage(html) {
	const doc = new DOMParser().parseFromString(html || "", "text/html");
	if (selected.value) {
		doc.querySelectorAll("img[src], a[href]").forEach((el) => {
			const attr = el.tagName === "IMG" ? "src" : "href";
			const v = el.getAttribute(attr) || "";
			if (v.startsWith("/files/") || v.startsWith("/private/files/")) {
				el.setAttribute(attr, supportDownloadUrl(selected.value.name, v));
			}
			el.removeAttribute("srcset");
		});
	}
	return DOMPurify.sanitize(doc.body.innerHTML);
}

onMounted(loadTickets);
</script>
