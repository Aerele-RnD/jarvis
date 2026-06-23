<template>
	<div ref="rootEl" class="jv-root" style="--surface:#ffffff;--surface-1:#f7f7f8;--surface-2:#f1f1f3;--surface-3:#ececef;--border:#e8e8ec;--border-2:#dfdfe4;--text:#171717;--text-2:#4a4a4f;--text-3:#83838b;--blue:#171717;--blue-bg:#eff4ff;--blue-bd:#d6e2fb;--green:#16a34a;--green-bg:#edf8f0;--green-bd:#cdeed8;--red:#dc2626;--red-bg:#fdf0ef;--red-bd:#f5d4d1;--amber:#d97706;--amber-bg:#fdf6ec;--amber-bd:#f3e2c2;--rad:8px;font-family:'Inter',system-ui,sans-serif;height:100vh;width:100%;display:flex;color:var(--text);background:var(--surface);overflow:hidden;position:relative;">

		<!-- ============ SIDEBAR ============ -->
		<aside style="width:268px;flex:none;background:var(--surface-1);border-right:1px solid var(--border);display:flex;flex-direction:column;height:100%;">
			<div style="padding:14px 14px 10px;display:flex;align-items:center;gap:9px;">
				<div style="width:28px;height:28px;border-radius:7px;background:var(--blue);display:flex;align-items:center;justify-content:center;flex:none;box-shadow:0 1px 2px rgba(37,99,235,.35);">
					<svg width="16" height="16" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg>
				</div>
				<div style="display:flex;flex-direction:column;line-height:1.1;">
					<span style="font-size:14px;font-weight:600;letter-spacing:-.01em;">Jarvis</span>
					<span style="font-size:11px;color:var(--text-3);font-weight:450;">ERPNext Assistant</span>
				</div>
				<div style="margin-left:auto;display:flex;align-items:center;gap:5px;padding:3px 7px;background:var(--green-bg);border-radius:20px;">
					<span style="width:6px;height:6px;border-radius:50%;background:var(--green);"></span>
					<span style="font-size:10px;color:var(--green);font-weight:550;">Live</span>
				</div>
			</div>

			<div style="padding:6px 12px 10px;">
				<button class="jv-newchat" @click="newChat" style="width:100%;display:flex;align-items:center;gap:8px;padding:8px 11px;background:var(--text);color:#fff;border:none;border-radius:var(--rad);font-family:inherit;font-size:13px;font-weight:550;cursor:pointer;">
					<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
					New chat
				</button>
			</div>

			<div style="padding:0 12px 10px;">
				<div style="display:flex;align-items:center;gap:8px;padding:7px 10px;background:var(--surface);border:1px solid var(--border);border-radius:var(--rad);">
					<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.9" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
					<input v-model="search" placeholder="Search chats" style="flex:1;border:none;outline:none;background:transparent;font-family:inherit;font-size:12.5px;color:var(--text);" />
				</div>
			</div>

			<nav style="flex:1;overflow-y:auto;padding:2px 8px 12px;">
				<template v-for="g in groups" :key="g.label">
					<div style="padding:8px 8px 4px;font-size:11px;font-weight:600;color:var(--text-3);letter-spacing:.03em;text-transform:uppercase;">{{ g.label }}</div>
					<div
						v-for="c in g.items"
						:key="c.name"
						class="jv-conv"
						:class="{ on: c.name === currentId }"
						@click="selectConversation(c.name)"
						style="display:flex;align-items:center;gap:9px;padding:7px 9px;border-radius:6px;cursor:pointer;margin-bottom:1px;"
					>
						<svg width="14" height="14" viewBox="0 0 24 24" fill="none" :stroke="c.name === currentId ? 'var(--text-2)' : 'var(--text-3)'" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
						<span :style="{ fontSize: '13px', color: c.name === currentId ? 'var(--text)' : 'var(--text-2)', fontWeight: c.name === currentId ? 500 : 400, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }">{{ c.title || "New chat" }}</span>
					</div>
				</template>
				<div v-if="!conversations.length" style="padding:18px 10px;text-align:center;font-size:12.5px;color:var(--text-3);">No chats yet</div>
			</nav>

			<div class="jv-usermenu-wrap" style="position:relative;border-top:1px solid var(--border);">
				<div v-if="userMenuOpen" style="position:absolute;bottom:calc(100% + 6px);left:12px;right:12px;background:var(--surface);border:1px solid var(--border-2);border-radius:10px;box-shadow:0 10px 28px rgba(20,20,30,.16);padding:5px;z-index:20;">
					<button class="jv-menuitem" @click="goDesk">
						<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /></svg>
						<span>Switch to Desk</span>
					</button>
					<button class="jv-menuitem" @click="session.logout()">
						<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" /></svg>
						<span style="color:var(--red);">Log out</span>
					</button>
				</div>
				<div style="padding:10px 12px;display:flex;align-items:center;gap:9px;">
					<div style="width:28px;height:28px;border-radius:50%;background:#e7ddcf;color:#8a6d3b;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;flex:none;">{{ initials }}</div>
					<div style="display:flex;flex-direction:column;line-height:1.2;min-width:0;">
						<span style="font-size:12.5px;font-weight:550;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ fullName }}</span>
						<span style="font-size:11px;color:var(--text-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ session.user }}</span>
					</div>
					<button class="jv-iconbtn" @click="userMenuOpen = !userMenuOpen" title="Account" style="margin-left:auto;flex:none;width:26px;height:26px;display:flex;align-items:center;justify-content:center;background:transparent;border:none;border-radius:6px;cursor:pointer;">
						<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM12 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4z" /></svg>
					</button>
				</div>
			</div>
		</aside>

		<!-- ============ MAIN ============ -->
		<main style="flex:1;display:flex;flex-direction:column;height:100%;min-width:0;background:var(--surface);">
			<header style="height:52px;flex:none;border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 18px;gap:12px;">
				<div style="display:flex;flex-direction:column;line-height:1.15;min-width:0;">
					<span style="font-size:14px;font-weight:600;letter-spacing:-.01em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ currentTitle }}</span>
					<span style="font-size:11.5px;color:var(--text-3);">{{ headerSub }}</span>
				</div>
				<div style="margin-left:auto;display:flex;align-items:center;gap:8px;">
					<!-- Model picker: switch the LLM model for this conversation -->
					<div class="jv-modelmenu-wrap" style="position:relative;">
						<button class="jv-modelpill" @click="modelMenuOpen = !modelMenuOpen" :title="availableModels.length ? 'Switch model' : 'Connected to ERPNext'" style="display:flex;align-items:center;gap:7px;padding:5px 10px;background:var(--surface-1);border:1px solid var(--border);border-radius:20px;cursor:pointer;font-family:inherit;">
							<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5" /><path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3" /></svg>
							<span style="font-size:12px;color:var(--text-2);font-weight:500;">ERPNext · {{ modelLabel }}</span>
							<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6" /></svg>
						</button>
						<div v-if="modelMenuOpen && availableModels.length" style="position:absolute;top:calc(100% + 6px);right:0;min-width:184px;background:var(--surface);border:1px solid var(--border-2);border-radius:10px;box-shadow:0 8px 24px rgba(20,20,30,.14);padding:5px;z-index:30;">
							<div style="padding:5px 9px 6px;font-size:10px;color:var(--text-3);font-weight:600;text-transform:uppercase;letter-spacing:.03em;">Model · {{ ui.llm_provider }}</div>
							<button v-for="m in availableModels" :key="m" class="jv-menuitem" @click="selectModel(m)">
								<span style="flex:1;">{{ m }}</span>
								<svg v-if="m === modelLabel" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
							</button>
						</div>
					</div>
					<button class="jv-iconbtn-bd" @click="openErpDesk" title="Open ERPNext Desk (new tab)" style="width:32px;height:32px;display:flex;align-items:center;justify-content:center;background:var(--surface);border:1px solid var(--border);border-radius:7px;cursor:pointer;">
						<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" /></svg>
					</button>
				</div>
			</header>

			<!-- ===== WELCOME ===== -->
			<div v-if="showWelcome" style="flex:1;overflow-y:auto;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:32px;">
				<div style="width:100%;max-width:680px;text-align:center;">
					<div style="width:52px;height:52px;border-radius:13px;background:var(--blue);display:flex;align-items:center;justify-content:center;margin:0 auto 18px;box-shadow:0 4px 14px rgba(37,99,235,.28);">
						<svg width="28" height="28" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg>
					</div>
					<h1 style="font-size:23px;font-weight:600;letter-spacing:-.02em;margin:0 0 6px;">{{ greeting }}, {{ firstName }}</h1>
					<p style="font-size:14.5px;color:var(--text-2);margin:0 0 26px;line-height:1.5;">Ask about your ERP data, run a workflow, or draft something. Jarvis is connected to your <strong style="color:var(--text);font-weight:600;">ERPNext</strong> instance.</p>
					<div style="display:grid;grid-template-columns:1fr 1fr;gap:11px;text-align:left;">
						<div v-for="s in suggestions" :key="s.title" class="jv-suggest" @click="fillInput(s.prompt)" style="display:flex;gap:11px;padding:14px;background:var(--surface);border:1px solid var(--border);border-radius:10px;cursor:pointer;transition:border-color .12s,background .12s;">
							<div :style="{ width:'30px',height:'30px',flex:'none',borderRadius:'8px',background:s.bg,display:'flex',alignItems:'center',justifyContent:'center' }" v-html="s.icon"></div>
							<div>
								<div style="font-size:13.5px;font-weight:550;margin-bottom:2px;">{{ s.title }}</div>
								<div style="font-size:12.5px;color:var(--text-3);line-height:1.4;">{{ s.prompt }}</div>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- ===== CONVERSATION ===== -->
			<div v-else ref="threadEl" style="flex:1;overflow-y:auto;">
				<div style="max-width:760px;margin:0 auto;padding:26px 24px 36px;display:flex;flex-direction:column;gap:26px;">
					<template v-for="m in visibleMessages" :key="m.name">
						<!-- user -->
						<div v-if="m.role === 'user'" style="display:flex;justify-content:flex-end;">
							<div style="max-width:78%;background:var(--surface-2);border:1px solid var(--border);border-radius:14px 14px 4px 14px;padding:10px 14px;font-size:14px;line-height:1.5;color:var(--text);white-space:pre-wrap;">{{ m.content }}</div>
						</div>
						<!-- assistant -->
						<div v-else style="display:flex;gap:12px;">
							<div style="width:28px;height:28px;flex:none;border-radius:7px;background:var(--blue);display:flex;align-items:center;justify-content:center;margin-top:2px;">
								<svg width="15" height="15" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg>
							</div>
							<div style="flex:1;min-width:0;">
								<div v-if="m.error" style="border:1px solid var(--red-bd);border-radius:11px;background:var(--red-bg);padding:13px 15px;display:flex;align-items:flex-start;gap:10px;">
									<svg width="17" height="17" style="margin-top:1px;flex:none;" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><path d="M12 9v4M12 17h.01" /></svg>
									<div style="flex:1;">
										<div style="font-size:13.5px;font-weight:600;color:#b42318;">Something went wrong</div>
										<div style="font-size:12.5px;color:#9a3a30;margin-top:2px;line-height:1.5;">{{ m.error }}</div>
										<button class="jv-retry" @click="retry(m.name)" style="margin-top:10px;display:flex;align-items:center;gap:6px;padding:6px 12px;background:var(--red);color:#fff;border:none;border-radius:7px;font-family:inherit;font-size:12px;font-weight:550;cursor:pointer;">Retry</button>
									</div>
								</div>
								<div v-else class="jv-md" style="font-size:14px;line-height:1.6;color:var(--text);" v-html="render(m.content)"></div>
								<!-- rich outputs: agent canvas/chart artifacts rendered inline (sandboxed) -->
								<div v-for="cv in (m.canvas || [])" :key="cv.name" class="jv-canvas">
									<div class="jv-canvas-bar">
										<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18" /><path d="M18 9l-5 5-3-3-4 4" /></svg>
										<span>{{ cv.title }}</span>
										<span class="jv-canvas-type">{{ cv.type }}</span>
									</div>
									<iframe
										v-if="canvasContent[m.name + '::' + cv.name]"
										:srcdoc="canvasContent[m.name + '::' + cv.name]"
										sandbox="allow-scripts allow-popups"
										class="jv-canvas-frame"
										loading="lazy"
										title="Jarvis chart"
									></iframe>
									<div v-else class="jv-canvas-loading">Rendering {{ cv.title }}…</div>
								</div>
								<div v-if="runMeta[m.name] && !m.error" class="jv-meta">
									<span :title="(runMeta[m.name].names || []).join(', ')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 1 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" /></svg>{{ runMeta[m.name].tools }} tool{{ runMeta[m.name].tools === 1 ? "" : "s" }}</span>
									<span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>{{ (runMeta[m.name].ms / 1000).toFixed(1) }}s</span>
								</div>
							</div>
						</div>
					</template>

					<!-- live tool activity + thinking (Claude Code style) -->
					<div v-if="activeTools.length || waiting" style="display:flex;gap:12px;">
						<div style="width:28px;height:28px;flex:none;border-radius:7px;background:var(--blue);display:flex;align-items:center;justify-content:center;margin-top:2px;">
							<svg width="15" height="15" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg>
						</div>
						<div style="flex:1;min-width:0;padding-top:3px;">
							<div v-for="t in activeTools" :key="t.id" class="jv-toolrow">
								<svg v-if="t.status === 'running'" class="jv-spin" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--blue)" stroke-width="2.4" stroke-linecap="round"><path d="M12 3a9 9 0 1 0 9 9" /></svg>
								<svg v-else-if="t.status === 'error'" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="2.2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
								<svg v-else width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
								<span>{{ t.status === "running" ? "Running" : t.status === "error" ? "Failed" : "Ran" }} <b>{{ t.name }}</b></span>
							</div>
							<div v-if="waiting && !activeTools.length" style="display:flex;align-items:center;gap:7px;padding-top:4px;">
								<span style="display:flex;gap:4px;">
									<span style="width:6px;height:6px;border-radius:50%;background:var(--text-3);animation:jv-dot 1.1s infinite;"></span>
									<span style="width:6px;height:6px;border-radius:50%;background:var(--text-3);animation:jv-dot 1.1s infinite .18s;"></span>
									<span style="width:6px;height:6px;border-radius:50%;background:var(--text-3);animation:jv-dot 1.1s infinite .36s;"></span>
								</span>
								<span style="font-size:12px;color:var(--text-3);">Thinking…</span>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- ===== COMPOSER ===== -->
			<div style="flex:none;padding:12px 24px 16px;border-top:1px solid var(--border);background:var(--surface);">
				<div style="max-width:760px;margin:0 auto;">
					<div class="jv-composer" style="position:relative;border:1.5px solid var(--text);border-radius:13px;background:var(--surface);box-shadow:0 2px 12px rgba(0,0,0,.07);padding:5px 6px 6px 6px;transition:border-color .12s,box-shadow .12s;">
						<!-- mention dropdown (@ user, / doctype·tool) -->
						<div v-if="mention.open && mention.items.length" style="position:absolute;bottom:calc(100% + 6px);left:0;min-width:248px;max-height:248px;overflow-y:auto;background:var(--surface);border:1px solid var(--border-2);border-radius:10px;box-shadow:0 10px 28px rgba(20,20,30,.16);padding:5px;z-index:30;">
							<button v-for="(it, i) in mention.items" :key="it.value" class="jv-menuitem" :class="{ on: i === mention.index }" @click="applyMention(it)" @mouseenter="mention.index = i">
								<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ mention.type }}{{ it.value }}</span>
								<span style="font-size:10px;color:var(--text-3);text-transform:uppercase;letter-spacing:.03em;">{{ it.sub }}</span>
							</button>
						</div>
						<!-- pending file attachments -->
						<div v-if="pendingFiles.length || uploading" style="display:flex;flex-wrap:wrap;gap:6px;padding:4px 4px 2px;">
							<span v-for="(f, i) in pendingFiles" :key="i" style="display:inline-flex;align-items:center;gap:5px;font-size:11.5px;padding:3px 5px 3px 9px;border-radius:999px;color:var(--text-2);background:var(--surface-1);border:1px solid var(--border);">📎 {{ f.file_name }}<button @click="removeFile(i)" style="border:none;background:transparent;cursor:pointer;font-size:14px;line-height:1;color:var(--text-3);">×</button></span>
							<span v-if="uploading" style="font-size:11.5px;color:var(--text-3);padding:3px 6px;">Uploading…</span>
						</div>
						<textarea ref="inputEl" v-model="input" @input="onInput" @keydown="onKey" rows="1" placeholder="Ask Jarvis…   @ to mention a user, / for a doctype or tool" style="width:100%;border:none;outline:none;resize:none;font-family:inherit;font-size:14px;line-height:1.5;color:var(--text);background:transparent;padding:8px 8px 4px;max-height:140px;"></textarea>
						<input ref="fileInput" type="file" multiple style="display:none;" @change="onFilesPicked" />
						<div style="display:flex;align-items:center;gap:6px;padding:2px 4px;">
							<button class="jv-iconbtn" title="Attach file" @click="pickFiles" style="width:30px;height:30px;display:flex;align-items:center;justify-content:center;background:transparent;border:none;border-radius:7px;cursor:pointer;color:var(--text-3);">
								<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a5 5 0 0 1-7.07-7.07l9.19-9.19a3.5 3.5 0 0 1 4.95 4.95l-9.2 9.19a1.5 1.5 0 0 1-2.12-2.12l8.49-8.49" /></svg>
							</button>
							<span style="margin-left:auto;font-size:11px;color:var(--text-3);margin-right:4px;">{{ busy ? "Stop" : "Enter ↵" }}</span>
							<button v-if="busy" @click="stopRun" title="Stop generating" style="width:32px;height:32px;display:flex;align-items:center;justify-content:center;background:var(--text);border:none;border-radius:8px;cursor:pointer;">
								<svg width="13" height="13" viewBox="0 0 24 24" fill="#fff"><rect x="6" y="6" width="12" height="12" rx="2.5" /></svg>
							</button>
							<button v-else @click="send()" :disabled="!canSend" :style="{ width:'32px', height:'32px', display:'flex', alignItems:'center', justifyContent:'center', background: canSend ? 'var(--blue)' : 'var(--surface-3)', border:'none', borderRadius:'8px', cursor: canSend ? 'pointer' : 'default', transition:'background .12s' }">
								<svg width="16" height="16" viewBox="0 0 24 24" fill="none" :stroke="canSend ? '#fff' : 'var(--text-3)'" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
							</button>
						</div>
					</div>
					<div style="text-align:center;font-size:10.5px;color:var(--text-3);margin-top:8px;">Jarvis can make mistakes. Verify important actions before submitting to ERPNext.</div>
				</div>
			</div>
		</main>
	</div>
