<template>
	<div ref="rootEl" class="jv-root" :class="{ 'jv-dark': effectiveDark }" :style="paletteVars" style="--rad:8px;font-family:'Inter',system-ui,sans-serif;height:100vh;width:100%;display:flex;color:var(--text);background:var(--surface);overflow:hidden;position:relative;">

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
				<button class="jv-newchat" @click="newChat" style="width:100%;display:flex;align-items:center;gap:8px;padding:8px 11px;background:var(--blue);color:#fff;border:none;border-radius:var(--rad);font-family:inherit;font-size:13px;font-weight:550;cursor:pointer;">
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
							<span style="font-size:12px;color:var(--text-2);font-weight:500;">{{ modelLabel }}</span>
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
					<button class="jv-iconbtn-bd" @click="openSettings" title="Settings" style="width:32px;height:32px;display:flex;align-items:center;justify-content:center;background:var(--surface);border:1px solid var(--border);border-radius:7px;cursor:pointer;">
						<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
					</button>
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
								<!-- rich outputs: agent artifacts rendered by type (sandboxed) -->
								<div v-for="cv in (m.canvas || [])" :key="cv.name" class="jv-canvas">
									<div class="jv-canvas-bar">
										<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18" /><path d="M18 9l-5 5-3-3-4 4" /></svg>
										<span>{{ cv.title }}</span>
										<span class="jv-canvas-type">{{ cv.type }}</span>
										<a v-if="cvOf(m, cv) && cv.type !== 'html' && cv.type !== 'svg'" :href="cvOf(m, cv)" :download="cvFile(cv)" class="jv-canvas-dl">Download</a>
									</div>
									<template v-if="cvOf(m, cv)">
										<!-- html / svg → sandboxed iframe srcdoc -->
										<iframe v-if="cv.type === 'html' || cv.type === 'svg'" :srcdoc="cvOf(m, cv)" sandbox="allow-scripts allow-popups" class="jv-canvas-frame" loading="lazy" title="Jarvis artifact"></iframe>
										<!-- pdf → browser viewer -->
										<iframe v-else-if="cv.type === 'pdf'" :src="cvOf(m, cv)" class="jv-canvas-frame jv-canvas-pdf" loading="lazy" title="PDF"></iframe>
										<!-- image -->
										<img v-else-if="cv.type === 'image'" :src="cvOf(m, cv)" class="jv-canvas-img" :alt="cv.title" />
										<!-- other files (xlsx/csv/…) → download card -->
										<a v-else :href="cvOf(m, cv)" :download="cvFile(cv)" class="jv-canvas-file">
											<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M12 18v-6M9 15l3 3 3-3" /></svg>
											<span>Download <b>{{ cvFile(cv) }}</b></span>
										</a>
									</template>
									<div v-else class="jv-canvas-loading">Loading {{ cv.title }}…</div>
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
							<!-- the single tool running right now -->
							<div v-if="currentTool" :key="currentTool.id" class="jv-toolrow">
								<svg class="jv-spin" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--blue)" stroke-width="2.4" stroke-linecap="round"><path d="M12 3a9 9 0 1 0 9 9" /></svg>
								<span>Running <b>{{ currentTool.name }}</b></span>
							</div>
							<!-- compact tally of tools finished this turn -->
							<div v-if="doneCount" class="jv-toolrow jv-tooldone">
								<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
								<span>{{ doneCount }} tool{{ doneCount === 1 ? "" : "s" }} done<template v-if="failedCount"> · {{ failedCount }} failed</template></span>
							</div>
							<div v-if="waiting && !currentTool" style="display:flex;align-items:center;gap:7px;padding-top:4px;">
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
							<button v-if="busy" @click="stopRun" title="Stop generating" style="width:32px;height:32px;display:flex;align-items:center;justify-content:center;background:var(--blue);border:none;border-radius:8px;cursor:pointer;">
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

		<!-- ============ SETTINGS (openclaw-style console) ============ -->
		<transition name="jv-fade">
			<div v-if="settingsOpen" class="jv-settings-overlay" @click.self="settingsOpen = false">
				<div class="jv-settings">
					<div class="jv-settings-head">
						<span style="font-size:15px;font-weight:600;">Settings</span>
						<button class="jv-iconbtn" @click="settingsOpen = false" title="Close" style="width:28px;height:28px;display:flex;align-items:center;justify-content:center;background:transparent;border:none;border-radius:7px;cursor:pointer;color:var(--text-3);">
							<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
						</button>
					</div>
					<div class="jv-settings-tabs">
						<button :class="{ on: settingsTab === 'overview' }" @click="settingsTab = 'overview'">Overview</button>
						<button :class="{ on: settingsTab === 'activity' }" @click="settingsTab = 'activity'">Activity</button>
						<button :class="{ on: settingsTab === 'appearance' }" @click="settingsTab = 'appearance'">Appearance</button>
					</div>
					<div class="jv-settings-body">
						<!-- OVERVIEW -->
						<template v-if="settingsTab === 'overview'">
							<div class="jv-set-sec">Connection</div>
							<div class="jv-set-row"><span>Model</span><b>{{ modelLabel }}</b></div>
							<div class="jv-set-row"><span>Provider</span><b>{{ ui.llm_provider || "—" }}</b></div>
							<div class="jv-set-row"><span>Auth mode</span><b>{{ ui.llm_auth_mode || "—" }}</b></div>
							<div class="jv-set-row"><span>Status</span><b style="color:var(--green);">Live</b></div>
							<div class="jv-set-sec" style="margin-top:18px;">Workspace</div>
							<div class="jv-set-row"><span>Conversations</span><b>{{ convCount }}</b></div>
							<div class="jv-set-row"><span>Messages in this chat</span><b>{{ msgCount }}</b></div>
							<div class="jv-set-row"><span>Tool calls this session</span><b>{{ sessionToolCalls }}</b></div>
							<div class="jv-set-row"><span>Tools available</span><b>{{ toolCount }}</b></div>
							<div class="jv-set-sec" style="margin-top:18px;display:flex;align-items:center;gap:7px;">Token usage <span class="jv-est">est.</span></div>
							<div class="jv-set-row"><span>This chat</span><b>{{ usage ? fmtTokens(usage.chat_tokens) : "—" }}</b></div>
							<div class="jv-set-row"><span>{{ usage ? usage.month_label : "This month" }}</span><b>{{ usage ? fmtTokens(usage.month_tokens) : "—" }}</b></div>
							<div class="jv-set-row"><span>All time</span><b>{{ usage ? fmtTokens(usage.total_tokens) : "—" }}</b></div>
							<template v-if="usage && usage.budget_monthly">
								<div class="jv-usage-bar"><div class="jv-usage-fill" :style="{ width: usagePct + '%' }"></div></div>
								<div class="jv-set-hint">{{ fmtTokens(usage.month_tokens) }} / {{ fmtTokens(usage.budget_monthly) }} this month · {{ usagePct }}%</div>
							</template>
							<div v-else class="jv-set-hint">No monthly budget set · counts are estimated from message text.</div>
						</template>
						<!-- ACTIVITY -->
						<template v-else-if="settingsTab === 'activity'">
							<div class="jv-set-sec">Recent tool runs</div>
							<div v-if="!recentActivity.length" class="jv-set-empty">No tool activity in this chat yet.</div>
							<div v-for="(a, i) in recentActivity" :key="i" class="jv-act">
								<div class="jv-act-top">
									<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 1 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" /></svg>
									<span>{{ a.tools }} tool{{ a.tools === 1 ? "" : "s" }}</span>
									<span class="jv-act-ms">{{ (a.ms / 1000).toFixed(1) }}s</span>
								</div>
								<div v-if="a.names.length" class="jv-act-names">{{ a.names.join(" · ") }}</div>
							</div>
						</template>
						<!-- APPEARANCE -->
						<template v-else>
							<div class="jv-set-sec">Theme</div>
							<div class="jv-seg">
								<button :class="{ on: theme === 'light' }" @click="setTheme('light')">
									<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
									Light
								</button>
								<button :class="{ on: theme === 'dark' }" @click="setTheme('dark')">
									<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
									Dark
								</button>
								<button :class="{ on: theme === 'system' }" @click="setTheme('system')">
									<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></svg>
									System
								</button>
							</div>
							<div class="jv-set-hint">{{ theme === "system" ? (effectiveDark ? "Following system · dark" : "Following system · light") : "Saved on this device" }}</div>

							<div class="jv-set-sec" style="margin-top:22px;">Conversation</div>
							<button class="jv-danger" @click="deleteChat" :disabled="!currentId">
								<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6" /></svg>
								Delete this chat
							</button>

							<div class="jv-set-sec" style="margin-top:22px;">About</div>
							<div class="jv-set-row"><span>Jarvis</span><b>ERPNext Assistant</b></div>
						</template>
					</div>
				</div>
			</div>
		</transition>
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