</template>

<script setup>
import { ref, computed, inject, onMounted, onBeforeUnmount, nextTick } from "vue"
import { useRoute } from "vue-router"
import * as api from "@/api"
import { renderMarkdown } from "@/markdown"

const session = inject("$session")
const socket = inject("$socket")
const route = useRoute()

const conversations = ref([])
const currentId = ref(null)
const messages = ref([])
const input = ref("")
const sending = ref(false)
const waiting = ref(false)
const search = ref("")
const ui = ref({})
const inputEl = ref(null)
const threadEl = ref(null)
const rootEl = ref(null)
const userMenuOpen = ref(false)
const modelMenuOpen = ref(false)
const modelOverride = ref("")

// Phase 1: streaming/metrics, live tool activity, file input, mentions, stop
const runStartMs = ref(0)
const currentRunId = ref(null)
const stoppedRunId = ref(null)
const activeTools = ref([]) // [{ id, name, status }] for the in-flight run
const runMeta = ref({}) // { [message_id]: { ms, tools, names } } — survives reloads
const canvasContent = ref({}) // { `${msgName}::${canvasName}`: render-ready html for the iframe srcdoc }
const pendingFiles = ref([]) // [{ file_url, file_name }] attachments to send
const uploading = ref(false)
const fileInput = ref(null)
const mention = ref({ open: false, type: "", query: "", start: 0, items: [], index: 0 })
const JARVIS_TOOLS = [
	"get_list", "get_doc", "get_schema", "run_query", "run_report",
	"create_doc", "update_doc", "submit_doc", "cancel_doc", "amend_doc", "delete_doc",
]

function cookie(name) {
	return new URLSearchParams(document.cookie.split("; ").join("&")).get(name)
}
const fullName = (cookie("full_name") ? decodeURIComponent(cookie("full_name")) : "") || session.user || "User"
const firstName = computed(() => fullName.split(/\s+/)[0])
const initials = computed(
	() => fullName.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase() || "U",
)
const greeting = computed(() => {
	const h = new Date().getHours()
	return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"
})
const modelLabel = computed(() => modelOverride.value || ui.value.llm_model || "gpt-5.5")
const availableModels = computed(() => ui.value.subscription_models?.[ui.value.llm_provider] || [])

const currentTitle = computed(
	() => conversations.value.find((c) => c.name === currentId.value)?.title || "New chat",
)
const visibleMessages = computed(() =>
	messages.value.filter((m) => m.role === "user" || m.role === "assistant"),
)
const showWelcome = computed(() => !currentId.value || visibleMessages.value.length === 0)
const headerSub = computed(() => {
	const n = visibleMessages.value.length
	return n ? `${Math.ceil(n / 2)} message${n > 2 ? "s" : ""}` : "ERPNext Assistant"
})
const canSend = computed(
	() => (input.value.trim().length > 0 || pendingFiles.value.length > 0) && !sending.value,
)
const busy = computed(() => sending.value || waiting.value)