// ---- settings panel + theme (openclaw-style console) ----
const settingsOpen = ref(false)
const settingsTab = ref("overview")
const usage = ref(null) // { estimated, chat_tokens, month_tokens, total_tokens, budget_monthly, month_label }
// Compact token count: 1234 → "1.2k", 2_500_000 → "2.5M".
function fmtTokens(n) {
	n = Number(n || 0)
	if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M"
	if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "k"
	return String(n)
}
const usagePct = computed(() => {
	const u = usage.value
	if (!u || !u.budget_monthly) return 0
	return Math.min(100, Math.round((u.month_tokens / u.budget_monthly) * 100))
})
// theme: 'light' | 'dark' | 'system' — persisted per-device (a browser/device
// preference; no migration needed). 'system' follows the OS color scheme live.
const theme = ref(localStorage.getItem("jarvis-theme") || "system")
const prefersDark = ref(false)
let _mq = null
function onColorScheme(e) {
	prefersDark.value = e.matches
}
const effectiveDark = computed(
	() => theme.value === "dark" || (theme.value === "system" && prefersDark.value),
)
const LIGHT_VARS = {
	"--surface": "#ffffff", "--surface-1": "#f7f7f8", "--surface-2": "#f1f1f3", "--surface-3": "#ececef",
	"--border": "#e8e8ec", "--border-2": "#dfdfe4",
	"--text": "#171717", "--text-2": "#4a4a4f", "--text-3": "#83838b",
	"--blue": "#171717", "--blue-bg": "#eff4ff", "--blue-bd": "#d6e2fb",
	"--green": "#16a34a", "--green-bg": "#edf8f0", "--green-bd": "#cdeed8",
	"--red": "#dc2626", "--red-bg": "#fdf0ef", "--red-bd": "#f5d4d1",
	"--amber": "#d97706", "--amber-bg": "#fdf6ec", "--amber-bd": "#f3e2c2",
}
const DARK_VARS = {
	"--surface": "#16161a", "--surface-1": "#1d1d22", "--surface-2": "#26262d", "--surface-3": "#30303a",
	"--border": "#2c2c34", "--border-2": "#3a3a45",
	"--text": "#ededf2", "--text-2": "#b6b6c0", "--text-3": "#7e7e8a",
	"--blue": "#5b7cfa", "--blue-bg": "#1c2545", "--blue-bd": "#2c3a66",
	"--green": "#34d399", "--green-bg": "#15271f", "--green-bd": "#214b38",
	"--red": "#f87171", "--red-bg": "#2a1818", "--red-bd": "#4a2a2a",
	"--amber": "#fbbf24", "--amber-bg": "#2a2315", "--amber-bd": "#4a3d1f",
}
const paletteVars = computed(() => (effectiveDark.value ? DARK_VARS : LIGHT_VARS))