const filteredConvs = computed(() => {
	const q = search.value.trim().toLowerCase()
	return q ? conversations.value.filter((c) => (c.title || "").toLowerCase().includes(q)) : conversations.value
})
const groups = computed(() => {
	const today = [], yest = [], earlier = []
	const now = new Date()
	const d0 = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
	for (const c of filteredConvs.value) {
		const raw = (c.last_active_at || c.modified || "").replace(" ", "T")
		const t = raw ? new Date(raw) : now
		const cd = new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime()
		const diff = Math.round((d0 - cd) / 86400000)
		if (diff <= 0) today.push(c)
		else if (diff === 1) yest.push(c)
		else earlier.push(c)
	}
	return [
		{ label: "Today", items: today },
		{ label: "Yesterday", items: yest },
		{ label: "Earlier", items: earlier },
	].filter((g) => g.items.length)
})

const suggestions = [
	{ title: "Analyse data", prompt: "Which sales orders are overdue this month?", bg: "var(--blue-bg)", icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#171717" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M18 9l-5 5-3-3-4 4"/></svg>' },
	{ title: "Take an action", prompt: "Create a new Sales Order", bg: "var(--green-bg)", icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>' },
	{ title: "Search records", prompt: "Search for a customer or contact", bg: "var(--amber-bg)", icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>' },
	{ title: "Draft content", prompt: "Write a follow-up email to a lead", bg: "#f3eefe", icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>' },
]

function render(text) {
	return renderMarkdown(text || "")
}
// Lazily fetch each canvas artifact's render-ready HTML and cache it by
// `${msgName}::${canvasName}` so the inline iframe srcdoc can bind to it.
async function ensureCanvas(m) {
	if (!m || !Array.isArray(m.canvas) || !m.canvas.length) return
	for (const cv of m.canvas) {
		const key = m.name + "::" + cv.name
		if (canvasContent.value[key]) continue
		try {
			const r = await api.getCanvas(m.name, cv.name)
			if (r && r.content) canvasContent.value = { ...canvasContent.value, [key]: r.content }
		} catch (e) {
			/* leave it in the loading state; a reload retries */
		}
	}
	nextTick(scrollBottom)
}
function scrollBottom() {
	const el = threadEl.value
	if (el) el.scrollTop = el.scrollHeight
}
function autoGrow() {
	const el = inputEl.value
	if (!el) return
	el.style.height = "auto"
	el.style.height = Math.min(el.scrollHeight, 140) + "px"
}
function onKey(e) {
	const mn = mention.value
	if (mn.open && mn.items.length) {
		if (e.key === "ArrowDown") {
			e.preventDefault()
			mention.value = { ...mn, index: (mn.index + 1) % mn.items.length }
			return
		}
		if (e.key === "ArrowUp") {
			e.preventDefault()
			mention.value = { ...mn, index: (mn.index - 1 + mn.items.length) % mn.items.length }
			return
		}
		if (e.key === "Enter" || e.key === "Tab") {
			e.preventDefault()
			applyMention(mn.items[mn.index])
			return
		}
		if (e.key === "Escape") {
			e.preventDefault()
			mention.value = { ...mn, open: false }
			return
		}
	}
	if (e.key === "Enter" && !e.shiftKey) {
		e.preventDefault()
		send()
	}
}

async function loadConversations() {
	conversations.value = await api.listConversations()
}
async function loadConversation(id) {
	if (!id) {
		messages.value = []
		modelOverride.value = ""
		return
	}
	const d = await api.getConversation(id)
	messages.value = d?.messages || []
	modelOverride.value = d?.model_override || ""
	for (const m of messages.value) {
		if (Array.isArray(m.canvas) && m.canvas.length) ensureCanvas(m)
	}
	await nextTick()
	scrollBottom()
}
async function selectConversation(id) {
	if (id === currentId.value) return
	currentId.value = id
	waiting.value = false
	await loadConversation(id)
}
async function newChat() {
	const conv = await api.createOrFocusEmpty()
	currentId.value = conv?.name || conv
	messages.value = []
	await loadConversations()
	await nextTick()
	inputEl.value?.focus()
}
// Welcome cards drop the prompt into the input (don't send) so the user can
// tweak it first.
function fillInput(text) {
	input.value = text
	nextTick(() => {
		inputEl.value?.focus()
		autoGrow()
	})
}
function goDesk() {
	window.location.assign("/app")
}
function openErpDesk() {
	window.open("/app", "_blank")
}
async function selectModel(m) {
	modelMenuOpen.value = false
	modelOverride.value = m
	if (currentId.value) {
		try {
			await api.setConversationModel(currentId.value, m)
		} catch (e) {
			/* ignore */
		}
	}
}
function onDocClick(e) {
	if (!e.target.closest(".jv-usermenu-wrap")) userMenuOpen.value = false
	if (!e.target.closest(".jv-modelmenu-wrap")) modelMenuOpen.value = false
	if (!e.target.closest(".jv-composer")) mention.value = { ...mention.value, open: false }
}
async function retry(messageId) {
	sending.value = true
	waiting.value = true
	try {
		await api.retryMessage(messageId)
	} catch (e) {
		sending.value = false
		waiting.value = false
	}
}

async function send(textArg) {
	const fromMain = typeof textArg !== "string"
	const text = (fromMain ? input.value : textArg).trim()
	const attachments = fromMain ? pendingFiles.value.slice() : []
	if ((!text && !attachments.length) || sending.value) return
	if (fromMain) {
		input.value = ""
		pendingFiles.value = []
		mention.value = { ...mention.value, open: false }
		nextTick(autoGrow)
	}
	if (!currentId.value) {
		const conv = await api.createOrFocusEmpty()
		currentId.value = conv?.name || conv
		await loadConversations()
	}
	sending.value = true
	waiting.value = true
	stoppedRunId.value = null
	const marker = attachments.length ? "📎 " + attachments.map((a) => a.file_name).join(", ") : ""
	const optimistic = [text, marker].filter(Boolean).join("\n\n")
	messages.value = [...messages.value, { name: `tmp-${Date.now()}`, role: "user", content: optimistic }]
	await nextTick()
	scrollBottom()
	try {
		await api.sendMessage(currentId.value, text, undefined, attachments)
	} catch (e) {
		sending.value = false
		waiting.value = false
	}
}

function onEvent(p) {
	if (p.conversation_id !== currentId.value) return
	if (p.run_id && p.run_id === stoppedRunId.value) return // user stopped this run
	switch (p.kind) {
		case "run:start":
			currentRunId.value = p.run_id
			runStartMs.value = Date.now()
			activeTools.value = []
			waiting.value = true
			break
		case "assistant:delta": {
			waiting.value = false
			// Upsert: the message may not be loaded yet when the first delta
			// arrives — add it so streaming text shows immediately (the bug fix).
			let m = messages.value.find((x) => x.name === p.message_id)
			if (!m) {
				m = { name: p.message_id, role: "assistant", content: "", streaming: true }
				messages.value = [...messages.value, m]
			}
			m.content = p.text
			m.streaming = true
			nextTick(scrollBottom)
			break
		}
		case "tool:start": {
			const id = p.tool_call_id || `${p.tool_name}-${activeTools.value.length}`
			activeTools.value = [...activeTools.value, { id, name: p.tool_name, status: "running" }]
			waiting.value = false
			nextTick(scrollBottom)
			break
		}
		case "tool:end": {
			const t = activeTools.value.find((x) => x.id === p.tool_call_id)
			if (t) t.status = p.status || "completed"
			break
		}
		case "canvas": {
			// Agent produced a chart/canvas this turn — attach + render inline.
			const cm = messages.value.find((x) => x.name === p.message_id)
			if (cm) {
				cm.canvas = p.items
				ensureCanvas(cm)
			}
			break
		}
		case "run:end": {
			const m = messages.value.find((x) => x.name === p.message_id)
			if (m) m.streaming = false
			// Stamp metrics keyed by message_id so they survive the reload below.
			if (p.message_id) {
				runMeta.value = {
					...runMeta.value,
					[p.message_id]: {
						ms: runStartMs.value ? Date.now() - runStartMs.value : 0,
						tools: activeTools.value.length,
						names: activeTools.value.map((t) => t.name),
					},
				}
			}
			waiting.value = false
			sending.value = false
			activeTools.value = []
			currentRunId.value = null
			loadConversations()
			loadConversation(currentId.value)
			break
		}
		case "run:error":
			waiting.value = false
			sending.value = false
			activeTools.value = []
			currentRunId.value = null
			loadConversation(currentId.value)
			break
	}
}

function stopRun() {
	// No backend cancel endpoint yet, so this stops the UI: ignore further
	// events for this run, drop the spinner, and mark the reply interrupted.
	// (The server-side turn still finishes; reopening the chat shows the full
	// reply.)
	if (currentRunId.value) stoppedRunId.value = currentRunId.value
	const m = [...messages.value].reverse().find((x) => x.role === "assistant" && x.streaming)
	if (m) {
		m.streaming = false
		if (!m.content) m.content = "_(stopped)_"
	}
	waiting.value = false
	sending.value = false
	activeTools.value = []
}

// ---- file input ----
function pickFiles() {
	fileInput.value?.click()
}
async function onFilesPicked(e) {
	const files = Array.from(e.target.files || [])
	e.target.value = ""
	if (!files.length) return
	uploading.value = true
	for (const f of files) {
		try {
			pendingFiles.value = [...pendingFiles.value, await api.uploadFile(f)]
		} catch (err) {
			/* skip a file that failed to upload */
		}
	}
	uploading.value = false
	inputEl.value?.focus()
}
function removeFile(i) {
	pendingFiles.value = pendingFiles.value.filter((_, idx) => idx !== i)
}

// ---- mentions (@ user, / doctype·tool) ----
let _mentionSeq = 0
function onInput() {
	autoGrow()
	const el = inputEl.value
	if (!el) return
	const caret = el.selectionStart
	const m = input.value.slice(0, caret).match(/(?:^|\s)([@/])([\w-]*)$/)
	if (!m) {
		mention.value = { ...mention.value, open: false }
		return
	}
	const type = m[1]
	const query = m[2]
	mention.value = { open: true, type, query, start: caret - query.length - 1, items: mention.value.items, index: 0 }
	queryMentions(type, query)
}
async function queryMentions(type, query) {
	const seq = ++_mentionSeq
	let items = []
	try {
		if (type === "@") {
			const r = await api.searchLink("User", query)
			items = (r || []).map((x) => ({ value: x.value, sub: x.description || "user" }))
		} else {
			const tools = JARVIS_TOOLS.filter((t) => t.includes(query.toLowerCase())).map((t) => ({ value: t, sub: "tool" }))
			const r = await api.searchLink("DocType", query)
			const dts = (r || []).map((x) => ({ value: x.value, sub: "doctype" }))
			items = [...tools, ...dts].slice(0, 8)
		}
	} catch (e) {
		items = []
	}
	if (seq !== _mentionSeq) return
	mention.value = { ...mention.value, items, index: 0 }
}
function applyMention(item) {
	if (!item) return
	const el = inputEl.value
	const caret = el ? el.selectionStart : input.value.length
	const before = input.value.slice(0, mention.value.start)
	const token = mention.value.type + item.value + " "
	input.value = before + token + input.value.slice(caret)
	mention.value = { ...mention.value, open: false }
	nextTick(() => {
		autoGrow()
		if (el) {
			const pos = (before + token).length
			el.focus()
			el.setSelectionRange(pos, pos)
		}
	})
}

onMounted(async () => {
	// Gate the chat the way the old Desk page did: if the customer hasn't
	// finished signup / LLM setup, send them to the onboarding wizard. A
	// transient failure falls through to the chat rather than trapping them.
	try {
		const r = await api.isReadyForChat()
		if (r && r.ready === false) {
			window.location.assign("/app/jarvis-onboarding")
			return
		}
	} catch (e) {
		/* fall through */
	}
	socket?.on("jarvis:event", onEvent)
	document.addEventListener("pointerdown", onDocClick)
	try {
		ui.value = (await api.getChatUiSettings()) || {}
	} catch (e) {
		/* ignore */
	}
	await loadConversations()
	const first = route.params.id || conversations.value[0]?.name
	if (first) {
		currentId.value = first
		await loadConversation(first)
	}
	await nextTick()
	inputEl.value?.focus()
})
onBeforeUnmount(() => {
	socket?.off("jarvis:event", onEvent)
	document.removeEventListener("pointerdown", onDocClick)
})
</script>

<style scoped>
.jv-newchat:hover { background: #000 !important; }
.jv-conv:hover { background: var(--surface-2); }
.jv-conv.on { background: var(--surface-3); }
.jv-suggest:hover { border-color: var(--border-2); background: var(--surface-1); }
.jv-iconbtn:hover { background: var(--surface-2); color: var(--text-2); }
.jv-iconbtn-bd:hover { background: var(--surface-1); }
.jv-ctxbtn:hover { background: var(--surface-2); }
.jv-retry:hover { filter: brightness(0.94); }
.jv-modelpill:hover { background: var(--surface-2); }
.jv-menuitem { display: flex; align-items: center; gap: 9px; width: 100%; padding: 7px 9px; border: none; background: transparent; border-radius: 7px; font-family: inherit; font-size: 12.5px; color: var(--text); cursor: pointer; text-align: left; }
.jv-menuitem:hover, .jv-menuitem.on { background: var(--surface-1); }
/* black focus highlight on the composer */
.jv-composer:focus-within { border-color: var(--text); box-shadow: 0 0 0 3px rgba(23, 23, 23, 0.07); }
/* response metrics (tools · time) */
.jv-meta { display: flex; align-items: center; gap: 14px; margin-top: 9px; font-size: 11px; color: var(--text-3); }
.jv-meta span { display: inline-flex; align-items: center; gap: 4px; }
/* live tool activity rows */
.jv-toolrow { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--text-2); padding: 2px 0; }
.jv-toolrow b { font-weight: 600; color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.jv-spin { animation: jv-spin 0.8s linear infinite; }
@keyframes jv-spin { to { transform: rotate(360deg); } }

/* inline canvas/chart artifacts (rendered sandboxed) */
.jv-canvas { margin-top: 12px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--surface); }
.jv-canvas-bar { display: flex; align-items: center; gap: 7px; padding: 8px 12px; font-size: 12.5px; font-weight: 550; color: var(--text-2); background: var(--surface-1); border-bottom: 1px solid var(--border); }
.jv-canvas-bar svg { color: var(--text-3); flex: none; }
.jv-canvas-type { margin-left: auto; font-size: 10px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; }
.jv-canvas-frame { width: 100%; height: 440px; border: 0; display: block; background: #fff; }
.jv-canvas-loading { padding: 26px 14px; text-align: center; font-size: 12.5px; color: var(--text-3); }

/* markdown content → the imported design's table look */
.jv-md :deep(.jv-md-p) { margin: 0 0 10px; }
.jv-md :deep(.jv-md-p:last-child) { margin-bottom: 0; }
.jv-md :deep(.jv-md-list) { margin: 0 0 10px; padding-left: 20px; }
.jv-md :deep(.jv-md-list li) { margin: 2px 0; }
.jv-md :deep(.jv-md-code) { background: var(--surface-2); padding: 1px 5px; border-radius: 4px; font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.jv-md :deep(.jv-md-link) { color: var(--blue); text-decoration: none; font-weight: 500; }
.jv-md :deep(.jv-md-tablewrap) { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; margin: 4px 0 10px; }
.jv-md :deep(.jv-md-table) { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.jv-md :deep(.jv-md-table th) { padding: 8px 13px; font-weight: 550; color: var(--text-3); background: var(--surface-1); border-bottom: 1px solid var(--border); }
.jv-md :deep(.jv-md-table td) { padding: 9px 13px; border-bottom: 1px solid var(--border); color: var(--text); font-variant-numeric: tabular-nums; }
.jv-md :deep(.jv-md-table tr:last-child td) { border-bottom: 0; }
</style>