function setTheme(t) {
	theme.value = t
	try {
		localStorage.setItem("jarvis-theme", t)
	} catch (e) {
		/* private mode / storage disabled — keep the in-memory choice */
	}
}
async function openSettings() {
	userMenuOpen.value = false
	modelMenuOpen.value = false
	settingsOpen.value = true
	try {
		usage.value = await api.getUsage(currentId.value)
	} catch (e) {
		/* usage stays null → the section shows a dash */
	}
}
async function deleteChat() {
	const id = currentId.value
	if (!id) return
	if (!window.confirm("Delete this chat? It will be removed from your history.")) return
	try {
		await api.archiveConversation(id)
	} catch (e) {
		/* ignore — reload below reflects the true state either way */
	}
	settingsOpen.value = false
	currentId.value = null
	messages.value = []
	await loadConversations()
	const first = conversations.value[0]?.name
	if (first) {
		currentId.value = first
		await loadConversation(first)
	}
}

// Phase 1: streaming/metrics, live tool activity, file input, mentions, stop
const runStartMs = ref(0)
const currentRunId = ref(null)
const stoppedRunId = ref(null)
const activeTools = ref([]) // [{ id, name, status }] for the in-flight run
// Live activity shows ONE tool at a time: the most-recently-started tool that's
// still running, plus a compact count of the ones already finished this turn.
const currentTool = computed(
	() => [...activeTools.value].reverse().find((t) => t.status === "running") || null,
)
const doneCount = computed(() => activeTools.value.filter((t) => t.status !== "running").length)
const failedCount = computed(() => activeTools.value.filter((t) => t.status === "error").length)
const runMeta = ref({}) // { [message_id]: { ms, tools, names } } — survives reloads
const canvasContent = ref({}) // { `${msgName}::${canvasName}`: srcdoc html (html/svg) | data-url (pdf/image/file) }
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

// settings/overview derived metrics (all from data we already hold)
const convCount = computed(() => conversations.value.length)
const msgCount = computed(() => visibleMessages.value.length)
const toolCount = computed(() => JARVIS_TOOLS.length)
const sessionToolCalls = computed(() =>
	Object.values(runMeta.value).reduce((s, r) => s + (r.tools || 0), 0),
)
// Recent tool runs in this chat (most recent first), from the per-message run
// metrics we already stamp on run:end.
const recentActivity = computed(() => {
	const out = []
	for (const m of visibleMessages.value) {
		const meta = runMeta.value[m.name]
		if (m.role === "assistant" && meta && meta.tools) {
			out.push({ tools: meta.tools, ms: meta.ms || 0, names: meta.names || [] })
		}
	}
	return out.reverse()
})
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
// Cached render payload for an artifact: HTML srcdoc (html/svg) or a base64
// data-url (pdf/image/file). Keyed by `${msgName}::${canvasName}`.
function cvOf(m, cv) {
	return canvasContent.value[m.name + "::" + cv.name]
}
// Basename (with extension) for a download filename / file card label.
function cvFile(cv) {
	return (cv.name || "file").split("/").pop()
}
// Lazily fetch each artifact's render payload (srcdoc content for html/svg, a
// data-url for pdf/image/file) and cache it.
async function ensureCanvas(m) {
	if (!m || !Array.isArray(m.canvas) || !m.canvas.length) return
	for (const cv of m.canvas) {
		const key = m.name + "::" + cv.name
		if (canvasContent.value[key]) continue
		try {
			const r = await api.getCanvas(m.name, cv.name)
			const payload = r && (r.content || r.data_url)
			if (payload) canvasContent.value = { ...canvasContent.value, [key]: payload }
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
	processMermaid()
}

// Render any ```mermaid blocks (the agent's inline pie/flow charts) into SVG.
// Lazy-loads mermaid so it never bloats the initial bundle; only runs on
// finalized messages (mid-stream mermaid source is incomplete and would error).
let _mermaid = null
async function processMermaid() {
	const nodes = rootEl.value?.querySelectorAll?.(".jv-mermaid:not([data-rendered])")
	if (!nodes || !nodes.length) return
	try {
		if (!_mermaid) {
			_mermaid = (await import("mermaid")).default
			_mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral" })
		}
	} catch (e) {
		return
	}
	let n = 0
	for (const el of nodes) {
		const src = (el.textContent || "").trim()
		el.setAttribute("data-rendered", "1")
		if (!src) continue
		try {
			const { svg } = await _mermaid.render(`jvmmd-${n++}-${Math.floor(performance.now())}`, src)
			el.innerHTML = svg
		} catch (e) {
			el.setAttribute("data-rendered", "err") // leave source visible on parse error
		}
	}
	nextTick(scrollBottom)
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
	// Track the OS color scheme so theme:'system' updates live.
	_mq = window.matchMedia("(prefers-color-scheme: dark)")
	prefersDark.value = _mq.matches
	_mq.addEventListener("change", onColorScheme)
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
	_mq?.removeEventListener("change", onColorScheme)
})
</script>

<style scoped>
.jv-newchat:hover { filter: brightness(0.9); }
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
.jv-tooldone { color: var(--text-3); font-size: 12px; }
.jv-spin { animation: jv-spin 0.8s linear infinite; }
@keyframes jv-spin { to { transform: rotate(360deg); } }

/* inline canvas/chart artifacts (rendered sandboxed) */
.jv-canvas { margin-top: 12px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--surface); }
.jv-canvas-bar { display: flex; align-items: center; gap: 7px; padding: 8px 12px; font-size: 12.5px; font-weight: 550; color: var(--text-2); background: var(--surface-1); border-bottom: 1px solid var(--border); }
.jv-canvas-bar svg { color: var(--text-3); flex: none; }
.jv-canvas-type { margin-left: auto; font-size: 10px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; }
.jv-canvas-frame { width: 100%; height: 440px; border: 0; display: block; background: #fff; }
.jv-canvas-pdf { height: 560px; }
.jv-canvas-img { display: block; max-width: 100%; height: auto; margin: 0 auto; background: #fff; }
.jv-canvas-loading { padding: 26px 14px; text-align: center; font-size: 12.5px; color: var(--text-3); }
.jv-canvas-dl { margin-left: auto; font-size: 11px; font-weight: 600; color: var(--blue); text-decoration: none; padding: 2px 8px; border: 1px solid var(--border); border-radius: 6px; }
.jv-canvas-dl:hover { background: var(--surface-1); }
.jv-canvas-file { display: flex; align-items: center; gap: 10px; padding: 16px 16px; color: var(--text-2); text-decoration: none; font-size: 13px; }
.jv-canvas-file svg { color: var(--text-3); flex: none; }
.jv-canvas-file:hover { background: var(--surface-1); }
.jv-canvas-file b { font-weight: 600; color: var(--text); }
/* mermaid diagrams + fenced code blocks in markdown */
.jv-md :deep(.jv-mermaid) { margin: 8px 0 12px; text-align: center; overflow-x: auto; }
.jv-md :deep(.jv-mermaid svg) { max-width: 100%; height: auto; }
.jv-md :deep(.jv-md-pre) { margin: 6px 0 12px; padding: 12px 14px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; overflow-x: auto; }
.jv-md :deep(.jv-md-pre code) { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--text); white-space: pre; }

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

/* ===== settings panel (slide-over console) ===== */
.jv-settings-overlay { position: absolute; inset: 0; z-index: 60; background: rgba(15, 15, 22, 0.32); display: flex; justify-content: flex-end; }
.jv-dark .jv-settings-overlay { background: rgba(0, 0, 0, 0.5); }
.jv-settings { width: 372px; max-width: 92vw; height: 100%; background: var(--surface); border-left: 1px solid var(--border); display: flex; flex-direction: column; box-shadow: -12px 0 40px rgba(20, 20, 30, 0.16); animation: jv-slidein 0.18s ease; }
@keyframes jv-slidein { from { transform: translateX(24px); opacity: 0.4; } to { transform: translateX(0); opacity: 1; } }
.jv-settings-head { display: flex; align-items: center; justify-content: space-between; padding: 15px 18px; border-bottom: 1px solid var(--border); }
.jv-settings-tabs { display: flex; gap: 2px; padding: 8px 12px 0; border-bottom: 1px solid var(--border); }
.jv-settings-tabs button { flex: 1; padding: 8px 6px 10px; background: transparent; border: none; border-bottom: 2px solid transparent; font-family: inherit; font-size: 12.5px; font-weight: 550; color: var(--text-3); cursor: pointer; }
.jv-settings-tabs button:hover { color: var(--text-2); }
.jv-settings-tabs button.on { color: var(--text); border-bottom-color: var(--blue); }
.jv-settings-body { flex: 1; overflow-y: auto; padding: 16px 18px 28px; }
.jv-set-sec { font-size: 11px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; margin: 0 0 8px; }
.jv-set-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--border); font-size: 13px; color: var(--text-2); }
.jv-set-row:last-child { border-bottom: 0; }
.jv-set-row b { font-weight: 600; color: var(--text); text-align: right; }
.jv-set-empty { font-size: 12.5px; color: var(--text-3); padding: 14px 0; }
.jv-set-hint { font-size: 11.5px; color: var(--text-3); margin-top: 9px; }
.jv-est { font-size: 9.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; }
.jv-usage-bar { margin-top: 12px; height: 7px; border-radius: 99px; background: var(--surface-2); overflow: hidden; }
.jv-usage-fill { height: 100%; border-radius: 99px; background: var(--blue); transition: width .25s ease; }
/* theme segmented control */
.jv-seg { display: flex; gap: 6px; }
.jv-seg button { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 5px; padding: 11px 6px; background: var(--surface-1); border: 1px solid var(--border); border-radius: 9px; font-family: inherit; font-size: 11.5px; font-weight: 550; color: var(--text-2); cursor: pointer; transition: border-color .12s, background .12s, color .12s; }
.jv-seg button:hover { border-color: var(--border-2); }
.jv-seg button.on { border-color: var(--blue); color: var(--text); background: var(--blue-bg); }
.jv-seg button svg { color: var(--text-3); }
.jv-seg button.on svg { color: var(--blue); }
/* danger / delete */
.jv-danger { display: flex; align-items: center; gap: 8px; width: 100%; justify-content: center; padding: 9px 12px; background: var(--red-bg); border: 1px solid var(--red-bd); border-radius: 9px; font-family: inherit; font-size: 13px; font-weight: 550; color: var(--red); cursor: pointer; }
.jv-danger:hover:not(:disabled) { filter: brightness(0.97); }
.jv-danger:disabled { opacity: 0.5; cursor: default; }
/* activity rows */
.jv-act { padding: 10px 0; border-bottom: 1px solid var(--border); }
.jv-act:last-child { border-bottom: 0; }
.jv-act-top { display: flex; align-items: center; gap: 7px; font-size: 12.5px; font-weight: 550; color: var(--text-2); }
.jv-act-ms { margin-left: auto; font-variant-numeric: tabular-nums; color: var(--text-3); font-weight: 500; }
.jv-act-names { font-size: 11.5px; color: var(--text-3); margin-top: 3px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-word; }
/* fade for the overlay */
.jv-fade-enter-active, .jv-fade-leave-active { transition: opacity .16s ease; }
.jv-fade-enter-from, .jv-fade-leave-to { opacity: 0; }
</style>
