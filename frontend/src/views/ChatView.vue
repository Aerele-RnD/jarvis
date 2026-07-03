<template>
	<div ref="rootEl" class="jv-root" :class="{ 'jv-dark': effectiveDark }" :style="paletteVars" style="--rad:8px;font-family:'Inter',system-ui,sans-serif;height:100vh;width:100%;display:flex;color:var(--text);background:var(--surface);overflow:hidden;position:relative;">

		<!-- ============ SIDEBAR ============ -->
		<aside class="jv-sidebar" :class="{ collapsed: sidebarCollapsed }" style="width:268px;flex:none;background:var(--surface-1);border-right:1px solid var(--border);display:flex;flex-direction:column;height:100%;">
			<!-- Collapsed: slim icon rail (instead of hiding the sidebar entirely) -->
			<div v-if="sidebarCollapsed" class="jv-rail">
				<div class="jv-rail-logo"><svg width="16" height="16" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg></div>
				<button class="jv-rail-btn" @click="toggleSidebar" title="Expand sidebar">
					<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M9 3v18" /><path d="m11 9 3 3-3 3" /></svg>
				</button>
				<button class="jv-rail-btn jv-rail-new" @click="newChat" title="New chat">
					<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
				</button>
				<button class="jv-rail-btn" @click="toggleSidebar" title="Search chats">
					<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
				</button>
				<div style="flex:1;"></div>
				<button class="jv-rail-btn" @click="openSettings" title="Settings">
					<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
				</button>
				<div class="jv-rail-avatar" @click="toggleSidebar" title="Account">{{ initials }}</div>
			</div>
			<div style="padding:14px 14px 10px;display:flex;align-items:center;gap:9px;">
				<div class="jv-logo" style="width:28px;height:28px;border-radius:7px;background:var(--blue);display:flex;align-items:center;justify-content:center;flex:none;box-shadow:0 1px 2px rgba(37,99,235,.35);">
					<svg width="16" height="16" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg>
				</div>
				<div style="display:flex;flex-direction:column;line-height:1.1;">
					<span style="font-size:14px;font-weight:600;letter-spacing:-.01em;">Jarvis</span>
					<span style="font-size:11px;color:var(--text-3);font-weight:450;">ERPNext Assistant</span>
				</div>
				<div style="margin-left:auto;display:flex;align-items:center;gap:6px;">
					<button class="jv-iconbtn" @click="toggleSidebar" title="Collapse sidebar" style="width:26px;height:26px;display:flex;align-items:center;justify-content:center;background:transparent;border:none;border-radius:6px;cursor:pointer;color:var(--text-3);flex:none;">
						<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M9 3v18" /><path d="m14 9-3 3 3 3" /></svg>
					</button>
				</div>
			</div>

			<div style="padding:6px 12px 10px;">
				<button class="jv-newchat" @click="newChat" style="width:100%;display:flex;align-items:center;justify-content:center;gap:8px;padding:8px 11px;background:var(--blue);color:#fff;border:none;border-radius:var(--rad);font-family:inherit;font-size:13px;font-weight:550;cursor:pointer;">
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
						@click="renamingId === c.name ? null : selectConversation(c.name)"
>
						<svg class="jv-conv-ic" width="14" height="14" viewBox="0 0 24 24" fill="none" :stroke="c.name === currentId ? 'var(--text-2)' : 'var(--text-3)'" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
						<input v-if="renamingId === c.name" class="jv-rename-input" v-model="renameText" @click.stop @keydown.enter.stop="commitRename(c)" @keydown.esc.stop="cancelRename()" @blur="commitRename(c)" />
						<span v-else class="jv-conv-title">{{ c.title || "New chat" }}</span>
						<button v-if="renamingId !== c.name" class="jv-conv-more" @click.stop="toggleConvMenu(c.name)" title="Options"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></svg></button>
						<div v-if="convMenuFor === c.name" class="jv-conv-menu" @click.stop>
							<button class="jv-menuitem" @click="toggleStar(c)"><svg width="14" height="14" viewBox="0 0 24 24" :fill="c.starred ? 'var(--amber)' : 'none'" :stroke="c.starred ? 'var(--amber)' : 'currentColor'" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg><span>{{ c.starred ? "Remove" : "Star" }}</span></button>
							<button class="jv-menuitem" @click="startRename(c)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg><span>Rename</span></button>
							<button class="jv-menuitem jv-menuitem-danger" @click="deleteConv(c)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg><span>Delete</span></button>
						</div>
					</div>
				</template>
				<div v-if="!conversations.length" style="padding:18px 10px;text-align:center;font-size:12.5px;color:var(--text-3);">No chats yet</div>
			</nav>

			<div class="jv-usermenu-wrap" style="position:relative;border-top:1px solid var(--border);">
				<div v-if="userMenuOpen" style="position:absolute;bottom:calc(100% + 6px);left:12px;right:12px;background:var(--surface);border:1px solid var(--border-2);border-radius:10px;box-shadow:0 10px 28px rgba(20,20,30,.16);padding:5px;z-index:20;">
					<button class="jv-menuitem" @click="openSettings(); userMenuOpen = false">
						<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
						<span>Settings</span>
					</button>
					<button class="jv-menuitem" @click="goDesk">
						<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /></svg>
						<span>Switch to Desk</span>
					</button>
					<button class="jv-menuitem" @click="session.logout()">
						<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" /></svg>
						<span style="color:var(--red);">Log out</span>
					</button>
				</div>
				<div class="jv-usercard" @click="userMenuOpen = !userMenuOpen" style="padding:10px 12px;display:flex;align-items:center;gap:9px;cursor:pointer;">
					<div style="width:28px;height:28px;border-radius:50%;background:#e7ddcf;color:#8a6d3b;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;flex:none;">{{ initials }}</div>
					<div style="display:flex;flex-direction:column;line-height:1.2;min-width:0;">
						<span style="font-size:12.5px;font-weight:550;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ fullName }}</span>
						<span style="font-size:11px;color:var(--text-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ session.user }}</span>
					</div>
					<button class="jv-iconbtn" tabindex="-1" title="Account" style="margin-left:auto;flex:none;width:26px;height:26px;display:flex;align-items:center;justify-content:center;background:transparent;border:none;border-radius:6px;cursor:pointer;pointer-events:none;">
						<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM12 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4z" /></svg>
					</button>
				</div>
			</div>
		</aside>

		<!-- ============ MAIN ============ -->
		<main style="flex:1;display:flex;flex-direction:column;height:100%;min-width:0;background:var(--surface);">
			<header style="height:52px;flex:none;border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 18px;gap:12px;">
				<button v-if="sidebarCollapsed" class="jv-iconbtn-bd" @click="toggleSidebar" title="Expand sidebar" style="width:32px;height:32px;display:flex;align-items:center;justify-content:center;background:var(--surface);border:1px solid var(--border);border-radius:7px;cursor:pointer;flex:none;">
					<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M9 3v18" /><path d="m11 9 3 3-3 3" /></svg>
				</button>
				<div style="display:flex;flex-direction:column;line-height:1.15;min-width:0;">
					<span style="font-size:14px;font-weight:600;letter-spacing:-.01em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ currentTitle }}</span>
					<span style="font-size:11.5px;color:var(--text-3);">{{ headerSub }}</span>
				</div>
				<div style="margin-left:auto;display:flex;align-items:center;gap:8px;">
					<!-- Save the current conversation's prompts as a reusable macro -->
					<button v-if="canSaveAsMacro" class="jv-modelpill" @click="saveConversationAsMacro" title="Save this chat's prompts as a macro" style="display:flex;align-items:center;gap:7px;padding:5px 10px;background:var(--surface-1);border:1px solid var(--border);border-radius:20px;cursor:pointer;font-family:inherit;">
						<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M5 3l14 9-14 9V3z" /></svg>
						<span style="font-size:12px;color:var(--text-2);font-weight:500;">Save as macro</span>
					</button>
					<!-- Model picker: switch the LLM model for this conversation -->
					<div class="jv-modelmenu-wrap" style="position:relative;">
						<button class="jv-modelpill" @click="modelMenuOpen = !modelMenuOpen" :title="availableModels.length ? 'Switch model' : 'Connected to ERPNext'" style="display:flex;align-items:center;gap:7px;padding:5px 10px;background:var(--surface-1);border:1px solid var(--border);border-radius:20px;cursor:pointer;font-family:inherit;">
							<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5" /><path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3" /></svg>
							<span style="font-size:12px;color:var(--text-2);font-weight:500;">{{ modelLabel }}</span>
							<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6" /></svg>
						</button>
						<div v-if="modelMenuOpen && availableModels.length" style="position:absolute;top:calc(100% + 6px);right:0;min-width:198px;background:var(--surface);border:1px solid var(--border-2);border-radius:10px;box-shadow:0 8px 24px rgba(20,20,30,.14);padding:5px;z-index:30;">
							<!-- Auto: its own separate option (let Jarvis pick), divided from the explicit models -->
							<button class="jv-menuitem" :class="{ on: !modelOverride }" @click="selectModel('')">
								<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="flex:none;"><path d="M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8" /></svg>
								<span style="flex:1;">Auto <span style="color:var(--text-3);font-weight:450;">· {{ ui.llm_model || "default" }}</span></span>
								<svg v-if="!modelOverride" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="flex:none;"><path d="M20 6 9 17l-5-5" /></svg>
							</button>
							<div style="height:1px;background:var(--border);margin:5px 2px;"></div>
							<div style="padding:3px 9px 6px;font-size:10px;color:var(--text-3);font-weight:600;text-transform:uppercase;letter-spacing:.03em;">Model · {{ ui.llm_provider }}</div>
							<button v-for="m in availableModels" :key="m" class="jv-menuitem" :class="{ on: m === modelOverride }" @click="selectModel(m)">
								<span style="flex:1;">{{ m }}</span>
								<svg v-if="m === modelOverride" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="flex:none;"><path d="M20 6 9 17l-5-5" /></svg>
							</button>
						</div>
					</div>
					<button class="jv-iconbtn-bd" @click="toggleTheme" :title="effectiveDark ? 'Switch to light theme' : 'Switch to dark theme'" style="width:32px;height:32px;display:flex;align-items:center;justify-content:center;background:var(--surface);border:1px solid var(--border);border-radius:7px;cursor:pointer;">
						<svg v-if="effectiveDark" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
						<svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
					</button>
					<button class="jv-iconbtn-bd" @click="openErpDesk" title="Open ERPNext Desk (new tab)" style="width:32px;height:32px;display:flex;align-items:center;justify-content:center;background:var(--surface);border:1px solid var(--border);border-radius:7px;cursor:pointer;">
						<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><path d="M15 3h6v6M10 14 21 3" /></svg>
					</button>
				</div>
			</header>

			<!-- initial load: a quiet spinner so the welcome screen doesn't flash
			     before the open conversation finishes loading on refresh -->
			<div v-if="booting" style="flex:1;display:flex;align-items:center;justify-content:center;">
				<svg class="jv-spin" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="2.4" stroke-linecap="round"><path d="M12 3a9 9 0 1 0 9 9" /></svg>
			</div>
			<!-- ===== WELCOME ===== -->
			<div v-else-if="showWelcome" style="flex:1;overflow-y:auto;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:32px;">
				<div style="width:100%;max-width:680px;text-align:center;">
					<div class="jv-logo" style="width:52px;height:52px;border-radius:13px;background:var(--blue);display:flex;align-items:center;justify-content:center;margin:0 auto 18px;box-shadow:0 4px 14px rgba(37,99,235,.28);">
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
			<div v-else ref="threadEl" @scroll.passive="onThreadScroll" style="flex:1;overflow-y:auto;">
				<div ref="threadInnerEl" style="max-width:1280px;margin:0 auto;padding:26px 40px 36px;display:flex;flex-direction:column;gap:26px;">
					<!-- macro run progress banner -->
					<div v-if="macroRun && macroRun.conversation === currentId" class="jv-macrobar" :class="{ ok: macroRun.status === 'completed', err: macroRun.status === 'failed', stopped: macroRun.status === 'stopped' }">
						<template v-if="macroRun.status === 'running'">
							<span class="jv-macrobar-dot spin"></span>
							<span class="jv-macrobar-txt">Running macro — step {{ macroRun.step }}/{{ macroRun.total }}<template v-if="macroRun.label">: {{ macroRun.label }}</template></span>
							<button class="jv-macrobar-stop" @click="stopMacro">Stop</button>
						</template>
						<template v-else-if="macroRun.status === 'completed'"><span class="jv-macrobar-chip">✓ Macro completed</span></template>
						<template v-else-if="macroRun.status === 'failed'"><span class="jv-macrobar-chip">✗ Macro failed</span></template>
						<template v-else-if="macroRun.status === 'stopped'"><span class="jv-macrobar-chip">⏹ Macro stopped</span></template>
					</div>
					<template v-for="m in visibleMessages" :key="m.name">
						<!-- user -->
						<div v-if="m.role === 'user'" class="jv-umsg" style="display:flex;flex-direction:column;align-items:flex-end;">
							<div v-if="m.content" style="max-width:78%;background:var(--surface-2);border:1px solid var(--border);border-radius:14px 14px 4px 14px;padding:10px 14px;font-size:14px;line-height:1.5;color:var(--text);white-space:pre-wrap;">{{ m.content }}</div>
							<!-- attached images → same clickable thumbnail + preview as generated ones -->
							<template v-for="cv in (m.canvas || [])" :key="cv.name">
								<button v-if="cv.type === 'image' && cv.file_url" class="jv-img-artifact" @click="openArtifact(m, cv)" :title="'Open ' + cv.title" style="margin-top:8px;cursor:zoom-in;">
									<img :src="cv.file_url" :alt="cv.title" loading="lazy" />
								</button>
							</template>
							<div class="jv-msgbar">
								<button class="jv-msgbtn" @click="copyMsg(m.name, m.content)" :title="copiedId === m.name ? 'Copied' : 'Copy'">
									<svg v-if="copiedId === m.name" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
									<svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
								</button>
								<button class="jv-msgbtn" @click="editCommand(m)" title="Edit & resend">
									<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
								</button>
							</div>
						</div>
						<!-- assistant -->
						<div v-else class="jv-amsg" style="display:flex;gap:12px;">
							<div class="jv-logo" style="width:28px;height:28px;flex:none;border-radius:7px;background:var(--blue);display:flex;align-items:center;justify-content:center;margin-top:2px;">
								<svg width="15" height="15" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg>
							</div>
							<div style="flex:1;min-width:0;">
								<!-- Activity: the tool calls (with input + output) that produced
								     this answer — openclaw-style, collapsible. -->
								<div v-if="showActivityDetail && (activityByAssistant[m.name] || []).length" class="jv-activity">
									<button class="jv-activity-head" @click="toggleActivity(m.name)" :aria-expanded="!!isActivityOpen(m.name)">
										<svg class="jv-activity-chev" :class="{ open: isActivityOpen(m.name) }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6" /></svg>
										<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 1 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" /></svg>
										<span class="jv-activity-count">{{ (activityByAssistant[m.name] || []).length }} tool call{{ (activityByAssistant[m.name] || []).length === 1 ? "" : "s" }}</span>
										<span v-if="!isActivityOpen(m.name)" class="jv-activity-preview">{{ activityNames(m.name) }}</span>
									</button>
									<div v-if="isActivityOpen(m.name)" class="jv-activity-body">
										<div v-for="t in (activityByAssistant[m.name] || [])" :key="t.name" class="jv-tool" :class="{ open: toolOpen[t.name] }">
											<button class="jv-tool-head" @click="toggleTool(t.name)">
												<span class="jv-tool-dot" :class="(t.tool_status === 'completed' ? 'ok' : (t.tool_status === 'running' ? 'run' : 'err'))"></span>
												<span class="jv-tool-name">{{ toolLabel(t.tool_name) }}</span>
												<span class="jv-tool-status">{{ t.tool_status }}</span>
												<svg class="jv-tool-chev" :class="{ open: toolOpen[t.name] }" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6" /></svg>
											</button>
											<div v-if="toolOpen[t.name]" class="jv-tool-detail">
												<template v-if="prettyJson(t.tool_args)">
													<div class="jv-tool-io-k">Input</div>
													<pre class="jv-tool-io">{{ prettyJson(t.tool_args) }}</pre>
												</template>
												<template v-if="prettyJson(t.tool_result)">
													<div class="jv-tool-io-k">Output</div>
													<pre class="jv-tool-io">{{ prettyJson(t.tool_result) }}</pre>
												</template>
											</div>
										</div>
									</div>
								</div>
								<div v-if="m.error" style="border:1px solid var(--red-bd);border-radius:11px;background:var(--red-bg);padding:13px 15px;display:flex;align-items:flex-start;gap:10px;">
									<svg width="17" height="17" style="margin-top:1px;flex:none;" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><path d="M12 9v4M12 17h.01" /></svg>
									<div style="flex:1;">
										<div style="font-size:13.5px;font-weight:600;color:#b42318;">Something went wrong</div>
										<div style="font-size:12.5px;color:#9a3a30;margin-top:2px;line-height:1.5;">{{ m.error }}</div>
										<button class="jv-retry" @click="retry(m.name)" style="margin-top:10px;display:flex;align-items:center;gap:6px;padding:6px 12px;background:var(--red);color:#fff;border:none;border-radius:7px;font-family:inherit;font-size:12px;font-weight:550;cursor:pointer;">Retry</button>
									</div>
								</div>
								<div v-else class="jv-md" style="font-size:14px;line-height:1.6;color:var(--text);" v-html="render(m.content)"></div>
								<!-- rich action card the agent emits (doc confirm / email draft) -->
								<template v-if="actionFor === m.name && activeAction">
									<!-- email draft -->
									<div v-if="activeAction.kind === 'email'" class="jv-email">
										<div class="jv-email-head">
											<div class="jv-email-line"><span class="jv-email-k">To</span><span class="jv-email-v">{{ activeAction.to }}</span></div>
											<div class="jv-email-line"><span class="jv-email-k">Subject</span><span class="jv-email-v jv-email-subj">{{ activeAction.subject }}</span></div>
										</div>
										<div class="jv-email-body">{{ activeAction.body }}</div>
										<div class="jv-action-foot">
											<button class="jv-action-primary" @click="actionSend('Yes, send it.')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13M22 2 15 22l-4-9-9-4 20-7z" /></svg>Send email</button>
											<button class="jv-action-2nd" @click="copyText(activeAction.body)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>Copy</button>
											<button class="jv-action-2nd" @click="actionSend('Regenerate that email, please.')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2v6h6M21 12a9 9 0 1 1-3-6.7L21 8" /></svg>Regenerate</button>
										</div>
									</div>
									<!-- create/update → compact chip; the side panel is the editor -->
									<div v-else-if="!activeAction.verb || activeAction.verb === 'create' || activeAction.verb === 'update'"
									     class="jv-draft-chip" role="button" tabindex="0"
									     @click="openDraftPanel({ verb: activeAction.verb || 'create', ...activeAction })"
									     @keydown.enter="openDraftPanel({ verb: activeAction.verb || 'create', ...activeAction })">
										<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 4v16"/></svg>
										<span><b>{{ activeAction.doctype }}</b> draft<template v-if="draftChipSummary"> · {{ draftChipSummary }}</template></span>
										<span class="jv-draft-chip-cta">Open editor</span>
									</div>
									<!-- submit/cancel/delete/amend → confirm card, but Confirm applies directly (Task 4) -->
									<div v-else class="jv-action">
										<div class="jv-action-head">
											<span class="jv-action-title">{{ actionVerb(activeAction) }} <b>{{ activeAction.doctype }}</b><template v-if="activeAction.name"> · {{ activeAction.name }}</template><template v-else-if="activeAction.title"> · {{ activeAction.title }}</template></span>
										</div>
										<div class="jv-action-fields">
											<div v-for="(f, fi) in (activeAction.fields || [])" :key="fi" class="jv-action-row">
												<span class="jv-action-k">{{ f.label }}</span>
												<span class="jv-action-v">{{ f.value }}</span>
											</div>
										</div>
										<div v-if="confirmError" class="jv-draft-error" style="margin:0 14px 10px">{{ confirmError }}</div>
										<div class="jv-action-foot">
											<button class="jv-action-primary" :disabled="confirmBusy" @click="confirmApply">✓ {{ actionCta(activeAction) }}</button>
											<button class="jv-action-discard" @click="actionSend('No, cancel that.')">Discard</button>
										</div>
									</div>
								</template>
								<!-- confirm / cancel (fallback, simple label) -->
								<div v-else-if="confirmFor === m.name" class="jv-confirm">
									<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--amber)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><path d="M12 9v4M12 17h.01" /></svg>
									<span class="jv-confirm-label">{{ confirmLabel(m) || "Apply this change?" }}</span>
									<button class="jv-confirm-no" @click="answerConfirm(false)">Cancel</button>
									<button class="jv-confirm-yes" @click="answerConfirm(true)">Confirm</button>
								</div>
								<!-- interactive clarifying questions (Claude-style cards; one Submit) -->
								<div v-else-if="askFor === m.name && activeAsk" class="jv-ask">
									<div v-for="(q, qi) in activeAsk.questions" :key="qi" class="jv-ask-q">
										<div class="jv-ask-qt"><span class="jv-ask-num">{{ qi + 1 }}</span>{{ q.q }}</div>
										<!-- yes/no, with optional custom labels (e.g. Approve / Reject) -->
										<div v-if="q.type === 'yesno'" class="jv-ask-opts">
											<button v-for="(lbl, li) in (q.options.length === 2 ? q.options : ['Yes', 'No'])" :key="li" class="jv-ask-opt" :class="{ on: isPicked(qi, lbl) }" @click="pickSingle(qi, lbl)"><span v-if="isPicked(qi, lbl)" class="jv-ask-tick">✓</span>{{ lbl }}</button>
										</div>
										<!-- single / multi choice -->
										<div v-else-if="q.type === 'single' || q.type === 'multi'" class="jv-ask-opts">
											<button v-for="(opt, oi) in q.options" :key="oi" class="jv-ask-opt" :class="{ on: isPicked(qi, opt) }" @click="q.type === 'multi' ? toggleMulti(qi, opt) : pickSingle(qi, opt)"><span v-if="isPicked(qi, opt)" class="jv-ask-tick">✓</span>{{ opt }}</button>
										</div>
										<!-- date / datetime / free text fields -->
										<input v-else-if="q.type === 'date'" type="date" class="jv-ask-field" :value="askSel[qi] || ''" @input="pickSingle(qi, $event.target.value)" />
										<input v-else-if="q.type === 'datetime'" type="datetime-local" class="jv-ask-field" :value="askSel[qi] || ''" @input="pickSingle(qi, $event.target.value)" />
										<input v-else-if="q.type === 'text'" type="text" class="jv-ask-field" :value="askSel[qi] || ''" @input="pickSingle(qi, $event.target.value)" placeholder="Type your answer…" @keydown.enter.prevent />
										<!-- link: search a record of the given DocType -->
										<div v-else-if="q.type === 'link'" class="jv-ask-link">
											<input type="text" class="jv-ask-field" :value="(askLink[qi] && askLink[qi].q != null) ? askLink[qi].q : (askSel[qi] || '')" @input="onLinkSearch(qi, q.doctype, $event.target.value)" @focus="onLinkSearch(qi, q.doctype, (askLink[qi] && askLink[qi].q) || '')" :placeholder="'Search ' + (q.doctype || 'records') + '…'" @keydown.enter.prevent />
											<div v-if="askLink[qi] && askLink[qi].open && (askLink[qi].items || []).length" class="jv-ask-linkmenu">
												<button v-for="(it, ii) in askLink[qi].items" :key="ii" @click="pickLink(qi, it)"><b>{{ it.value }}</b><span v-if="it.label"> · {{ it.label }}</span></button>
											</div>
										</div>
										<!-- Other free-text only for choice questions -->
										<input v-if="q.type === 'single' || q.type === 'multi' || q.type === 'yesno'" class="jv-ask-other" v-model="askOther[qi]" placeholder="Other…" @keydown.enter.prevent />
									</div>
									<div class="jv-ask-foot">
										<button class="jv-ask-submit" :disabled="!askReady" @click="submitAsk">Submit answers</button>
										<span v-if="!askReady" class="jv-ask-hint">Answer each question to continue</span>
									</div>
								</div>
								<!-- record cards: scrollable card strip instead of a wide table -->
								<div v-if="cardsOf(m)" class="jv-cards">
									<div v-if="cardsOf(m).title" class="jv-cards-title">{{ cardsOf(m).title }}</div>
									<div class="jv-cards-strip">
										<div v-for="(c, ci) in cardsOf(m).cards" :key="ci" class="jv-card">
											<a v-if="c.doctype && c.name" :href="`/app/${_deskSlug(c.doctype)}/${encodeURIComponent(c.name)}`" target="_blank" rel="noopener" class="jv-card-title jv-card-link" :title="'Open ' + c.doctype">{{ c.title }}</a>
											<div v-else class="jv-card-title">{{ c.title }}</div>
											<div v-if="c.subtitle" class="jv-card-sub">{{ c.subtitle }}</div>
											<div v-for="(f, fi) in c.fields" :key="fi" class="jv-card-field"><span class="jv-card-k">{{ f.label }}</span><span class="jv-card-v">{{ f.value }}</span></div>
										</div>
									</div>
								</div>
								<!-- save-as-macro card: the agent proposed a reusable macro -->
								<div v-if="macroCardOf(m)" class="jv-macrocard">
									<div class="jv-macrocard-ic"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M5 3l14 9-14 9V3z" /></svg></div>
									<div class="jv-macrocard-txt">
										<span class="jv-macrocard-title">{{ macroCardOf(m).name || "Macro" }}</span>
										<span class="jv-macrocard-sub">{{ macroCardOf(m).steps.length }} step{{ macroCardOf(m).steps.length === 1 ? "" : "s" }}<template v-if="macroCardOf(m).description"> · {{ macroCardOf(m).description }}</template></span>
									</div>
									<button class="jv-macrocard-btn" @click="openMacroFromCard(macroCardOf(m))">Save as macro</button>
								</div>
								<!-- inline charts: ECharts rendered from the agent's jarvis-chart spec -->
								<div v-for="(spec, ci) in chartsOf(m)" :key="'chart' + ci" class="jv-chartwrap">
									<JvChart :spec="spec" :dark="effectiveDark" />
								</div>
								<!-- rich outputs: agent artifacts rendered by type (sandboxed) -->
								<template v-for="cv in (m.canvas || [])" :key="cv.name">
									<!-- generated image → clickable thumbnail (click to enlarge) -->
									<button v-if="cv.type === 'image' && cv.file_url" class="jv-img-artifact" @click="openArtifact(m, cv)" :title="'Open ' + cv.title">
										<img :src="cv.file_url" :alt="cv.title" loading="lazy" />
										<span class="jv-img-artifact-cap"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6M14 10l7-7M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" /></svg>{{ cv.title }}</span>
									</button>
									<!-- everything else → the file card -->
									<button v-else class="jv-artifact" @click="openArtifact(m, cv)" :title="'Open ' + cv.title">
										<span class="jv-artifact-ic" :class="'t-' + cv.type">
											<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></svg>
										</span>
										<span class="jv-artifact-txt">
											<span class="jv-artifact-title">{{ cv.title }}</span>
											<span class="jv-artifact-sub">{{ (cv.type || "file").toUpperCase() }} · open preview</span>
										</span>
										<svg class="jv-artifact-go" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6" /></svg>
									</button>
								</template>
								<div v-if="skillsUsedOf(m).length" class="jv-skillused">
									<span v-for="(sk, si) in skillsUsedOf(m)" :key="si" class="jv-skillused-chip" :title="'This reply used the ' + sk + ' skill'"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 4 7v10l8 5 8-5V7z" /><path d="M12 22V12M12 12 4 7M12 12l8-5" /></svg>{{ sk }}</span>
								</div>
								<div v-if="!m.error && !m.streaming && (toolCountOf(m) || elapsedOf(m))" class="jv-meta">
									<span v-if="toolCountOf(m)" :title="activityNames(m.name)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 1 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" /></svg>{{ toolCountOf(m) }} tool{{ toolCountOf(m) === 1 ? "" : "s" }}</span>
									<span v-if="elapsedOf(m)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>{{ elapsedOf(m) }}s</span>
								</div>
								<div v-if="!m.error && m.content" class="jv-msgbar">
									<button class="jv-msgbtn" @click="copyMsg(m.name, stripBlocks(m.content))" :title="copiedId === m.name ? 'Copied' : 'Copy'">
										<svg v-if="copiedId === m.name" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
										<svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
									</button>
								</div>
							</div>
						</div>
					</template>

					<!-- live tool activity + thinking (Claude Code style) -->
					<div v-if="activeTools.length || waiting" style="display:flex;gap:12px;">
						<div class="jv-logo" style="width:28px;height:28px;flex:none;border-radius:7px;background:var(--blue);display:flex;align-items:center;justify-content:center;margin-top:2px;">
							<svg width="15" height="15" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg>
						</div>
						<div style="flex:1;min-width:0;padding-top:3px;">
							<!-- the single tool running right now -->
							<div v-if="showActivityDetail && currentTool" :key="currentTool.id" class="jv-toolrow">
								<svg class="jv-spin" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--blue)" stroke-width="2.4" stroke-linecap="round"><path d="M12 3a9 9 0 1 0 9 9" /></svg>
								<span>Running <b>{{ currentTool.name }}</b></span>
							</div>
							<!-- compact tally of tools finished this turn -->
							<div v-if="showActivityDetail && doneCount" class="jv-toolrow jv-tooldone">
								<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
								<span>{{ doneCount }} tool{{ doneCount === 1 ? "" : "s" }} done<template v-if="failedCount"> · {{ failedCount }} failed</template></span>
							</div>
							<div v-if="!showActivityDetail || (waiting && !currentTool)" style="display:flex;align-items:center;gap:7px;padding-top:4px;">
								<span style="display:flex;gap:4px;">
									<span style="width:6px;height:6px;border-radius:50%;background:var(--text-3);animation:jv-dot 1.1s infinite;"></span>
									<span style="width:6px;height:6px;border-radius:50%;background:var(--text-3);animation:jv-dot 1.1s infinite .18s;"></span>
									<span style="width:6px;height:6px;border-radius:50%;background:var(--text-3);animation:jv-dot 1.1s infinite .36s;"></span>
								</span>
								<span style="font-size:12px;color:var(--text-3);">{{ thinkingWord }}</span>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- ===== COMPOSER ===== -->
			<div style="position:relative;flex:none;padding:12px 40px 16px;border-top:1px solid var(--border);background:var(--surface);">
				<!-- floats just above the composer; jumps the thread to the newest message -->
				<transition name="jv-sd">
					<button v-if="showScrollDown && !showWelcome && !booting" class="jv-scrolldown" @click="jumpToBottom" title="Jump to latest" aria-label="Jump to latest message">
						<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14" /><path d="m19 12-7 7-7-7" /></svg>
					</button>
				</transition>
				<div style="max-width:1280px;margin:0 auto;">
					<div class="jv-composer" @dragover.prevent @dragenter.prevent="onDragEnter" @dragleave.prevent="onDragLeave" @drop.prevent="onDrop" style="position:relative;border:1.5px solid var(--text);border-radius:13px;background:var(--surface);box-shadow:0 2px 12px rgba(0,0,0,.07);padding:5px 6px 6px 6px;transition:border-color .12s,box-shadow .12s;">
						<div v-if="dragActive" style="position:absolute;inset:0;z-index:40;display:flex;align-items:center;justify-content:center;background:var(--blue-bg);border:2px dashed var(--blue);border-radius:13px;color:var(--blue);font-size:13px;font-weight:600;pointer-events:none;">Drop image or file to attach</div>
						<!-- mention dropdown (@ user, / doctype·tool) -->
						<div v-if="mention.open && mention.items.length" style="position:absolute;bottom:calc(100% + 6px);left:0;min-width:248px;max-height:248px;overflow-y:auto;background:var(--surface);border:1px solid var(--border-2);border-radius:10px;box-shadow:0 10px 28px rgba(20,20,30,.16);padding:5px;z-index:30;">
							<button v-for="(it, i) in mention.items" :key="it.value" class="jv-menuitem" :class="{ on: i === mention.index }" @click="applyMention(it)" @mouseenter="mention.index = i">
								<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ mention.type }}{{ it.value }}</span>
								<span style="font-size:10px;color:var(--text-3);text-transform:uppercase;letter-spacing:.03em;">{{ it.sub }}</span>
							</button>
						</div>
						<!-- pending attachments: image thumbnails (Claude-style) + file chips -->
						<div v-if="pendingFiles.length || uploading" style="display:flex;flex-wrap:wrap;gap:8px;padding:6px 4px 2px;">
							<template v-for="(f, i) in pendingFiles" :key="i">
								<span v-if="isImageFile(f)" :title="f.file_name" style="position:relative;display:inline-block;line-height:0;">
									<img :src="f.file_url" alt="" style="width:52px;height:52px;object-fit:cover;border-radius:9px;border:1px solid var(--border);display:block;" />
									<button @click="removeFile(i)" title="Remove" style="position:absolute;top:-7px;right:-7px;width:18px;height:18px;border-radius:50%;background:var(--text);color:var(--surface);border:none;cursor:pointer;font-size:12px;line-height:1;display:flex;align-items:center;justify-content:center;padding:0;">×</button>
								</span>
								<span v-else style="display:inline-flex;align-items:center;gap:5px;font-size:11.5px;padding:3px 5px 3px 9px;border-radius:999px;color:var(--text-2);background:var(--surface-1);border:1px solid var(--border);">📎 {{ f.file_name }}<button @click="removeFile(i)" style="border:none;background:transparent;cursor:pointer;font-size:14px;line-height:1;color:var(--text-3);">×</button></span>
							</template>
							<span v-if="uploading" style="font-size:11.5px;color:var(--text-3);padding:3px 6px;">Uploading…</span>
						</div>
						<div v-if="pasteHint" style="font-size:11.5px;color:var(--amber);padding:4px 8px;line-height:1.4;">{{ pasteHint }}</div>
						<textarea ref="inputEl" v-model="input" @input="onInput" @keydown="onKey" @paste="onPaste" rows="1" placeholder="Ask Jarvis…   @ to mention a user, / for a doctype or tool" style="width:100%;border:none;outline:none;resize:none;font-family:inherit;font-size:14px;line-height:1.5;color:var(--text);background:transparent;padding:8px 8px 4px;max-height:140px;"></textarea>
						<input ref="fileInput" type="file" multiple style="display:none;" @change="onFilesPicked" />
						<div style="display:flex;align-items:center;gap:6px;padding:2px 4px;">
							<button class="jv-iconbtn" title="Attach file" @click="pickFiles" style="width:30px;height:30px;display:flex;align-items:center;justify-content:center;background:transparent;border:none;border-radius:7px;cursor:pointer;color:var(--text-3);">
								<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a5 5 0 0 1-7.07-7.07l9.19-9.19a3.5 3.5 0 0 1 4.95 4.95l-9.2 9.19a1.5 1.5 0 0 1-2.12-2.12l8.49-8.49" /></svg>
							</button>
							<span style="margin-left:auto;font-size:11px;color:var(--text-3);margin-right:4px;">{{ busy ? "Stop" : "Enter ↵" }}</span>
							<button v-if="busy" @click="stopRun" title="Stop generating" style="width:32px;height:32px;display:flex;align-items:center;justify-content:center;background:var(--blue);border:none;border-radius:8px;cursor:pointer;">
								<svg width="13" height="13" viewBox="0 0 24 24" fill="#fff"><rect x="6" y="6" width="12" height="12" rx="2.5" /></svg>
							</button>
							<button v-else class="jv-sendbtn" :class="{ ready: canSend }" @click="send()" :disabled="!canSend" :style="{ width:'32px', height:'32px', display:'flex', alignItems:'center', justifyContent:'center', background: canSend ? 'var(--blue)' : 'var(--surface-3)', border:'none', borderRadius:'8px', cursor: canSend ? 'pointer' : 'default' }">
								<svg width="16" height="16" viewBox="0 0 24 24" fill="none" :stroke="canSend ? '#fff' : 'var(--text-3)'" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
							</button>
						</div>
					</div>
					<div style="text-align:center;font-size:10.5px;color:var(--text-3);margin-top:8px;">Jarvis can make mistakes. Verify important actions before submitting to ERPNext.</div>
				</div>
			</div>
		</main>

		<!-- ============ RIGHT RAIL: SKILLS + MACROS (opens the center popup) ============ -->
		<aside class="jv-skillbar">
			<div class="jv-skillrail">
				<button class="jv-skillrail-btn" :class="{ active: skillsModalOpen }" @click="openSkillsModal()">
					<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 4 7v10l8 5 8-5V7z" /><path d="M12 22V12M12 12 4 7M12 12l8-5" /></svg>
					<span class="jv-railtip">Skills</span>
				</button>
				<button class="jv-skillrail-btn" :class="{ active: macrosModalOpen }" @click="openMacrosModal()">
					<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M5 3l14 9-14 9V3z" /><path d="M3 5v14" /></svg>
					<span class="jv-railtip">Macros</span>
				</button>
			</div>
		</aside>

		<!-- ============ SKILLS POPUP (centered) ============ -->
		<transition name="jv-fade">
			<div v-if="skillsModalOpen" class="jv-skills-overlay" @click.self="closeSkillsModal">
				<div class="jv-skills-modal">
					<div class="jv-skills-head">
						<div style="min-width:0;">
							<div class="jv-skills-title">{{ skillFormOpen ? (skillReadonly ? "Skill" : (skillForm.name ? "Edit skill" : "New skill")) : "Skills" }}</div>
							<div class="jv-skills-sub">Abilities your assistant can use — type <kbd class="jv-kbd">/</kbd> in chat to trigger one.</div>
						</div>
						<button v-if="!skillFormOpen" class="jv-btn jv-btn--primary jv-btn--sm" @click="newSkill">
							<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14" /></svg> New
						</button>
						<button class="jv-btn jv-btn--icon" title="Close (Esc)" @click="closeSkillsModal">
							<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
						</button>
					</div>
					<!-- Sync status shows only while actionable: an in-flight update or a
					     failure. The steady "up to date" line was noise (user request). -->
					<div v-if="skillsSync.pending || skillsSync.last_sync_status.startsWith('failed')" class="jv-skills-status" :class="{ err: skillsSync.last_sync_status.startsWith('failed') }">
						<template v-if="skillsSync.pending"><span class="jv-skill-dot spin"></span> Updating your assistant… (restarts briefly, ~30s)</template>
						<template v-else><span class="jv-skill-dot err"></span> Couldn't update your assistant. {{ skillsSync.last_sync_status.replace("failed:", "").trim() }}</template>
					</div>
					<div class="jv-skills-body">
						<!-- create / edit form -->
						<div v-if="skillFormOpen" class="jv-skill-form">
							<div v-if="skillError" class="jv-skill-err">{{ skillError }}</div>
							<div v-if="skillReadonly" class="jv-ro-banner">
								<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
								<span>Shared by <b>{{ skillSharedBy || "another user" }}</b> · read-only</span>
							</div>
							<label class="jv-skill-l">Name</label>
							<input class="jv-skill-in" v-model="skillForm.skill_name" :disabled="skillReadonly || !!skillForm.name" placeholder="e.g. monthly-close" maxlength="40" />
							<div v-if="!skillReadonly" class="jv-set-hint" style="margin:3px 0 10px;">Lowercase letters, digits and hyphens. Trigger it in chat with <kbd class="jv-kbd">/{{ skillForm.skill_name || 'name' }}</kbd>.</div>
							<div v-else style="height:10px;"></div>
							<label class="jv-skill-l">Description</label>
							<input class="jv-skill-in" v-model="skillForm.description" :disabled="skillReadonly" placeholder="When should the assistant use this skill?" maxlength="500" />
							<div v-if="!skillReadonly" class="jv-set-hint" style="margin:3px 0 10px;">A short hint so the assistant knows when this skill applies.</div>
							<div v-else style="height:10px;"></div>
							<label class="jv-skill-l">Instructions</label>
							<textarea class="jv-skill-ta" v-model="skillForm.instructions" :disabled="skillReadonly" rows="9" placeholder="Markdown instructions the assistant follows when this skill runs…"></textarea>
							<div v-if="!skillReadonly" class="jv-set-row" style="margin-top:10px;"><span>Let users trigger it with /<br /><span style="font-size:11px;color:var(--text-3);font-weight:400;">Appears in the chat “/” menu</span></span><button class="jv-switch" :class="{ on: skillForm.user_invocable }" @click="skillForm.user_invocable = !skillForm.user_invocable" role="switch" :aria-checked="String(!!skillForm.user_invocable)"><span class="jv-switch-knob"></span></button></div>
							<div v-if="!skillReadonly" class="jv-set-row"><span>Enabled<br /><span style="font-size:11px;color:var(--text-3);font-weight:400;">Off = saved as a draft, not used by the assistant</span></span><button class="jv-switch" :class="{ on: skillForm.enabled }" @click="skillForm.enabled = !skillForm.enabled" role="switch" :aria-checked="String(!!skillForm.enabled)"><span class="jv-switch-knob"></span></button></div>
							<div class="jv-skill-formfoot">
								<button v-if="!skillReadonly" class="jv-btn jv-btn--primary" :disabled="skillSaving || skillsSync.pending" @click="saveSkill">{{ skillSaving ? "Saving…" : "Save skill" }}</button>
								<button v-if="skillReadonly" class="jv-btn jv-btn--ghost" @click="skillFormOpen = false; skillReadonly = false">Back</button>
								<button v-else class="jv-btn jv-btn--ghost" :disabled="skillSaving" @click="skillFormOpen = false">Cancel</button>
								<span v-if="!skillReadonly" class="jv-skill-foothint">Saving updates your assistant automatically.</span>
							</div>
						</div>
						<!-- skills list -->
						<template v-else>
							<div v-if="!customSkills.length" class="jv-set-empty" style="text-align:center;padding:26px 0;">No skills yet.<br />Create one to give your assistant a new ability.</div>
							<!-- own skills: full controls + share -->
							<div v-for="s in mySkills" :key="s.name" class="jv-skill-row">
								<div style="min-width:0;flex:1;cursor:pointer;" @click="editSkill(s)">
									<div class="jv-skill-name">/{{ s.skill_name }} <span v-if="!s.enabled" class="jv-skill-off">draft</span><span v-if="s.shared_count > 0" class="jv-shared-chip"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8a3 3 0 1 0-2.83-4M6 12a3 3 0 1 0 0 .01M18 16a3 3 0 1 0-2.83 4M8.6 13.5l6.8 4M15.4 6.5l-6.8 4" /></svg>Shared · {{ s.shared_count }}</span></div>
									<div class="jv-skill-desc">{{ s.description }}</div>
								</div>
								<button class="jv-btn jv-btn--icon jv-ib jv-ib-accent" title="Share" @click="openShareModal(s)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" /><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4" /></svg></button>
								<button class="jv-btn jv-btn--icon jv-ib" title="Edit" @click="editSkill(s)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg></button>
								<button class="jv-btn jv-btn--icon jv-ib jv-ib-danger" title="Delete" @click="removeSkill(s)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" /></svg></button>
							</div>
							<!-- shared-with-me: read-only -->
							<template v-if="sharedSkills.length">
								<div class="jv-share-divider">Shared with you</div>
								<div v-for="s in sharedSkills" :key="s.name" class="jv-skill-row jv-skill-row-shared" @click="editSkill(s)" style="cursor:pointer;">
									<span class="jv-share-lock" title="Read-only — shared with you"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg></span>
									<div style="min-width:0;flex:1;">
										<div class="jv-skill-name">/{{ s.skill_name }} <span class="jv-sharedby-chip"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>Shared by {{ s.shared_by }}</span></div>
										<div class="jv-skill-desc">{{ s.description }}</div>
									</div>
								</div>
							</template>
						</template>
					</div>
				</div>
			</div>
		</transition>

		<!-- ============ SHARE SKILL POPUP (centered) ============ -->
		<transition name="jv-fade">
			<div v-if="shareModalOpen" class="jv-skills-overlay" @click.self="closeShareModal">
				<div class="jv-skills-modal jv-share-modal">
					<div class="jv-skills-head">
						<div style="min-width:0;">
							<div class="jv-skills-title">Share “{{ shareSkill.skill_name }}”</div>
							<div class="jv-skills-sub">They can use this skill in chat, but can’t edit or re-share it.</div>
						</div>
						<button class="jv-btn jv-btn--icon" title="Close (Esc)" @click="closeShareModal">
							<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
						</button>
					</div>
					<div class="jv-skills-body">
						<div v-if="shareLoading" class="jv-set-empty" style="text-align:center;padding:30px 0;">Loading people…</div>
						<template v-else>
							<!-- selected users as chips -->
							<div v-if="shareSelected.length" class="jv-share-chips">
								<span v-for="id in shareSelected" :key="id" class="jv-share-chip">
									<span class="jv-share-avatar">{{ _shareInitials(_shareUser(id)) }}</span>
									<span class="jv-share-chip-name">{{ _shareUser(id).full_name }}</span>
									<button class="jv-share-chip-x" title="Remove" @click="toggleShareUser(id)"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg></button>
								</span>
							</div>
							<!-- search -->
							<div class="jv-share-searchwrap">
								<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.9" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
								<input v-model="shareSearch" class="jv-share-search" placeholder="Search people…" />
							</div>
							<!-- candidate list -->
							<div v-if="!shareCandidates.length" class="jv-set-empty" style="text-align:center;padding:22px 0;">No other users to share with yet.</div>
							<div v-else-if="!shareMatches.length" class="jv-set-empty" style="text-align:center;padding:18px 0;">No people match “{{ shareSearch }}”.</div>
							<div v-else class="jv-share-list">
								<button v-for="u in shareMatches" :key="u.name" class="jv-share-row" :class="{ on: isShareSelected(u.name) }" @click="toggleShareUser(u.name)">
									<span class="jv-share-avatar">{{ _shareInitials(u) }}</span>
									<span class="jv-share-row-info">
										<span class="jv-share-row-name">{{ u.full_name }}</span>
										<span class="jv-share-row-id">{{ u.name }}</span>
									</span>
									<svg v-if="isShareSelected(u.name)" class="jv-share-check" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--blue)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
								</button>
							</div>
							<div class="jv-share-helper">
								<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
								They can use this skill in chat, but can’t edit or re-share it.
							</div>
							<div class="jv-skill-formfoot">
								<button class="jv-btn jv-btn--primary" :disabled="shareSaving" @click="saveShares">{{ shareSaving ? "Saving…" : "Save" }}</button>
								<button class="jv-btn jv-btn--ghost" :disabled="shareSaving" @click="closeShareModal">Cancel</button>
								<span class="jv-skill-foothint">{{ shareSelected.length }} {{ shareSelected.length === 1 ? "person" : "people" }} selected</span>
							</div>
						</template>
					</div>
				</div>
			</div>
		</transition>

		<!-- ============ MACROS POPUP (centered) ============ -->
		<transition name="jv-fade">
			<div v-if="macrosModalOpen" class="jv-skills-overlay" @click.self="closeMacrosModal">
				<div class="jv-skills-modal">
					<div class="jv-skills-head">
						<div style="min-width:0;">
							<div class="jv-skills-title">Macros</div>
							<div class="jv-skills-sub">Saved prompt sequences your assistant runs as a chain of turns.</div>
						</div>
						<button class="jv-btn jv-btn--primary jv-btn--sm" @click="newMacro">
							<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14" /></svg> New
						</button>
						<button class="jv-btn jv-btn--icon" title="Close (Esc)" @click="closeMacrosModal">
							<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
						</button>
					</div>
					<div class="jv-skills-body">
						<div v-if="macroError" class="jv-skill-err">{{ macroError }}</div>
						<div v-if="!macros.length" class="jv-set-empty" style="text-align:center;padding:32px 0;">No macros yet.<br />Hit <strong>New</strong> to record a sequence of prompts.</div>
						<div v-for="mm in macros" :key="mm.name" class="jv-skill-row">
							<div style="min-width:0;flex:1;cursor:pointer;" @click="editMacro(mm)">
								<div class="jv-skill-name" style="font-family:inherit;">{{ mm.macro_name }} <span v-if="!mm.enabled" class="jv-skill-off">draft</span></div>
								<div class="jv-macro-sub">{{ mm.step_count || 0 }} step{{ (mm.step_count || 0) === 1 ? "" : "s" }}<span v-if="mm.schedule_enabled" class="jv-macro-sched"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>{{ mm.schedule_frequency || "scheduled" }}</span></div>
							</div>
							<button class="jv-btn jv-btn--primary jv-btn--sm" title="Run" @click.stop="runMacroFromList(mm)"><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4l14 8-14 8V4z" /></svg> Run</button>
							<button class="jv-btn jv-btn--icon jv-ib" title="Edit" @click.stop="editMacro(mm)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg></button>
							<button class="jv-btn jv-btn--icon jv-ib jv-ib-danger" title="Delete" @click.stop="removeMacro(mm)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" /></svg></button>
						</div>
					</div>
				</div>
			</div>
		</transition>

		<!-- ============ MACRO EDITOR POPUP (centered) ============ -->
		<transition name="jv-fade">
			<div v-if="macroEditorOpen" class="jv-skills-overlay" @click.self="closeMacroEditor">
				<div class="jv-skills-modal">
					<div class="jv-skills-head">
						<div style="min-width:0;">
							<div class="jv-skills-title">{{ macroForm.name ? "Edit macro" : "New macro" }}</div>
							<div class="jv-skills-sub">Each step runs as its own agent turn, in order.</div>
						</div>
						<button class="jv-btn jv-btn--icon" title="Close (Esc)" @click="closeMacroEditor">
							<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
						</button>
					</div>
					<div class="jv-skills-body">
						<label class="jv-skill-l">Name</label>
						<input class="jv-skill-in" v-model="macroForm.macro_name" placeholder="e.g. Monthly close" maxlength="140" />
						<div style="height:10px;"></div>
						<label class="jv-skill-l">Description</label>
						<input class="jv-skill-in" v-model="macroForm.description" placeholder="What does this macro do?" maxlength="500" />
						<div class="jv-set-row" style="margin-top:12px;"><span>Stop if a step fails<br /><span style="font-size:11px;color:var(--text-3);font-weight:400;">Otherwise the chain keeps going after an error</span></span><button class="jv-switch" :class="{ on: macroForm.stop_on_error }" @click="macroForm.stop_on_error = !macroForm.stop_on_error" role="switch" :aria-checked="String(!!macroForm.stop_on_error)"><span class="jv-switch-knob"></span></button></div>
						<div class="jv-set-row"><span>Run on a schedule<br /><span style="font-size:11px;color:var(--text-3);font-weight:400;">Jarvis runs this macro automatically</span></span><button class="jv-switch" :class="{ on: macroForm.schedule_enabled }" @click="macroForm.schedule_enabled = !macroForm.schedule_enabled" role="switch" :aria-checked="String(!!macroForm.schedule_enabled)"><span class="jv-switch-knob"></span></button></div>
						<div v-if="macroForm.schedule_enabled" class="jv-macro-sched-fields">
							<div style="flex:1;">
								<label class="jv-skill-l">Frequency</label>
								<select class="jv-skill-in" v-model="macroForm.schedule_frequency"><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select>
							</div>
							<div style="flex:1;">
								<label class="jv-skill-l">Time</label>
								<input type="time" class="jv-skill-in" v-model="macroForm.schedule_time" />
							</div>
						</div>
						<label class="jv-skill-l" style="margin-top:16px;">Steps</label>
						<div v-if="!macroForm.steps.length" class="jv-set-empty">No steps yet. Add one below.</div>
						<div v-for="(st, si) in macroForm.steps" :key="si" class="jv-macro-step" :class="{ dragging: dragStepIdx === si, dragover: dragOverIdx === si && dragStepIdx !== null && dragStepIdx !== si }" @dragover.prevent="onStepDragOver(si)" @dragleave="onStepDragLeave(si)" @drop.prevent="onStepDrop(si)">
							<div class="jv-macro-step-head">
								<span class="jv-macro-grip" draggable="true" title="Drag to reorder" @dragstart="onStepDragStart(si, $event)" @dragend="onStepDragEnd"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="6" r="1.5" /><circle cx="15" cy="6" r="1.5" /><circle cx="9" cy="12" r="1.5" /><circle cx="15" cy="12" r="1.5" /><circle cx="9" cy="18" r="1.5" /><circle cx="15" cy="18" r="1.5" /></svg></span>
								<span class="jv-macro-step-num">{{ si + 1 }}</span>
								<input class="jv-skill-in jv-macro-step-label" v-model="st.label" placeholder="Optional label" maxlength="140" />
								<button class="jv-btn jv-btn--icon jv-ib jv-ib-danger" title="Remove step" @click="removeMacroStep(si)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg></button>
							</div>
							<textarea class="jv-skill-ta" v-model="st.prompt" rows="3" placeholder="The prompt to send for this step…"></textarea>
							<div v-if="macroSkillOptions.length" class="jv-macro-step-skills">
								<span class="jv-macro-step-skills-l"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" /></svg>Skills</span>
								<button v-for="s in macroSkillOptions" :key="s.name" class="jv-macro-skill-opt jv-macro-skill-opt--sm" :class="{ on: (st.skills || []).includes(s.name) }" @click="toggleStepSkill(si, s.name)" :title="s.description || s.skill_name">
									<span v-if="(st.skills || []).includes(s.name)" class="jv-ask-tick">✓</span>/{{ s.skill_name }}<span v-if="!s.mine" class="jv-macro-skill-shared">shared</span>
								</button>
							</div>
						</div>
						<button class="jv-skill-newrow" style="margin-top:12px;margin-bottom:0;" @click="addMacroStep"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14" /></svg> Add step</button>
						<!-- Error sits next to Save (the body scrolls — a top-of-form message
						     is off-screen when a long step list is open, so it was missed). -->
						<div v-if="macroError" class="jv-skill-err" style="margin-top:12px;">{{ macroError }}</div>
						<div class="jv-skill-formfoot">
							<button class="jv-btn jv-btn--primary" :disabled="macroSaving" @click="saveMacro">{{ macroSaving ? "Saving…" : "Save macro" }}</button>
							<button class="jv-btn jv-btn--ghost" :disabled="macroSaving" @click="closeMacroEditor">Cancel</button>
						</div>
					</div>
				</div>
			</div>
		</transition>

		<!-- ============ MACRO MERGE REVIEW (auto-offered after a 2+ step save) ============ -->
		<transition name="jv-fade">
			<div v-if="macroMerge" class="jv-skills-overlay" @click.self="dropMacroMerge('')">
				<div class="jv-merge-modal">
					<div class="jv-merge-head">
						<b>Merge “{{ macroMerge.macroName }}” into one prompt?</b>
						<button class="jv-art-close" @click="dropMacroMerge('')" aria-label="Close">✕</button>
					</div>
					<div v-if="macroMerge.status === 'pending'" class="jv-merge-pending">
						<span class="jv-merge-spin"></span> Summarizing {{ macroMerge.steps }} steps into one prompt…
						<div class="jv-merge-sub">Macro saved. You'll review the merged prompt before anything changes — close this to keep the step sequence.</div>
					</div>
					<template v-else-if="macroMerge.status === 'ready'">
						<div v-if="(macroMerge.merge.dependencies || []).length" class="jv-merge-deps">
							<span v-for="(d, di) in macroMerge.merge.dependencies" :key="di" class="jv-merge-chip">
								step {{ d.step }} ← {{ (d.uses || []).join(", ") }}
							</span>
						</div>
						<textarea class="jv-merge-text" v-model="macroMerge.editedPrompt" rows="10"></textarea>
						<div v-if="macroMerge.error" class="jv-draft-error">{{ macroMerge.error }}</div>
						<div class="jv-merge-foot">
							<button class="jv-action-2nd" @click="dropMacroMerge('')">Keep sequence</button>
							<button class="jv-action-primary" style="margin-left:auto" :disabled="macroMerge.applying" @click="acceptMacroMerge">
								{{ macroMerge.applying ? "Applying…" : "Use merged prompt" }}
							</button>
						</div>
					</template>
					<template v-else>
						<div class="jv-merge-keep">Kept as a sequence — {{ (macroMerge.merge && macroMerge.merge.reason) || "these steps need their checkpoints." }}</div>
						<div class="jv-merge-foot">
							<button class="jv-action-primary" style="margin-left:auto" @click="dropMacroMerge('')">OK</button>
						</div>
					</template>
				</div>
			</div>
		</transition>
		<transition name="jv-fade">
			<div v-if="mergeNotice" class="jv-merge-notice">{{ mergeNotice }}</div>
		</transition>

		<!-- ============ PROACTIVE MESSAGE TOAST (Jarvis started a chat) ============ -->
		<transition name="jv-fade">
			<div v-if="proactiveToast" class="jv-toast" @click="openProactive">
				<div class="jv-toast-ic"><svg width="16" height="16" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg></div>
				<div style="min-width:0;flex:1;">
					<div class="jv-toast-title">{{ proactiveToast.title }}</div>
					<div class="jv-toast-preview">{{ proactiveToast.preview }}</div>
				</div>
				<button class="jv-toast-open" @click.stop="openProactive">Open</button>
				<button class="jv-toast-x" @click.stop="proactiveToast = null" title="Dismiss"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg></button>
			</div>
		</transition>

		<!-- ============ NOTIFIER (reusable toasts: "Deleted", etc.) ============ -->
		<div class="jv-notes" aria-live="polite">
			<transition-group name="jv-note">
				<div v-for="n in notes" :key="n.id" class="jv-note" :class="n.type" role="status">
					<span class="jv-note-ic" aria-hidden="true">
						<svg v-if="n.type === 'success'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
						<svg v-else-if="n.type === 'error'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16.4v.01" /></svg>
						<svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 16v-5M12 8v.01" /></svg>
					</span>
					<div class="jv-note-body">
						<div v-if="n.title" class="jv-note-title">{{ n.title }}</div>
						<div class="jv-note-msg">{{ n.message }}</div>
					</div>
					<button class="jv-note-x" @click="dismissNote(n.id)" title="Dismiss" aria-label="Dismiss"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg></button>
				</div>
			</transition-group>
		</div>

		<!-- ============ CONFIRM DIALOG (reusable; replaces window.confirm) ============ -->
		<transition name="jv-fade">
			<div v-if="confirmBox" class="jv-skills-overlay" @click.self="_settleConfirm(false)">
				<div class="jv-cdialog" role="alertdialog" aria-modal="true">
					<div class="jv-cdialog-title">{{ confirmBox.title }}</div>
					<div v-if="confirmBox.message" class="jv-cdialog-msg">{{ confirmBox.message }}</div>
					<div class="jv-cdialog-foot">
						<button class="jv-btn jv-btn--ghost" @click="_settleConfirm(false)">{{ confirmBox.cancelLabel }}</button>
						<button class="jv-btn" :class="confirmBox.danger ? 'jv-btn--danger' : 'jv-btn--primary'" @click="_settleConfirm(true)">{{ confirmBox.confirmLabel }}</button>
					</div>
				</div>
			</div>
		</transition>

		<!-- ============ SETTINGS (openclaw-style console) ============ -->
		<transition name="jv-fade">
			<div v-if="settingsOpen" class="jv-settings-overlay" @click.self="settingsOpen = false">
				<div class="jv-settings">
					<div class="jv-settings-nav">
						<div class="jv-settings-nav-title">Settings</div>
						<button class="jv-settings-navitem" :class="{ on: settingsTab === 'overview' }" @click="settingsTab = 'overview'">
							<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
							<span>General</span>
						</button>
						<button class="jv-settings-navitem" :class="{ on: settingsTab === 'usage' }" @click="settingsTab = 'usage'">
							<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18" /><rect x="7" y="10" width="3" height="7" /><rect x="13" y="6" width="3" height="11" /></svg>
							<span>Usage</span>
						</button>
						<button class="jv-settings-navitem" :class="{ on: settingsTab === 'appearance' }" @click="settingsTab = 'appearance'">
							<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
							<span>Appearance</span>
						</button>
						<button class="jv-settings-navitem" :class="{ on: settingsTab === 'activity' }" @click="settingsTab = 'activity'">
							<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2" /></svg>
							<span>Activity</span>
						</button>
						<button class="jv-settings-navitem" :class="{ on: settingsTab === 'macroruns' }" @click="settingsTab = 'macroruns'">
							<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M5 3l14 9-14 9V3z" /></svg>
							<span>Macro runs</span>
						</button>
						<button class="jv-settings-navitem" :class="{ on: settingsTab === 'shortcuts' }" @click="settingsTab = 'shortcuts'">
							<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2" /><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M6 12h.01M10 12h.01M14 12h.01M18 12h.01M7 16h10" /></svg>
							<span>Shortcuts</span>
						</button>
					</div>
					<div class="jv-settings-main">
						<div class="jv-settings-head">
							<span style="font-size:15px;font-weight:600;">{{ settingsTab === "appearance" ? "Appearance" : settingsTab === "activity" ? "Activity" : settingsTab === "usage" ? "Usage" : settingsTab === "shortcuts" ? "Keyboard shortcuts" : "General" }}</span>
							<button class="jv-iconbtn" @click="settingsOpen = false" title="Close" style="width:28px;height:28px;display:flex;align-items:center;justify-content:center;background:transparent;border:none;border-radius:7px;cursor:pointer;color:var(--text-3);">
								<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
							</button>
						</div>
						<div class="jv-settings-body">
						<!-- OVERVIEW -->
						<template v-if="settingsTab === 'overview'">
							<div class="jv-set-sec">Connection</div>
							<div class="jv-set-row"><span>Model</span><b>{{ modelLabel }}</b></div>
							<div class="jv-set-row"><span>Provider</span><b>{{ ui.llm_provider || "—" }}</b></div>
							<div class="jv-set-row"><span>Auth mode</span><b>{{ ui.llm_auth_mode || "—" }}</b></div>
							<div class="jv-set-row"><span>Status</span><b style="color:var(--green);">Live</b></div>
								<div class="jv-set-sec" style="margin-top:18px;">Behavior</div>
								<div class="jv-set-row">
									<span>Confirm before changes<br /><span style="font-size:11px;color:var(--text-3);font-weight:400;">Ask before any create, update, or delete</span></span>
									<button class="jv-switch" :class="{ on: !ui.auto_apply_changes }" @click="toggleAutoApply" role="switch" :aria-checked="String(!ui.auto_apply_changes)" :title="ui.auto_apply_changes ? 'Auto mode — changes apply without asking' : 'Confirm each change before it runs'">
										<span class="jv-switch-knob"></span>
									</button>
								</div>
								<div class="jv-set-row">
									<span>Show tool activity<br /><span style="font-size:11px;color:var(--text-3);font-weight:400;">Show the live tool steps + input/output above each reply. The tools count &amp; time always show below.</span></span>
									<button class="jv-switch" :class="{ on: showActivityDetail }" @click="setActivityDetail(!showActivityDetail)" role="switch" :aria-checked="String(showActivityDetail)" title="Show the tool/skill activity under each answer">
										<span class="jv-switch-knob"></span>
									</button>
								</div>
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
						<!-- USAGE -->
						<template v-else-if="settingsTab === 'usage'">
							<div style="font-size:12px;color:var(--text-3);margin:0 0 14px;">Estimated tokens, messages and tool activity for your workspace. <span class="jv-est">est.</span></div>
							<div class="jv-statgrid">
								<div class="jv-stat"><div class="jv-stat-label">Messages</div><div class="jv-stat-val">{{ msgCount }}</div><div class="jv-stat-sub">{{ userMsgCount }} you · {{ assistantMsgCount }} Jarvis</div></div>
								<div class="jv-stat"><div class="jv-stat-label">Tool calls</div><div class="jv-stat-val">{{ sessionToolCalls }}</div><div class="jv-stat-sub">this session</div></div>
								<div class="jv-stat"><div class="jv-stat-label">Avg tokens / msg</div><div class="jv-stat-val">{{ avgTokensPerMsg }}</div><div class="jv-stat-sub">this chat</div></div>
								<div class="jv-stat"><div class="jv-stat-label">Conversations</div><div class="jv-stat-val">{{ convCount }}</div><div class="jv-stat-sub">{{ starredCount }} starred</div></div>
								<div class="jv-stat"><div class="jv-stat-label">This chat</div><div class="jv-stat-val">{{ usage ? fmtTokens(usage.chat_tokens) : "—" }}</div><div class="jv-stat-sub">tokens</div></div>
								<div class="jv-stat"><div class="jv-stat-label">{{ usage ? usage.month_label : "This month" }}</div><div class="jv-stat-val">{{ usage ? fmtTokens(usage.month_tokens) : "—" }}</div><div class="jv-stat-sub">tokens</div></div>
								<div class="jv-stat"><div class="jv-stat-label">All time</div><div class="jv-stat-val">{{ usage ? fmtTokens(usage.total_tokens) : "—" }}</div><div class="jv-stat-sub">tokens</div></div>
								<div class="jv-stat"><div class="jv-stat-label">Tools</div><div class="jv-stat-val">{{ toolCount }}</div><div class="jv-stat-sub">available</div></div>
							</div>
							<template v-if="usage && usage.budget_monthly">
								<div class="jv-set-sec" style="margin-top:20px;">Monthly budget</div>
								<div class="jv-usage-bar"><div class="jv-usage-fill" :style="{ width: usagePct + '%' }"></div></div>
								<div class="jv-set-hint">{{ fmtTokens(usage.month_tokens) }} / {{ fmtTokens(usage.budget_monthly) }} this month · {{ usagePct }}%</div>
							</template>
							<div v-else class="jv-set-hint" style="margin-top:14px;">No monthly budget set · token counts are estimated from message text.</div>
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
						<!-- MACRO RUNS -->
						<template v-else-if="settingsTab === 'macroruns'">
							<div class="jv-statgrid">
								<div class="jv-stat"><div class="jv-stat-label">Total runs</div><div class="jv-stat-val">{{ macroRunStats ? macroRunStats.total : "—" }}</div><div class="jv-stat-sub">all time</div></div>
								<div class="jv-stat"><div class="jv-stat-label">Success rate</div><div class="jv-stat-val" style="color:var(--green);">{{ macroRunStats && macroRunStats.success_rate != null ? macroRunStats.success_rate + "%" : "—" }}</div><div class="jv-stat-sub">completed ÷ finished</div></div>
								<div class="jv-stat"><div class="jv-stat-label">Running now</div><div class="jv-stat-val" style="color:var(--blue);">{{ macroRunStats ? macroRunStats.running : "—" }}</div><div class="jv-stat-sub">active</div></div>
								<div class="jv-stat"><div class="jv-stat-label">Last run</div><div class="jv-stat-val">{{ macroRunStats && macroRunStats.last_run_at ? fmtAgo(macroRunStats.last_run_at) : "—" }}</div><div class="jv-stat-sub">&nbsp;</div></div>
							</div>
							<div class="jv-runfilters">
								<div class="jv-seg jv-runchips">
									<button v-for="s in MACRO_RUN_STATUSES" :key="s || 'all'" :class="{ on: macroRunStatus === s }" @click="setMacroRunStatus(s)">{{ s ? (s[0].toUpperCase() + s.slice(1)) : "All" }}</button>
								</div>
								<select class="jv-runmacrosel" :value="macroRunMacro" @change="setMacroRunMacro">
									<option value="">All macros</option>
									<option v-for="mm in macros" :key="mm.name" :value="mm.name">{{ mm.macro_name }}</option>
								</select>
							</div>
							<div v-if="!macroRuns.length && !macroRunsLoading" class="jv-set-empty" style="text-align:center;padding:30px 0;">No macro runs yet.<br />Run a macro to see its history here.</div>
							<div v-for="run in macroRuns" :key="run.name" class="jv-run">
								<span class="jv-run-dot" :class="'d-' + macroRunBadge(run.status)"></span>
								<div class="jv-run-main">
									<div class="jv-run-top">
										<span class="jv-run-name">{{ run.macro_name }}</span>
										<span class="jv-run-badge" :class="'b-' + macroRunBadge(run.status)">{{ run.status }}</span>
										<span class="jv-run-trig">
											<svg v-if="run.trigger === 'scheduled'" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="5" width="16" height="15" rx="2" /><path d="M8 3v4M16 3v4M4 10h16" /></svg>
											<svg v-else width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v4l3 2" /></svg>
											{{ run.trigger }}
										</span>
									</div>
									<div class="jv-run-meta">
										<span class="jv-run-prog">{{ run.current_step }}/{{ run.total_steps }}</span>
										<span class="jv-run-sep">·</span><span>{{ fmtAgo(run.started_at || run.creation) }}</span>
										<template v-if="macroRunElapsed(run)"><span class="jv-run-sep">·</span><span>{{ macroRunElapsed(run) }}</span></template>
									</div>
									<div v-if="run.error" class="jv-run-err">
										<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4M12 17h.01" /></svg>
										{{ run.error }}
									</div>
								</div>
								<div class="jv-run-act">
									<button v-if="run.status === 'running' || run.status === 'queued'" class="jv-run-btn stop" @click="stopRunFromHistory(run)">Stop</button>
									<button v-else class="jv-run-btn" @click="rerunFromHistory(run)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2v6h6M21 12a9 9 0 1 1-3-6.7L21 8" /></svg>Re-run</button>
									<button v-if="run.conversation" class="jv-run-btn" @click="openRunConversation(run)">Open ›</button>
								</div>
							</div>
							<button v-if="macroRunHasMore" class="jv-run-loadmore" :disabled="macroRunsLoading" @click="loadMacroRuns(false)">{{ macroRunsLoading ? "Loading…" : "Load more" }}</button>
						</template>
						<!-- SHORTCUTS -->
						<template v-else-if="settingsTab === 'shortcuts'">
							<div style="font-size:12px;color:var(--text-3);margin:0 0 14px;">Speed up the composer and chat.</div>
							<div class="jv-set-sec">Composer</div>
							<div class="jv-kbd-row"><span>Recall previous / next prompt</span><span><kbd class="jv-kbd">↑</kbd><kbd class="jv-kbd">↓</kbd></span></div>
							<div class="jv-kbd-row"><span>Send message</span><kbd class="jv-kbd">Enter</kbd></div>
							<div class="jv-kbd-row"><span>New line</span><span><kbd class="jv-kbd">Shift</kbd><span class="jv-kbd-plus">+</span><kbd class="jv-kbd">Enter</kbd></span></div>
							<div class="jv-kbd-row"><span>Mention a doctype / record</span><kbd class="jv-kbd">@</kbd></div>
							<div class="jv-set-sec" style="margin-top:20px;">Chat</div>
							<div class="jv-kbd-row"><span>New chat</span><span><kbd class="jv-kbd">Ctrl</kbd><span class="jv-kbd-plus">+</span><kbd class="jv-kbd">Shift</kbd><span class="jv-kbd-plus">+</span><kbd class="jv-kbd">O</kbd></span></div>
							<div class="jv-kbd-row"><span>Toggle sidebar</span><span><kbd class="jv-kbd">Ctrl</kbd><span class="jv-kbd-plus">+</span><kbd class="jv-kbd">B</kbd></span></div>
							<div class="jv-kbd-row"><span>Close panel / cancel</span><kbd class="jv-kbd">Esc</kbd></div>
							<div class="jv-set-hint" style="margin-top:14px;">Tip: <kbd class="jv-kbd">↑</kbd> at the start of an empty composer walks back through your earlier prompts in this chat.</div>
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

							<div class="jv-set-sec" style="margin-top:22px;">About</div>
							<div class="jv-set-row"><span>Jarvis</span><b>ERPNext Assistant</b></div>
						</template>
					</div>
				</div>
				</div>
			</div>
		</transition>

		<!-- Artifact preview panel — slides in from the right (PDF in a viewer, Excel as a table) -->
		<transition name="jv-slide">
			<div v-if="artifact" class="jv-artifact-overlay" @click.self="closeArtifact">
				<aside class="jv-artifact-panel" ref="artifactPanelEl" tabindex="-1">
					<div class="jv-artifact-head">
						<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></svg>
						<span class="jv-artifact-head-title">{{ artifact.cv.title }}</span>
						<span class="jv-canvas-type">{{ artifact.cv.type }}</span>
						<a class="jv-art-act" :href="artifact.url" target="_blank" rel="noopener" title="Open in new tab" aria-label="Open in new tab">
							<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3" /></svg>
						</a>
						<a class="jv-art-act" :href="artifact.url" :download="cvFile(artifact.cv)" title="Download" aria-label="Download">
							<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
						</a>
						<span class="jv-art-divider" aria-hidden="true"></span>
						<button class="jv-art-close" @click="closeArtifact" title="Close preview (Esc)" aria-label="Close preview">
							<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
						</button>
					</div>
					<div class="jv-artifact-body">
						<iframe v-if="artifact.kind === 'pdf'" :src="artifact.url" class="jv-artifact-frame" title="PDF preview"></iframe>
						<img v-else-if="artifact.kind === 'image'" :src="artifact.url" class="jv-artifact-img" :alt="artifact.cv.title" />
						<iframe v-else-if="artifact.kind === 'html' || artifact.kind === 'svg'" :srcdoc="artifact.content" sandbox="allow-scripts allow-popups" class="jv-artifact-frame" title="Artifact preview"></iframe>
						<template v-else-if="artifact.kind === 'table'">
							<div v-if="artifact.sheets.length > 1" class="jv-sheet-tabs">
								<button v-for="(sh, si) in artifact.sheets" :key="si" :class="{ on: si === artifact.sheetIdx }" @click="setSheet(si)">{{ sh.name }}</button>
							</div>
							<div class="jv-sheet-scroll">
								<table class="jv-sheet">
									<thead v-if="curSheet.rows.length"><tr><th v-for="(c, ci) in curSheet.rows[0]" :key="ci">{{ c }}</th></tr></thead>
									<tbody><tr v-for="(row, ri) in curSheet.rows.slice(1)" :key="ri"><td v-for="(c, ci) in row" :key="ci">{{ c }}</td></tr></tbody>
								</table>
							</div>
						</template>
						<pre v-else-if="artifact.kind === 'text'" class="jv-artifact-text">{{ artifact.text }}</pre>
						<div v-else-if="artifact.kind === 'loading'" class="jv-artifact-loading">Loading preview…</div>
						<div v-else class="jv-artifact-nopreview">
							<p>No inline preview for this file type.</p>
							<a :href="artifact.url" :download="cvFile(artifact.cv)" class="jv-canvas-dl">Download {{ cvFile(artifact.cv) }}</a>
						</div>
					</div>
				</aside>
			</div>
		</transition>
		<!-- Record draft panel — the agent's proposed create/update, fully editable, applied directly -->
		<transition name="jv-slide">
			<div v-if="draftPanel" class="jv-artifact-overlay" @click.self="closeDraftPanel">
				<aside class="jv-artifact-panel jv-draft-panel" tabindex="-1">
					<div class="jv-artifact-head">
						<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 4v16"/></svg>
						<span class="jv-artifact-head-title">{{ draftPanel.verb === 'update' ? 'Update' : 'New' }} {{ draftPanel.doctype }}<template v-if="draftPanel.docName"> · {{ draftPanel.docName }}</template></span>
						<span class="jv-draft-badge">Draft — not saved</span>
						<button class="jv-art-close" @click="closeDraftPanel" title="Close (draft stays in chat)" aria-label="Close">
							<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
						</button>
					</div>
					<div class="jv-draft-body">
						<div v-if="draftPanel.updatedToast" class="jv-draft-toast">Draft updated from chat</div>
						<div class="jv-draft-fields">
							<div v-for="f in draftPanel.fields" :key="f.fieldname" class="jv-draft-fld"
							     :class="{ missing: f.reqd && !String(f.value).trim(), changed: f.changed }">
								<label>{{ f.label }}<span v-if="f.reqd" class="jv-req"> *</span></label>
								<div class="jv-draft-ctl">
									<template v-if="f.control === 'link'">
										<input class="jv-action-input" v-model="f.value"
										       @input="onDraftLink('f:' + f.fieldname, () => f.value, f.options, $event)"
										       @focus="onDraftLink('f:' + f.fieldname, () => f.value, f.options, $event)"
										       @blur="closeDraftLink" :placeholder="'Search ' + (f.options || 'records') + '…'" autocomplete="off" />
										<div v-if="draftLink.open && draftLink.key === 'f:' + f.fieldname && draftLink.items.length"
										     class="jv-action-linkmenu" :class="{ up: draftLink.up }">
											<button v-for="it in draftLink.items" :key="it.value" @mousedown.prevent="pickDraftLink((v) => { f.value = v }, it)">
												<b>{{ it.value }}</b><span v-if="it.label"> — {{ it.label }}</span>
											</button>
										</div>
									</template>
									<select v-else-if="f.control === 'select'" class="jv-action-input jv-action-sel" v-model="f.value">
										<option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
									</select>
									<select v-else-if="f.control === 'check'" class="jv-action-input jv-action-sel" v-model="f.value">
										<option>Yes</option><option>No</option>
									</select>
									<input v-else-if="f.control === 'date'" type="date" class="jv-action-input" v-model="f.value" />
									<input v-else-if="f.control === 'datetime'" type="datetime-local" class="jv-action-input" v-model="f.value" />
									<input v-else-if="f.control === 'time'" type="time" class="jv-action-input" v-model="f.value" />
									<input v-else-if="f.control === 'number'" type="number" class="jv-action-input" v-model="f.value" />
									<textarea v-else-if="f.control === 'text'" class="jv-action-input" v-model="f.value" rows="3"></textarea>
									<input v-else class="jv-action-input" v-model="f.value" />
								</div>
							</div>
						</div>
						<div v-for="(t, ti) in draftPanel.tables" :key="t.fieldname" class="jv-draft-table">
							<div class="jv-draft-table-title">{{ t.label }}</div>
							<div class="jv-draft-gridwrap">
								<table class="jv-grid">
									<thead><tr><th v-for="c in t.columns" :key="c.fieldname">{{ c.label }}</th><th class="jv-grid-x"></th></tr></thead>
									<tbody>
										<tr v-for="(r, ri) in t.rows" :key="ri">
											<td v-for="c in t.columns" :key="c.fieldname" :class="{ 'jv-grid-ro': c.read_only }">
												<span v-if="c.read_only">{{ r[c.fieldname] }}</span>
												<template v-else-if="c.fieldtype === 'Link'">
													<input class="jv-action-input" v-model="r[c.fieldname]"
													       @input="onDraftLink('t:' + ti + ':' + ri + ':' + c.fieldname, () => r[c.fieldname], c.options, $event)"
													       @focus="onDraftLink('t:' + ti + ':' + ri + ':' + c.fieldname, () => r[c.fieldname], c.options, $event)"
													       @blur="closeDraftLink" autocomplete="off" />
													<div v-if="draftLink.open && draftLink.key === 't:' + ti + ':' + ri + ':' + c.fieldname && draftLink.items.length"
													     class="jv-action-linkmenu" :class="{ up: draftLink.up }">
														<button v-for="it in draftLink.items" :key="it.value" @mousedown.prevent="pickDraftLink((v) => { r[c.fieldname] = v }, it)">
															<b>{{ it.value }}</b><span v-if="it.label"> — {{ it.label }}</span>
														</button>
													</div>
												</template>
												<input v-else-if="['Int','Float','Currency','Percent'].includes(c.fieldtype)" type="number" class="jv-action-input" v-model="r[c.fieldname]" />
												<input v-else-if="c.fieldtype === 'Date'" type="date" class="jv-action-input" v-model="r[c.fieldname]" />
												<select v-else-if="c.fieldtype === 'Check'" class="jv-action-input jv-action-sel" v-model="r[c.fieldname]">
													<option value="1">Yes</option><option value="0">No</option>
												</select>
												<input v-else class="jv-action-input" v-model="r[c.fieldname]" />
											</td>
											<td class="jv-grid-x"><button class="jv-grid-del" @click="removeDraftRow(ti, ri)" title="Remove row" aria-label="Remove row">✕</button></td>
										</tr>
									</tbody>
								</table>
							</div>
							<button class="jv-draft-addrow" @click="addDraftRow(ti)">＋ Add row</button>
						</div>
						<div v-if="draftTotals" class="jv-draft-totals">{{ draftTotals }} <span class="jv-draft-est">(estimate — ERPNext computes final totals)</span></div>
						<div v-if="draftPanel.error" class="jv-draft-error">{{ draftPanel.error }}</div>
					</div>
					<div class="jv-draft-foot">
						<button class="jv-action-discard" @click="discardDraft">Discard</button>
						<button v-if="draftPanel.submittable && draftPanel.verb === 'create'" class="jv-action-2nd" style="margin-left:auto" :disabled="draftPanel.applying" @click="applyDraft(1)">Create &amp; Submit</button>
						<button class="jv-action-primary" :style="draftPanel.submittable && draftPanel.verb === 'create' ? '' : 'margin-left:auto'" :disabled="draftPanel.applying" @click="applyDraft(0)">
							{{ draftPanel.applying ? 'Saving…' : draftCta }}
						</button>
					</div>
				</aside>
			</div>
		</transition>
	</div>
</template>

<script setup>
import { ref, computed, inject, onMounted, onBeforeUnmount, nextTick, watch } from "vue"
import { useRoute } from "vue-router"
import * as api from "@/api"
import { renderMarkdown } from "@/markdown"
import JvChart from "@/charts/JvChart.vue"

const session = inject("$session")
const socket = inject("$socket")
const route = useRoute()

const conversations = ref([])
const currentId = ref(null)
// Remember the open chat per-device so a refresh — or a duplicated tab — restores
// it instead of jumping to whatever sorts first in the sidebar (e.g. a starred
// chat). Also lets a duplicated tab land on the SAME in-progress conversation.
watch(currentId, (id) => {
	try {
		id ? localStorage.setItem("jarvis-last-conv", id) : localStorage.removeItem("jarvis-last-conv")
	} catch (e) {}
})
const messages = ref([])
const input = ref("")
// Per-conversation composer drafts: switching chats stashes the leaving
// chat's unsent text here and restores the target chat's own draft, so a
// draft never bleeds into another conversation (and is never lost on an
// accidental switch).
const drafts = ref({})
// Up/Down recall of previously sent prompts (shell-style history).
const promptHistory = ref([])
const histIdx = ref(null)
const histDraft = ref("")
const sending = ref(false)
const waiting = ref(false)
const search = ref("")
const ui = ref({})
const inputEl = ref(null)
const threadEl = ref(null)
const threadInnerEl = ref(null)
const rootEl = ref(null)
// Jump-to-latest arrow: shown when the thread is scrolled up away from the newest
// message. `pinnedToBottom` tracks whether we should auto-stick to the bottom as
// content grows (streaming replies, late-loading images/charts) — true until the
// user deliberately scrolls up.
const showScrollDown = ref(false)
const pinnedToBottom = ref(true)

// ---- Reusable notifier + confirm dialog ------------------------------------
// notify("Deleted", { type: "success" }) drops a lightweight toast that stacks
// bottom-right and auto-dismisses. confirmDialog({...}) shows a centered confirm
// modal and resolves true/false — a drop-in replacement for the native
// window.confirm() used across destructive actions (delete chat/skill/macro).
// Both are intentionally generic so any new call site can reuse them.
const notes = ref([])
let _noteSeq = 0
function notify(message, opts = {}) {
	const id = ++_noteSeq
	notes.value = [...notes.value, { id, message, type: opts.type || "info", title: opts.title || "" }]
	const ttl = opts.duration == null ? 3200 : opts.duration
	if (ttl > 0) setTimeout(() => dismissNote(id), ttl)
	return id
}
function dismissNote(id) {
	notes.value = notes.value.filter((n) => n.id !== id)
}
const confirmBox = ref(null) // { title, message, confirmLabel, cancelLabel, danger }
let _confirmResolve = null
function confirmDialog(opts = {}) {
	return new Promise((resolve) => {
		_confirmResolve = resolve
		confirmBox.value = {
			title: opts.title || "Are you sure?",
			message: opts.message || "",
			confirmLabel: opts.confirmLabel || "Confirm",
			cancelLabel: opts.cancelLabel || "Cancel",
			danger: opts.danger !== false, // deletes default to the red confirm button
		}
	})
}
function _settleConfirm(val) {
	confirmBox.value = null
	const r = _confirmResolve
	_confirmResolve = null
	if (r) r(val)
}
const userMenuOpen = ref(false)
const modelMenuOpen = ref(false)
// Collapsible sidebar (persisted per device, openclaw-style).
// Below this width the sidebar auto-collapses to the icon rail so a narrow /
// half-screen window doesn't let it crowd the chat.
const SIDEBAR_NARROW_BP = 820
const _sidebarNarrow = () => typeof window !== "undefined" && window.matchMedia(`(max-width: ${SIDEBAR_NARROW_BP}px)`).matches
function _sidebarPref() {
	try { return localStorage.getItem("jarvis-sidebar") === "collapsed" } catch (e) { return false }
}
// Initial: forced collapsed on a narrow viewport, else the saved preference.
const sidebarCollapsed = ref(_sidebarNarrow() || _sidebarPref())
function toggleSidebar() {
	sidebarCollapsed.value = !sidebarCollapsed.value
	// Only persist as the user's preference on wide screens; on a narrow window
	// the collapse is width-driven, so a manual toggle there is temporary and
	// must not overwrite the saved preference.
	if (!_sidebarNarrow()) {
		try { localStorage.setItem("jarvis-sidebar", sidebarCollapsed.value ? "collapsed" : "open") } catch (e) {}
	}
}
// React to viewport width crossing the breakpoint: collapse when it goes
// narrow, restore the saved preference when it goes wide again.
let _sidebarMq = null
function _applySidebarForWidth() {
	sidebarCollapsed.value = _sidebarNarrow() ? true : _sidebarPref()
}
onMounted(() => {
	if (typeof window === "undefined") return
	_sidebarMq = window.matchMedia(`(max-width: ${SIDEBAR_NARROW_BP}px)`)
	_sidebarMq.addEventListener("change", _applySidebarForWidth)
})
onBeforeUnmount(() => {
	if (_sidebarMq) _sidebarMq.removeEventListener("change", _applySidebarForWidth)
})
// per-conversation ⋯ menu + inline rename (sidebar)
const convMenuFor = ref(null)
const renamingId = ref(null)
const renameText = ref("")
function toggleConvMenu(id) {
	convMenuFor.value = convMenuFor.value === id ? null : id
}
async function toggleStar(c) {
	convMenuFor.value = null
	const next = c.starred ? 0 : 1
	const conv = conversations.value.find((x) => x.name === c.name)
	if (conv) conv.starred = next // optimistic — regroups instantly
	try {
		await api.setStar(c.name, next)
	} catch (e) {
		loadConversations()
	}
}
function startRename(c) {
	convMenuFor.value = null
	renamingId.value = c.name
	renameText.value = c.title || ""
	nextTick(() => {
		const el = document.querySelector(".jv-rename-input")
		if (el) {
			el.focus()
			el.select()
		}
	})
}
function cancelRename() {
	renamingId.value = null
}
async function commitRename(c) {
	if (renamingId.value !== c.name) return
	const t = renameText.value.trim()
	renamingId.value = null
	if (!t || t === (c.title || "")) return
	const conv = conversations.value.find((x) => x.name === c.name)
	if (conv) conv.title = t // optimistic
	try {
		await api.renameConversation(c.name, t)
	} catch (e) {
		loadConversations()
	}
}
async function deleteConv(c) {
	convMenuFor.value = null
	if (!(await confirmDialog({ title: "Delete chat?", message: `Delete "${c.title || "this chat"}"? This can't be undone.`, confirmLabel: "Delete" }))) return
	try {
		await api.archiveConversation(c.name)
		notify("Chat deleted", { type: "success" })
	} catch (e) {
		/* ignore */
	}
	if (currentId.value === c.name) {
		currentId.value = null
		messages.value = []
	}
	loadConversations()
}
const modelOverride = ref("")

// ---- settings panel + theme (openclaw-style console) ----
const settingsOpen = ref(false)
const settingsTab = ref("overview")

// --- Custom skills (Skills settings tab + "/" composer menu) ---
const customSkills = ref([])
const skillFormOpen = ref(false)
const skillSaving = ref(false)
const skillError = ref("")
const skillForm = ref({ name: "", skill_name: "", description: "", instructions: "", user_invocable: true, enabled: true })
const skillsSync = ref({ last_sync_status: "", pending: false })
let _skillsPoll = null
// Read-only view of a skill someone shared with me (no editing, saving or toggles).
const skillReadonly = ref(false)
const skillSharedBy = ref("")

// --- Skill sharing (owners share read-only use with specific users) ---
const shareModalOpen = ref(false)
const shareSkill = ref({ name: "", skill_name: "" })
const shareSearch = ref("")
const shareCandidates = ref([]) // [{name, full_name}]
const shareSelected = ref([]) // array of user ids
const shareLoading = ref(false)
const shareSaving = ref(false)

// Own skills vs skills shared with me (both arrive in customSkills).
const mySkills = computed(() => customSkills.value.filter((s) => s.mine))
const sharedSkills = computed(() => customSkills.value.filter((s) => !s.mine))

// Candidate rows filtered by the search box; selected users always stay visible.
const shareMatches = computed(() => {
	const q = (shareSearch.value || "").trim().toLowerCase()
	if (!q) return shareCandidates.value
	return shareCandidates.value.filter((u) =>
		(u.full_name || "").toLowerCase().includes(q) || (u.name || "").toLowerCase().includes(q))
})

function _shareInitials(u) {
	const s = (u && (u.full_name || u.name) || "").trim()
	if (!s) return "?"
	const parts = s.split(/\s+/).filter(Boolean)
	if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
	return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}
function _shareUser(id) {
	return shareCandidates.value.find((u) => u.name === id) || { name: id, full_name: id }
}
function isShareSelected(id) {
	return shareSelected.value.includes(id)
}
function toggleShareUser(id) {
	if (shareSelected.value.includes(id)) shareSelected.value = shareSelected.value.filter((x) => x !== id)
	else shareSelected.value = [...shareSelected.value, id]
}
async function openShareModal(s) {
	shareSkill.value = { name: s.name, skill_name: s.skill_name }
	shareSearch.value = ""
	shareSelected.value = []
	shareCandidates.value = []
	shareModalOpen.value = true
	shareLoading.value = true
	try {
		const [cand, shares] = await Promise.all([api.listShareableUsers(), api.getSkillShares(s.name)])
		shareCandidates.value = cand || []
		shareSelected.value = ((shares && shares.users) || []).map((u) => u.name)
		// Make sure already-shared users are selectable even if not in the candidate list.
		const known = new Set(shareCandidates.value.map((u) => u.name))
		for (const u of ((shares && shares.users) || [])) {
			if (!known.has(u.name)) { shareCandidates.value.push({ name: u.name, full_name: u.full_name || u.name }); known.add(u.name) }
		}
	} catch (e) { notify(_skillErr(e), { type: "error" }) } finally { shareLoading.value = false }
}
function closeShareModal() {
	shareModalOpen.value = false
	shareSaving.value = false
}
async function saveShares() {
	shareSaving.value = true
	try {
		await api.shareCustomSkill(shareSkill.value.name, [...shareSelected.value])
		await loadCustomSkills()
		notify("Sharing updated", { type: "success" })
		closeShareModal()
	} catch (e) { notify(_skillErr(e), { type: "error" }); shareSaving.value = false }
}

function _skillErr(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}
async function loadCustomSkills() {
	try { customSkills.value = (await api.listCustomSkills()) || [] } catch (e) { /* keep prior */ }
}
async function loadSkillsSync() {
	try {
		const s = (await api.getCustomSkillsSyncStatus()) || {}
		skillsSync.value = { last_sync_status: s.last_sync_status || "", pending: !!s.pending }
	} catch (e) { /* ignore */ }
}
// The right skills sidebar is always present as a slim icon rail (collapsed);
// clicking the rail expands it. openclaw-style, mirrors the left sidebar rail.
const skillsModalOpen = ref(false)
function openSkillsModal(openForm) {
	skillsModalOpen.value = true
	skillError.value = ""
	loadCustomSkills()
	loadSkillsSync()
	if (openForm === true) newSkill()
	else skillFormOpen.value = false
}
function closeSkillsModal() {
	skillsModalOpen.value = false
	skillFormOpen.value = false
	skillReadonly.value = false
	skillSharedBy.value = ""
	skillError.value = ""
}
// Push the current skills to the assistant — the old "Apply", now run
// automatically on save/delete. No confirm: an empty set legitimately clears
// all custom skills (e.g. after deleting the last one).
async function syncSkills() {
	try {
		await api.applyCustomSkills()
		skillsSync.value = { last_sync_status: "pending: applying skills", pending: true }
		if (_skillsPoll) clearInterval(_skillsPoll)
		_skillsPoll = setInterval(async () => {
			await loadSkillsSync()
			if (!skillsSync.value.pending) { clearInterval(_skillsPoll); _skillsPoll = null }
		}, 3000)
	} catch (e) { skillError.value = _skillErr(e) }
}
function newSkill() {
	skillError.value = ""
	skillReadonly.value = false
	skillSharedBy.value = ""
	skillForm.value = { name: "", skill_name: "", description: "", instructions: "", user_invocable: true, enabled: true }
	skillFormOpen.value = true
}
async function editSkill(s) {
	skillError.value = ""
	// Shared-with-me skills open read-only: no editing, saving or toggles.
	skillReadonly.value = !s.mine
	skillSharedBy.value = ""
	try {
		const full = await api.getCustomSkill(s.name)
		skillForm.value = {
			name: full.name, skill_name: full.skill_name, description: full.description || "",
			instructions: full.instructions || "", user_invocable: !!full.user_invocable, enabled: !!full.enabled,
		}
		if (full.can_edit === 0 || !s.mine) skillReadonly.value = true
		skillSharedBy.value = full.shared_by || s.shared_by || ""
		skillFormOpen.value = true
	} catch (e) { skillError.value = _skillErr(e) }
}
async function saveSkill() {
	skillError.value = ""
	skillSaving.value = true
	try {
		const f = skillForm.value
		const payload = {
			skill_name: (f.skill_name || "").trim().toLowerCase(),
			description: f.description, instructions: f.instructions,
			user_invocable: f.user_invocable ? 1 : 0, enabled: f.enabled ? 1 : 0,
		}
		if (f.name) await api.updateCustomSkill({ name: f.name, ...payload })
		else await api.createCustomSkill(payload)
		skillFormOpen.value = false
		await loadCustomSkills()
		syncSkills() // saving pushes to the assistant automatically
	} catch (e) { skillError.value = _skillErr(e) } finally { skillSaving.value = false }
}
async function removeSkill(s) {
	if (!(await confirmDialog({ title: "Delete skill?", message: `Delete “${s.skill_name}”? It will be removed from your assistant.`, confirmLabel: "Delete" }))) return
	try {
		await api.deleteCustomSkill(s.name)
		await loadCustomSkills()
		syncSkills() // deleting updates the assistant automatically
		notify("Skill deleted", { type: "success" })
	} catch (e) { skillError.value = _skillErr(e) }
}

// --- Macros (customer-authored prompt sequences run as chained turns) ---
const macros = ref([])
const macrosModalOpen = ref(false)
const macroEditorOpen = ref(false)
const macroSaving = ref(false)
const macroError = ref("")
const macroForm = ref(_blankMacro())
// The live macro-run banner: { run, conversation, step, total, label, status }.
const macroRun = ref(null)
let _macroDoneTimer = null

function _blankMacro() {
	return {
		name: "", macro_name: "", description: "",
		enabled: true, stop_on_error: true,
		schedule_enabled: false, schedule_frequency: "daily", schedule_time: "09:00",
		steps: [],
	}
}
// Skills taggable on a macro STEP: my own + shared-with-me, enabled only (a
// disabled skill can't be invoked, so offering it would silently no-op).
const macroSkillOptions = computed(() => customSkills.value.filter((s) => s.enabled))
function toggleStepSkill(si, name) {
	const st = macroForm.value.steps[si]
	if (!st) return
	if (!Array.isArray(st.skills)) st.skills = []
	const i = st.skills.indexOf(name)
	if (i >= 0) st.skills.splice(i, 1)
	else st.skills.push(name)
}
async function loadMacros() {
	try { macros.value = (await api.listMacros()) || [] } catch (e) { /* keep prior */ }
}
function openMacrosModal() {
	macrosModalOpen.value = true
	macroError.value = ""
	loadMacros()
}
function closeMacrosModal() {
	macrosModalOpen.value = false
	macroError.value = ""
}
function closeMacroEditor() {
	macroEditorOpen.value = false
	macroError.value = ""
}
function newMacro() {
	macroError.value = ""
	macroForm.value = _blankMacro()
	macroForm.value.steps = [{ label: "", prompt: "", skills: [] }]
	loadSkillsSync() // populate the taggable-skills options
	macroEditorOpen.value = true
}
async function editMacro(m) {
	macroError.value = ""
	try {
		const full = await api.getMacro(m.name)
		macroForm.value = {
			name: full.name,
			macro_name: full.macro_name || "",
			description: full.description || "",
			enabled: full.enabled == null ? true : !!full.enabled,
			stop_on_error: !!full.stop_on_error,
			schedule_enabled: !!full.schedule_enabled,
			schedule_frequency: full.schedule_frequency || "daily",
			schedule_time: full.schedule_time || "09:00",
			steps: (Array.isArray(full.steps) ? full.steps : []).map((s) => ({ label: s.label || "", prompt: s.prompt || "", skills: Array.isArray(s.skills) ? [...s.skills] : [] })),
		}
		if (!macroForm.value.steps.length) macroForm.value.steps = [{ label: "", prompt: "", skills: [] }]
		loadSkillsSync() // populate the taggable-skills options
		macroEditorOpen.value = true
	} catch (e) { macroError.value = _skillErr(e) }
}
function addMacroStep() {
	macroForm.value.steps.push({ label: "", prompt: "", skills: [] })
}
function removeMacroStep(i) {
	macroForm.value.steps.splice(i, 1)
}
// Drag-to-reorder steps (premium replacement for up/down buttons). The grip
// handle is the drag source; the whole step card is the drop target.
const dragStepIdx = ref(null)
const dragOverIdx = ref(null)
function onStepDragStart(i, e) {
	dragStepIdx.value = i
	if (e && e.dataTransfer) {
		e.dataTransfer.effectAllowed = "move"
		try { e.dataTransfer.setData("text/plain", String(i)) } catch (_) { /* ignore */ }
	}
}
function onStepDragOver(i) {
	if (dragStepIdx.value !== null) dragOverIdx.value = i
}
function onStepDragLeave(i) {
	if (dragOverIdx.value === i) dragOverIdx.value = null
}
function onStepDrop(i) {
	const from = dragStepIdx.value
	dragOverIdx.value = null
	if (from === null || from === i) { dragStepIdx.value = null; return }
	const steps = macroForm.value.steps
	const [it] = steps.splice(from, 1)
	steps.splice(i, 0, it)
	dragStepIdx.value = null
}
function onStepDragEnd() {
	dragStepIdx.value = null
	dragOverIdx.value = null
}
async function saveMacro() {
	macroError.value = ""
	const f = macroForm.value
	const steps = f.steps
		.map((s) => ({ label: (s.label || "").trim(), prompt: (s.prompt || "").trim(), skills: Array.isArray(s.skills) ? s.skills : [] }))
		.filter((s) => s.prompt)
	if (!(f.macro_name || "").trim()) { macroError.value = "Give the macro a name."; return }
	if (!steps.length) { macroError.value = "Add at least one step with a prompt."; return }
	macroSaving.value = true
	try {
		const payload = {
			macro_name: f.macro_name.trim(),
			description: f.description || "",
			steps,
			enabled: f.enabled ? 1 : 0,
			stop_on_error: f.stop_on_error ? 1 : 0,
			schedule_enabled: f.schedule_enabled ? 1 : 0,
			schedule_frequency: f.schedule_frequency || "daily",
			schedule_time: f.schedule_time || "09:00",
		}
		let savedName = f.name
		if (f.name) {
			await api.updateMacro({ name: f.name, ...payload })
		} else {
			const r = await api.createMacro(payload)
			savedName = r && r.data && r.data.name
		}
		macroEditorOpen.value = false
		await loadMacros()
		if (savedName && steps.length >= 2) startMacroMerge(savedName, payload.macro_name, steps.length)
	} catch (e) { macroError.value = _skillErr(e) } finally { macroSaving.value = false }
}

// --- Macro merge: on every 2+ step save, generate a single merged prompt in
// the background and let the user adopt or keep the sequence. ---
const macroMerge = ref(null) // {macro, macroName, conversation, steps, status:'pending'|'ready'|'unmergeable', merge, editedPrompt, applying, error}
const mergeNotice = ref("")
let _mergeNoticeTimer = null
function _showMergeNotice(text) {
	mergeNotice.value = text
	if (_mergeNoticeTimer) clearTimeout(_mergeNoticeTimer)
	_mergeNoticeTimer = setTimeout(() => { mergeNotice.value = "" }, 6000)
}

async function startMacroMerge(name, macroName, stepCount) {
	let conversation
	try {
		const r = await api.summarizeMacro(name)
		conversation = r && r.conversation
	} catch (e) { return } // macro already saved — merging is optional sugar
	if (!conversation) return
	macroMerge.value = {
		macro: name, macroName, conversation, steps: stepCount,
		status: "pending", merge: null, editedPrompt: "", applying: false, error: "",
	}
	_pollMacroMerge(conversation)
}

async function _pollMacroMerge(conversation) {
	for (let i = 0; i < 30; i++) { // 30 × 3s ≈ 90s budget
		await new Promise((res) => setTimeout(res, 3000))
		const mm = macroMerge.value
		if (!mm || mm.conversation !== conversation) return // modal closed / superseded
		let r
		try { r = await api.getMacroMerge(conversation) } catch (e) { continue }
		if (!macroMerge.value || macroMerge.value.conversation !== conversation) return
		if (!r || r.status === "pending") continue
		if (r.status === "ready" && r.merge && r.merge.mergeable) {
			macroMerge.value = { ...macroMerge.value, status: "ready", merge: r.merge, editedPrompt: r.merge.merged_prompt }
		} else if (r.status === "ready") {
			macroMerge.value = { ...macroMerge.value, status: "unmergeable", merge: r.merge }
		} else {
			dropMacroMerge("Couldn't generate a merged prompt — macro saved as a sequence.")
		}
		return
	}
	dropMacroMerge("Merging timed out — macro saved as a sequence.")
}

function dropMacroMerge(notice) {
	const mm = macroMerge.value
	macroMerge.value = null
	if (mm) api.discardMacroMerge(mm.conversation).catch(() => {})
	if (notice) _showMergeNotice(notice)
}

async function acceptMacroMerge() {
	const mm = macroMerge.value
	if (!mm || mm.applying) return
	mm.applying = true
	mm.error = ""
	try {
		await api.applyMacroMerge(mm.macro, mm.editedPrompt, mm.conversation)
		macroMerge.value = null
		_showMergeNotice("Macro merged into one prompt.")
		loadMacros()
	} catch (e) {
		mm.applying = false
		mm.error = (e && e.messages && e.messages[0]) || (e && e.message) || "Could not apply the merge."
	}
}

async function removeMacro(m) {
	if (!(await confirmDialog({ title: "Delete macro?", message: `Delete “${m.macro_name}”? This can't be undone.`, confirmLabel: "Delete" }))) return
	try {
		await api.deleteMacro(m.name)
		await loadMacros()
		notify("Macro deleted", { type: "success" })
	} catch (e) { macroError.value = _skillErr(e) }
}
async function runMacroFromList(m) {
	macroError.value = ""
	try {
		const res = await api.runMacro(m.name)
		const data = (res && res.data) || res || {}
		macrosModalOpen.value = false
		await loadConversations()
		if (data.conversation) await selectConversation(data.conversation)
		macroRun.value = {
			run: data.macro_run,
			conversation: data.conversation,
			step: 0,
			total: m.step_count || 0,
			label: "",
			status: "running",
		}
	} catch (e) {
		macroError.value = _skillErr(e)
		macrosModalOpen.value = true
	}
}
async function stopMacro() {
	if (!macroRun.value) return
	try { await api.stopMacroRun(macroRun.value.run) } catch (e) { /* ignore */ }
}

// ---- Macro run history dashboard (settings → Macro runs) ----
const MACRO_RUN_PAGE = 30
const macroRuns = ref([])
const macroRunStats = ref(null)
const macroRunStatus = ref("") // "" = all
const macroRunMacro = ref("") // "" = all macros
const macroRunStart = ref(0)
const macroRunHasMore = ref(false)
const macroRunsLoading = ref(false)
const MACRO_RUN_STATUSES = ["", "running", "completed", "failed", "stopped"]

async function loadMacroRunStats() {
	try { macroRunStats.value = await api.macroRunStats() } catch (e) { /* keep prior */ }
}
// reset=true starts a fresh page-1 load (also refreshes stats + the macro
// filter options); reset=false appends the next page ("Load more").
async function loadMacroRuns(reset = true) {
	if (macroRunsLoading.value) return
	macroRunsLoading.value = true
	if (reset) {
		macroRunStart.value = 0
		loadMacroRunStats()
		if (!macros.value.length) loadMacros() // populate the macro filter dropdown
	}
	try {
		const r = await api.listMacroRuns({
			status: macroRunStatus.value,
			macro: macroRunMacro.value,
			limit: MACRO_RUN_PAGE,
			start: macroRunStart.value,
		})
		const rows = (r && r.runs) || []
		macroRuns.value = reset ? rows : [...macroRuns.value, ...rows]
		macroRunHasMore.value = !!(r && r.has_more)
		macroRunStart.value += rows.length
	} catch (e) { /* keep the last-good list */ } finally { macroRunsLoading.value = false }
}
function setMacroRunStatus(s) { macroRunStatus.value = s; loadMacroRuns(true) }
function setMacroRunMacro(e) { macroRunMacro.value = e.target.value; loadMacroRuns(true) }

// Row actions -------------------------------------------------------------
async function openRunConversation(run) {
	if (!run.conversation) return
	settingsOpen.value = false
	await loadConversations()
	await selectConversation(run.conversation)
}
async function rerunFromHistory(run) {
	try {
		const res = await api.runMacro(run.macro)
		const data = (res && res.data) || res || {}
		settingsOpen.value = false
		await loadConversations()
		if (data.conversation) await selectConversation(data.conversation)
		macroRun.value = { run: data.macro_run, conversation: data.conversation, step: 0, total: 0, label: "", status: "running" }
	} catch (e) { notify(_skillErr(e), { type: "error" }) }
}
async function stopRunFromHistory(run) {
	try {
		await api.stopMacroRun(run.name)
		run.status = "stopped" // optimistic patch
		loadMacroRunStats()
	} catch (e) { notify(_skillErr(e), { type: "error" }) }
}

// Formatters --------------------------------------------------------------
function macroRunBadge(status) {
	return { completed: "ok", failed: "err", running: "run", queued: "run", stopped: "stop" }[status] || "stop"
}
function fmtAgo(dt) {
	if (!dt) return ""
	const t = new Date(String(dt).replace(" ", "T")).getTime()
	if (isNaN(t)) return ""
	const s = Math.max(0, Math.floor((Date.now() - t) / 1000))
	if (s < 60) return "just now"
	const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`
	const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`
	const d = Math.floor(h / 24); if (d < 7) return `${d}d ago`
	return new Date(t).toLocaleDateString()
}
function fmtDuration(sec) {
	if (sec == null) return ""
	sec = Math.max(0, Math.round(sec))
	if (sec < 60) return `${sec}s`
	const m = Math.floor(sec / 60), s = sec % 60
	if (m < 60) return s ? `${m}m ${s}s` : `${m}m`
	const h = Math.floor(m / 60)
	return `${h}h ${m % 60}m`
}
// Elapsed for a run that hasn't finished (running/queued) — shows "· 18s".
function macroRunElapsed(run) {
	if (run.duration_s != null || !run.started_at) return fmtDuration(run.duration_s)
	const t = new Date(String(run.started_at).replace(" ", "T")).getTime()
	if (isNaN(t)) return ""
	return fmtDuration((Date.now() - t) / 1000) + " elapsed"
}
// Live-patch an open dashboard from macro:progress / macro:done events.
function patchMacroRunRow(p, done) {
	if (!settingsOpen.value || settingsTab.value !== "macroruns") return
	const row = macroRuns.value.find((r) => r.name === p.macro_run)
	if (row) {
		if (p.step != null) row.current_step = p.step
		row.status = done ? (p.status || "completed") : "running"
	}
	loadMacroRunStats()
}
// Load the dashboard when the user enters the Macro runs tab (fresh each time).
watch(
	() => settingsOpen.value && settingsTab.value === "macroruns",
	(active) => { if (active) loadMacroRuns(true) },
)
// A ```jarvis-macro card's "Save as macro" button: pre-fill the editor.
function openMacroFromCard(card) {
	macroError.value = ""
	macroForm.value = _blankMacro()
	macroForm.value.macro_name = card.name || ""
	macroForm.value.description = card.description || ""
	macroForm.value.steps = (card.steps || []).map((s) => ({ label: s.label || "", prompt: s.prompt || "" }))
	if (!macroForm.value.steps.length) macroForm.value.steps = [{ label: "", prompt: "" }]
	macroEditorOpen.value = true
}
// Header "Save as macro": collect this chat's user prompts into the editor.
const canSaveAsMacro = computed(
	() => !!currentId.value && messages.value.some((m) => m.role === "user" && m.content && !m.content.startsWith("▶ Running macro")),
)
function saveConversationAsMacro() {
	macroError.value = ""
	const steps = messages.value
		.filter((m) => m.role === "user" && m.content && !m.content.startsWith("▶ Running macro"))
		.map((m) => ({ label: "", prompt: m.content }))
	if (!steps.length) return
	macroForm.value = _blankMacro()
	macroForm.value.macro_name = currentTitle.value && currentTitle.value !== "New chat" ? currentTitle.value : ""
	macroForm.value.steps = steps
	macroEditorOpen.value = true
}
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
// Dark = "Refined Indigo" (chosen 2026-07-02): neutral charcoal surfaces with a
// crisper indigo accent; the brand mark gets an indigo→violet gradient below.
const DARK_VARS = {
	"--surface": "#16161a", "--surface-1": "#1d1d22", "--surface-2": "#26262d", "--surface-3": "#30303a",
	"--border": "#2c2c34", "--border-2": "#3a3a45",
	"--text": "#ededf2", "--text-2": "#b6b6c0", "--text-3": "#7e7e8a",
	"--blue": "#6e8bff", "--blue-bg": "#1e2749", "--blue-bd": "#34437a",
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
// Quick header toggle: flip between light and dark (drops out of 'system').
function toggleTheme() {
	setTheme(effectiveDark.value ? "light" : "dark")
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
// Flip "confirm before changes" (server-side, per site). Optimistic; reverts on
// failure. Stored as auto_apply_changes (1 = skip confirmation / auto mode).
async function toggleAutoApply() {
	const next = ui.value.auto_apply_changes ? 0 : 1
	ui.value = { ...ui.value, auto_apply_changes: next }
	try {
		await api.setAutoApply(next)
	} catch (e) {
		ui.value = { ...ui.value, auto_apply_changes: next ? 0 : 1 } // revert
	}
}
async function deleteChat() {
	const id = currentId.value
	if (!id) return
	if (!(await confirmDialog({ title: "Delete chat?", message: "Delete this chat? It will be removed from your history.", confirmLabel: "Delete" }))) return
	try {
		await api.archiveConversation(id)
		notify("Chat deleted", { type: "success" })
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
// Tool names for the "Tools available" count + the /tool autocomplete. Seeded
// with the core set as a fallback, then replaced on mount with the live bench
// registry (jarvis.chat.api.list_tools) so it reflects every registered tool
// instead of drifting from a hardcoded list.
const jarvisTools = ref([
	"get_list", "get_doc", "get_schema", "query", "run_report",
	"create_doc", "update_doc", "submit_doc", "cancel_doc", "amend_doc", "delete_doc",
])

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
// Empty override = "Auto": the backend falls back to Jarvis Settings.llm_model.
const modelLabel = computed(() => modelOverride.value || "Auto")
const availableModels = computed(() => ui.value.subscription_models?.[ui.value.llm_provider] || [])

const currentTitle = computed(
	() => conversations.value.find((c) => c.name === currentId.value)?.title || "New chat",
)
const visibleMessages = computed(() =>
	messages.value.filter((m) => m.role === "user" || m.role === "assistant"),
)
// Group role=tool messages under the assistant turn they belong to, so each
// answer can show an expandable "Activity" list of the tool calls (with input
// + output) that produced it — openclaw-style. Tool rows follow their
// assistant placeholder in seq order, so we attach to the most recent
// assistant message and reset on each user message.
const activityByAssistant = computed(() => {
	const map = {}
	let cur = null
	for (const m of messages.value) {
		if (m.role === "user") cur = null
		else if (m.role === "assistant") { cur = m.name; if (!map[cur]) map[cur] = [] }
		else if (m.role === "tool" && cur) (map[cur] || (map[cur] = [])).push(m)
	}
	return map
})
const activityOpen = ref({})
const toolOpen = ref({})
// Whether replies reveal which tools + skills produced them. When off, the
// chat shows only a generic "Thinking…/Working…" indicator and hides the
// per-reply tool/skill chips. Persisted per device.
const showActivityDetail = ref(localStorage.getItem("jarvis-activity-detail") === "1")
function setActivityDetail(v) {
	showActivityDetail.value = !!v
	try { localStorage.setItem("jarvis-activity-detail", v ? "1" : "0") } catch (e) {}
}
// In-flight wording shown while a turn runs (tool-activity hidden). Kept to a
// single neutral "Thinking\u2026" \u2014 no task-describing phrases that could overclaim.
const THINK_WORDS = ["Thinking\u2026"]
const thinkTick = ref(0)
let _thinkTimer = null
const thinkingWord = computed(() => THINK_WORDS[thinkTick.value % THINK_WORDS.length])
// Persisted per-reply tool count + duration so they survive a refresh (runMeta
// is live-session only): count from the saved tool messages, duration from the
// assistant row's modified-minus-creation span (clamped to a sane window).
function toolCountOf(m) { return (activityByAssistant.value[m.name] || []).length }
function elapsedOf(m) {
	const live = runMeta.value[m.name] && runMeta.value[m.name].ms
	if (live) return (live / 1000).toFixed(1)
	if (m.creation && m.modified) {
		const d = (new Date(m.modified.replace(" ", "T")) - new Date(m.creation.replace(" ", "T"))) / 1000
		if (d >= 0 && d < 1800) return d.toFixed(1)
	}
	return ""
}
// Open state falls back to the pref until the user explicitly toggles a turn.
function isActivityOpen(name) {
	return name in activityOpen.value ? activityOpen.value[name] : false
}
function toggleActivity(name) { activityOpen.value = { ...activityOpen.value, [name]: !isActivityOpen(name) } }
function toggleTool(name) { toolOpen.value = { ...toolOpen.value, [name]: !toolOpen.value[name] } }
function toolLabel(n) { return (n || "tool").replace(/^jarvis__/, "") }
function activityNames(assistantName) {
	return (activityByAssistant.value[assistantName] || [])
		.map((t) => toolLabel(t.tool_name)).join(", ")
}
// args/result are stored as JSON strings — pretty-print, and trim very large
// payloads so a 10k-row result doesn't blow up the chat.
function prettyJson(s) {
	if (s == null || s === "") return ""
	let v = s
	try { v = typeof s === "string" ? JSON.parse(s) : s } catch (e) { return String(s).slice(0, 4000) }
	let out = ""
	try { out = JSON.stringify(v, null, 2) } catch (e) { out = String(s) }
	return out.length > 4000 ? out.slice(0, 4000) + "\n… (truncated)" : out
}
// True only until the initial conversation load finishes — keeps the welcome
// screen from flashing on refresh before the open chat appears.
const booting = ref(true)
const showWelcome = computed(
	() => !booting.value && (!currentId.value || visibleMessages.value.length === 0),
)

// settings/overview derived metrics (all from data we already hold)
const convCount = computed(() => conversations.value.length)
const msgCount = computed(() => visibleMessages.value.length)
const toolCount = computed(() => jarvisTools.value.length)
const sessionToolCalls = computed(() =>
	Object.values(runMeta.value).reduce((s, r) => s + (r.tools || 0), 0),
)
const userMsgCount = computed(() => visibleMessages.value.filter((m) => m.role === "user").length)
const assistantMsgCount = computed(() => visibleMessages.value.filter((m) => m.role === "assistant").length)
const avgTokensPerMsg = computed(() => {
	const n = msgCount.value
	if (!usage.value || !n) return "—"
	return fmtTokens(Math.round((usage.value.chat_tokens || 0) / n))
})
const starredCount = computed(() => conversations.value.filter((c) => c.starred).length)
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
	const starred = [], today = [], yest = [], earlier = []
	const now = new Date()
	const d0 = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
	for (const c of filteredConvs.value) {
		if (c.starred) {
			starred.push(c)
			continue
		}
		const raw = (c.last_active_at || c.modified || "").replace(" ", "T")
		const t = raw ? new Date(raw) : now
		const cd = new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime()
		const diff = Math.round((d0 - cd) / 86400000)
		if (diff <= 0) today.push(c)
		else if (diff === 1) yest.push(c)
		else earlier.push(c)
	}
	return [
		{ label: "Starred", items: starred },
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

// Inline action blocks the agent emits: a rich ```jarvis-action JSON card (a doc
// create/update confirm, or an email draft), or a simple ```confirm label as a
// fallback. The chat renders them as cards with buttons and strips the raw block
// from the visible prose.
const _ACTION_RE = /```jarvis-action[ \t]*\n([\s\S]*?)```/
const _CONFIRM_RE = /```confirm[ \t]*\n([\s\S]*?)```/
// Interactive clarifying questions: the agent emits a ```jarvis-ask JSON block
// (a list of questions, each single/multi/yesno with up to a few options); the
// chat renders it as option cards with one Submit, and strips the raw block.
const _ASK_RE = /```jarvis-ask[ \t]*\n([\s\S]*?)```/
// A ```jarvis-cards block: a list of record cards the chat renders as a
// horizontally-scrollable card strip instead of a wide Markdown table.
const _CARDS_RE = /```jarvis-cards[ \t]*\n([\s\S]*?)```/
// The agent declares which skill(s) it used to shape a reply in a ```jarvis-skill
// block; the chat shows a small chip and strips the raw block.
const _SKILL_RE = /```jarvis-skill[ \t]*\n([\s\S]*?)```/
// A ```jarvis-macro block: the agent proposes a reusable macro (name +
// description + ordered steps); the chat renders a "Save as macro" card that
// opens the macro editor pre-filled, and strips the raw JSON from the prose.
const _MACRO_RE = /```jarvis-macro[ \t]*\n([\s\S]*?)```/
// A ```jarvis-chart block: a high-level chart spec the chat renders inline with
// ECharts (themed by chartTheme; the agent never sends raw ECharts options).
const _CHART_RE = /```jarvis-chart[ \t]*\n([\s\S]*?)```/g
const _CHART_TYPES = new Set(["bar", "line", "area", "pie", "donut", "scatter", "bubble", "heatmap", "boxplot", "radar", "funnel", "gauge"])
// The agent keeps emitting ```mermaid xychart-beta for DATA charts instead of
// jarvis-chart. Mermaid renders xychart unstyled and crams the axis labels, so
// we intercept those blocks, parse the fixed xychart-beta grammar into a
// jarvis-chart spec, and render them through the themed ECharts path instead.
const _XYCHART_RE = /```mermaid[ \t]*\n([\s\S]*?)```/g
function _xySplit(s) {
	const out = []
	const re = /"([^"]*)"|'([^']*)'|([^,]+)/g
	let m
	while ((m = re.exec(s))) {
		const v = (m[1] ?? m[2] ?? m[3] ?? "").trim().replace(/^["']|["']$/g, "")
		if (v) out.push(v)
	}
	return out
}
function parseXychart(body) {
	const text = String(body || "")
	if (!/^\s*xychart-beta\b/.test(text)) return null
	const horizontal = /xychart-beta[ \t]+horizontal\b/.test(text)
	const tM = text.match(/title[ \t]+"([^"]*)"/)
	const yM = text.match(/y-axis[ \t]+"([^"]*)"/)
	const yLabel = yM ? yM[1].trim() : undefined
	let x = []
	const xM = text.match(/x-axis[ \t]+\[([^\]]*)\]/)
	if (xM) x = _xySplit(xM[1])
	const series = []
	let anyBar = false
	const re = /\b(bar|line)[ \t]+(?:"([^"]*)"[ \t]+)?\[([^\]]*)\]/g
	let m
	while ((m = re.exec(text))) {
		const data = _xySplit(m[3]).map(Number).filter((n) => !Number.isNaN(n))
		if (!data.length) continue
		if (m[1] === "bar") anyBar = true
		series.push({ name: m[2] || yLabel || "Value", data })
	}
	if (!series.length) return null
	const spec = { type: anyBar ? "bar" : "line", x, series }
	if (tM) spec.title = tM[1].trim()
	if (horizontal) spec.options = { horizontal: true }
	return spec
}
function stripBlocks(text) {
	return (text || "")
		.replace(/```jarvis-action[ \t]*\n[\s\S]*?```/g, "")
		.replace(/```confirm[ \t]*\n[\s\S]*?```/g, "")
		.replace(/```jarvis-ask[ \t]*\n[\s\S]*?```/g, "")
		.replace(/```jarvis-cards[ \t]*\n[\s\S]*?```/g, "")
		.replace(/```jarvis-skill[ \t]*\n[\s\S]*?```/g, "")
		.replace(/```jarvis-macro[ \t]*\n[\s\S]*?```/g, "")
		.replace(/```jarvis-chart[ \t]*\n[\s\S]*?```/g, "")
		.replace(/```mermaid[ \t]*\n[ \t]*xychart-beta[\s\S]*?```/g, "")
		.replace(/\n{3,}/g, "\n\n")
		.trim()
}
const _skillUsedCache = new Map()
function skillsUsedOf(m) {
	const content = (m && m.content) || ""
	if (!content.includes("jarvis-skill")) return []
	if (_skillUsedCache.has(content)) return _skillUsedCache.get(content)
	let names = []
	const mt = content.match(_SKILL_RE)
	if (mt) {
		names = mt[1]
			.split(/[\n,]+/)
			.map((s) => s.trim().replace(/^[-*]\s*/, ""))
			.filter(Boolean)
			.map((s) => s.replace(/^custom-/, "")) // hide the internal prefix
			.slice(0, 6)
		names = [...new Set(names)]
	}
	_skillUsedCache.set(content, names)
	return names
}
const _cardsCache = new Map()
function cardsOf(m) {
	const content = (m && m.content) || ""
	if (!content.includes("jarvis-cards")) return null
	if (_cardsCache.has(content)) return _cardsCache.get(content)
	let res = null
	const mt = content.match(_CARDS_RE)
	if (mt) {
		try {
			const a = JSON.parse(mt[1].trim())
			const list = Array.isArray(a) ? a : a && a.cards
			if (Array.isArray(list)) {
				const cards = list.slice(0, 60).map((c) => ({
					title: String(c.title || c.name || "").trim(),
					subtitle: String(c.subtitle || "").trim(),
					doctype: String(c.doctype || "").trim(),
					name: String(c.name || "").trim(),
					fields: Array.isArray(c.fields)
						? c.fields.slice(0, 12).map((f) => ({ label: String(f.label || ""), value: String(f.value != null ? f.value : "") }))
						: [],
				})).filter((c) => c.title || c.fields.length)
				if (cards.length) res = { title: String((a && a.title) || ""), cards }
			}
		} catch (e) {
			res = null
		}
	}
	_cardsCache.set(content, res)
	return res
}
const _macroCardCache = new Map()
function macroCardOf(m) {
	const content = (m && m.content) || ""
	if (!content.includes("jarvis-macro")) return null
	if (_macroCardCache.has(content)) return _macroCardCache.get(content)
	let res = null
	const mt = content.match(_MACRO_RE)
	if (mt) {
		try {
			const a = JSON.parse(mt[1].trim())
			const rawSteps = Array.isArray(a) ? a : (a && a.steps)
			if (Array.isArray(rawSteps)) {
				const steps = rawSteps
					.slice(0, 40)
					.map((s) => ({ label: String((s && s.label) || "").trim(), prompt: String((s && (s.prompt != null ? s.prompt : s)) || "").trim() }))
					.filter((s) => s.prompt)
				if (steps.length) {
					res = {
						name: String((a && (a.name || a.macro_name)) || "").trim(),
						description: String((a && a.description) || "").trim(),
						steps,
					}
				}
			}
		} catch (e) {
			res = null
		}
	}
	_macroCardCache.set(content, res)
	return res
}
const _chartsCache = new Map()
function chartsOf(m) {
	const content = (m && m.content) || ""
	if (!content.includes("jarvis-chart") && !content.includes("xychart-beta")) return []
	if (_chartsCache.has(content)) return _chartsCache.get(content)
	const specs = []
	for (const mt of content.matchAll(_CHART_RE)) {
		try {
			const s = JSON.parse(mt[1].trim())
			if (s && typeof s === "object" && _CHART_TYPES.has(s.type) && Array.isArray(s.series)) {
				specs.push(s)
			}
		} catch (e) {
			/* incomplete mid-stream JSON: skip until the closing fence arrives */
		}
	}
	for (const mt of content.matchAll(_XYCHART_RE)) {
		const s = parseXychart(mt[1])
		if (s) specs.push(s)
	}
	_chartsCache.set(content, specs)
	return specs
}

function askOf(m) {
	const mt = ((m && m.content) || "").match(_ASK_RE)
	if (!mt) return null
	try {
		const a = JSON.parse(mt[1].trim())
		const raw = Array.isArray(a) ? a : a && a.questions
		if (!Array.isArray(raw)) return null
		const FIELD = ["date", "datetime", "link", "text"]
		const questions = raw.slice(0, 6).map((q) => {
			let type = q.type === "boolean" ? "yesno" : q.type
			if (!["single", "multi", "yesno", ...FIELD].includes(type)) type = "single"
			return {
				q: String(q.q || q.question || "").trim(),
				type,
				// yesno may carry exactly 2 custom labels (e.g. ["Approve","Reject"]).
				options: Array.isArray(q.options) ? q.options.map(String).slice(0, 8) : [],
				doctype: type === "link" ? String(q.doctype || q.link || "").trim() : "",
			}
		}).filter((q) => {
			if (!q.q) return false
			if (q.type === "yesno" || FIELD.includes(q.type)) return true
			return q.options.length > 0
		})
		return questions.length ? { questions } : null
	} catch (e) {
		return null
	}
}
function actionOf(m) {
	const mt = ((m && m.content) || "").match(_ACTION_RE)
	if (!mt) return null
	try {
		const a = JSON.parse(mt[1].trim())
		return a && typeof a === "object" ? a : null
	} catch (e) {
		return null
	}
}
function confirmLabel(m) {
	const mt = ((m && m.content) || "").match(_CONFIRM_RE)
	return mt ? mt[1].trim() : ""
}
function render(text) {
	return linkifyDocs(renderMarkdown(stripBlocks(text)))
}
// {document name → DocType} harvested from THIS conversation's tool calls
// (get_doc / create_doc / get_list / update_doc / …). We only ever linkify IDs
// that actually came back from a tool, so we always know the DocType for the
// Desk URL and never false-positive on arbitrary prose.
const docRefs = computed(() => {
	const map = {}
	const add = (dt, name) => {
		if (dt && typeof name === "string" && name.length >= 4) map[name] = dt
	}
	for (const m of messages.value) {
		if (m.role !== "tool") continue
		let args = {}
		let res = {}
		try { args = m.tool_args ? JSON.parse(m.tool_args) : {} } catch (e) {}
		try { res = m.tool_result ? JSON.parse(m.tool_result) : {} } catch (e) {}
		const dt = args.doctype
		if (args.name) add(dt, args.name)
		const data = res && res.data
		if (Array.isArray(data)) {
			for (const row of data) if (row && row.name) add(row.doctype || dt, row.name)
		} else if (data && typeof data === "object") {
			add(data.doctype || dt, data.name)
		}
	}
	return map
})
const _escapeRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
// Compiled once per docRefs change: matches any known doc name as a whole token
// (not a substring of a longer id/word). Capped so a huge get_list can't build a
// pathological alternation.
const docNameRegex = computed(() => {
	const names = Object.keys(docRefs.value).sort((a, b) => b.length - a.length).slice(0, 400)
	if (!names.length) return null
	try {
		return new RegExp(`(?<![\\w-])(${names.map(_escapeRegex).join("|")})(?![\\w-])`, "g")
	} catch (e) {
		return null // e.g. a browser without lookbehind — degrade to no links
	}
})
const _deskSlug = (dt) => dt.toLowerCase().replace(/ /g, "-")
// Turn known document IDs in the rendered markdown HTML into Desk links, without
// touching text already inside an <a> (so markdown links stay intact).
function linkifyDocs(html) {
	const re = docNameRegex.value
	const refs = docRefs.value
	if (!re || !html) return html
	let inAnchor = 0
	return html.replace(/(<a\b[^>]*>)|(<\/a>)|(<[^>]+>)|([^<]+)/gi, (m, aOpen, aClose, otherTag, text) => {
		if (aOpen) { inAnchor++; return aOpen }
		if (aClose) { inAnchor = Math.max(0, inAnchor - 1); return aClose }
		if (otherTag != null) return otherTag
		if (inAnchor) return text
		return text.replace(re, (name) => {
			const dt = refs[name]
			if (!dt) return name
			const url = `/app/${_deskSlug(dt)}/${encodeURIComponent(name)}`
			return `<a href="${url}" target="_blank" rel="noopener" class="jv-doclink" title="Open ${dt} in ERPNext">${name}</a>`
		})
	})
}
// The last assistant message (finished, turn idle) decides which card is live —
// once the user clicks, a new message lands and the card retires automatically.
const _lastAssistant = computed(() => {
	if (busy.value) return null
	// visibleMessages excludes tool rows; the assistant reply has a LOWER seq than
	// the tool calls it spawned, so the raw messages array ends on a tool message.
	const vm = visibleMessages.value
	const last = vm[vm.length - 1]
	return last && last.role === "assistant" && !last.streaming ? last : null
})
const activeAction = computed(() => (_lastAssistant.value ? actionOf(_lastAssistant.value) : null))
const actionFor = computed(() => (activeAction.value ? _lastAssistant.value.name : null))
const confirmFor = computed(() =>
	_lastAssistant.value && !activeAction.value && confirmLabel(_lastAssistant.value)
		? _lastAssistant.value.name
		: null,
)
function actionSend(text) {
	send(text)
}
function answerConfirm(ok) {
	send(ok ? "Yes, go ahead." : "No, cancel that.")
}

// --- Field-control helpers shared by the confirm card and the record draft
// panel (chip → side panel; see _formMeta / openDraftPanel below).
function _isLongVal(v) {
	const s = String(v == null ? "" : v)
	return s.length > 55 || s.includes("\n")
}
// Map a Frappe fieldtype → the edit control to render + its options payload.
function _controlFor(fieldtype, options) {
	switch (fieldtype) {
		case "Link":
			return ["link", options || ""] // options = target doctype (searchLink)
		case "Select":
			return ["select", String(options || "").split("\n").map((o) => o.trim())]
		case "Check":
			return ["check", ""]
		case "Date":
			return ["date", ""]
		case "Datetime":
			return ["datetime", ""]
		case "Time":
			return ["time", ""]
		case "Int":
		case "Float":
		case "Currency":
		case "Percent":
		case "Rating":
			return ["number", ""]
		case "Small Text":
		case "Text":
		case "Long Text":
		case "Code":
		case "Text Editor":
		case "HTML Editor":
		case "Markdown Editor":
		case "JSON":
			return ["text", ""]
		default:
			return ["data", ""]
	}
}
// "Item Group" / "item_group" / "itemGroup" all → "itemgroup": the agent's
// action JSON labels fields sometimes by display label, sometimes by fieldname.
function _normKey(s) {
	return String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "")
}
// Resolve one card label to a field: exact normalized match on label/fieldname,
// else unique containment (e.g. "UOM" → stock_uom when it's the only sensible
// hit; required fields win ambiguous shorthands).
function _actField(meta, label) {
	const k = _normKey(label)
	if (!k) return null
	if (meta.map[k]) return meta.map[k]
	const hits = meta.fields.filter((f) => f._kl.includes(k) || f._kf.includes(k))
	if (hits.length === 1) return hits[0]
	if (hits.length > 1) {
		const reqd = hits.filter((f) => f.reqd)
		if (reqd.length === 1) return reqd[0]
	}
	return null
}
function _checkToYesNo(v) {
	const s = typeof v === "string" ? v.toLowerCase() : v
	return ["1", 1, "yes", "true", true, "on"].includes(s) ? "Yes" : "No"
}
// --- Record draft panel: the action JSON is the draft; edits are local; apply
// posts to actions_api (no LLM round-trip). ---
const draftPanel = ref(null)
// one shared link-search menu for panel inputs, keyed "f:<fieldname>" or "t:<ti>:<ri>:<col>"
const draftLink = ref({ key: "", items: [], open: false, up: false })
const _formMetaCache = {}

async function _formMeta(doctype) {
	if (_formMetaCache[doctype]) return _formMetaCache[doctype]
	const r = await api.getDoctypeFormMeta(doctype)
	if (!r || !r.ok) throw new Error("no form meta")
	for (const f of r.fields) { f._kl = _normKey(f.label); f._kf = _normKey(f.fieldname) }
	_formMetaCache[doctype] = r
	return r
}

function _panelField(metaField, value) {
	let [control, options] = _controlFor(metaField.fieldtype, metaField.options)
	let v = value == null ? "" : String(value)
	let orig = v
	if (control === "check") { v = _checkToYesNo(v); orig = v }
	if (control === "select" && Array.isArray(options) && v && !options.includes(v)) options = [v, ...options]
	return {
		fieldname: metaField.fieldname, label: metaField.label, control, options,
		fieldtype: metaField.fieldtype, reqd: metaField.reqd, read_only: metaField.read_only,
		value: v, orig,
	}
}

// Build the panel model from an action + form meta (+ live doc for updates).
async function openDraftPanel(a) {
	if (!a || a.kind !== "doc" || !a.doctype) return
	const verb = a.verb === "update" ? "update" : "create"
	let meta
	try { meta = await _formMeta(a.doctype) } catch (e) { return } // no meta → no panel (old card still shows)
	let base = { values: {}, tables: {} }
	if (verb === "update" && a.name) {
		try { base = await api.loadDocForEdit(a.doctype, a.name) } catch (e) { /* not editable → create-style view */ }
	}
	// proposed main fields: agent's fields resolved by label-or-fieldname
	const metaLookup = { fields: meta.fields, map: {} }
	for (const f of meta.fields) { if (f._kf && !metaLookup.map[f._kf]) metaLookup.map[f._kf] = f; if (f._kl) metaLookup.map[f._kl] = f }
	const proposed = {} // fieldname -> value
	for (const f of a.fields || []) {
		const m = _actField(metaLookup, f.label)
		if (m && m.fieldtype !== "Table") proposed[m.fieldname] = f.value
	}
	const fields = []
	const seen = new Set()
	for (const f of meta.fields) {
		if (f.fieldtype === "Table") continue
		const has = f.fieldname in proposed
		const baseV = base.values[f.fieldname]
		// Show: agent-proposed fields + required fields + (update) filled fields the agent referenced
		if (!has && !f.reqd) continue
		const pf = _panelField(f, has ? proposed[f.fieldname] : baseV)
		if (verb === "update") pf.orig = baseV == null ? "" : String(pf.control === "check" ? _checkToYesNo(baseV) : baseV)
		pf.changed = verb === "update" && String(pf.value) !== String(pf.orig)
		fields.push(pf); seen.add(f.fieldname)
	}
	// child tables: every meta table that is required, agent-proposed, or (update) non-empty
	const tables = []
	const aTables = {}
	for (const t of a.tables || []) if (t && t.fieldname) aTables[t.fieldname] = t.rows || []
	for (const [tf, spec] of Object.entries(meta.tables || {})) {
		const metaField = meta.fields.find((f) => f.fieldname === tf) || { reqd: 0 }
		const proposedRows = aTables[tf]
		const baseRows = (base.tables || {})[tf] || []
		if (!proposedRows && !metaField.reqd && !baseRows.length) continue
		// columns = child meta columns ∪ keys the agent used (unknown keys → data input)
		const columns = spec.columns.slice()
		const known = new Set(columns.map((c) => c.fieldname))
		for (const r of proposedRows || []) {
			for (const k of Object.keys(r)) {
				if (!known.has(k)) { known.add(k); columns.push({ fieldname: k, label: k, fieldtype: "Data", options: "", reqd: 0, read_only: 0 }) }
			}
		}
		const srcRows = proposedRows != null ? proposedRows : baseRows // proposal REPLACES loaded rows
		const rows = srcRows.map((r) => { const o = {}; for (const c of columns) o[c.fieldname] = r[c.fieldname] == null ? "" : String(r[c.fieldname]); return o })
		if (!rows.length) rows.push(_blankRow(columns))
		tables.push({
			fieldname: tf, label: spec.label, child: spec.child_doctype, columns, rows,
			origJson: JSON.stringify(verb === "update" ? baseRows : null),
		})
	}
	draftPanel.value = {
		verb, doctype: a.doctype, docName: verb === "update" ? (a.name || "") : "",
		title: a.title || "", submittable: !!meta.is_submittable,
		fields, tables, applying: false, error: "", updatedToast: false,
	}
}

function _blankRow(columns) {
	const o = {}
	for (const c of columns) o[c.fieldname] = ""
	return o
}
function addDraftRow(ti) {
	const t = draftPanel.value.tables[ti]
	t.rows.push(_blankRow(t.columns))
}
function removeDraftRow(ti, ri) {
	draftPanel.value.tables[ti].rows.splice(ri, 1)
}
function closeDraftPanel() {
	draftPanel.value = null
	draftLink.value = { key: "", items: [], open: false, up: false }
}

// Link search shared by panel fields + grid cells.
async function onDraftLink(key, target, doctype, ev) {
	let up = false
	const el = ev && ev.target
	if (el && el.getBoundingClientRect) up = el.getBoundingClientRect().bottom > window.innerHeight - 260
	draftLink.value = { key, items: [], open: true, up }
	if (!doctype) return
	try {
		const r = await api.searchLink(doctype, target())
		if (draftLink.value.key !== key) return // user moved on
		draftLink.value = { key, items: (r || []).map((x) => ({ value: x.value, label: x.description || "" })).slice(0, 8), open: true, up }
	} catch (e) { /* menu stays empty */ }
}
function pickDraftLink(setter, item) {
	setter(item.value)
	draftLink.value = { key: "", items: [], open: false, up: false }
}
function closeDraftLink() {
	setTimeout(() => { draftLink.value = { ...draftLink.value, open: false } }, 160)
}

// est. totals: any grid with qty (+rate) columns
const draftTotals = computed(() => {
	const p = draftPanel.value
	if (!p) return ""
	let qty = 0, amt = 0, hasQty = false, hasAmt = false
	for (const t of p.tables) {
		const q = t.columns.find((c) => c.fieldname === "qty")
		const r = t.columns.find((c) => c.fieldname === "rate")
		if (!q) continue
		hasQty = true
		for (const row of t.rows) {
			const n = parseFloat(row.qty) || 0
			qty += n
			if (r) { hasAmt = true; amt += n * (parseFloat(row.rate) || 0) }
		}
	}
	if (!hasQty) return ""
	return `Total qty ${qty}` + (hasAmt ? ` · Est. total ${amt.toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : "")
})
const draftCta = computed(() => {
	const p = draftPanel.value
	if (!p) return ""
	return p.verb === "update" ? `Update ${p.docName || p.doctype}` : `Create ${p.doctype}`
})
const draftChipSummary = computed(() => {
	const a = activeAction.value
	if (!a) return ""
	const n = (a.tables || []).reduce((s, t) => s + ((t.rows || []).length), 0)
	return n ? `${n} row${n === 1 ? "" : "s"}` : ""
})

// Auto-open on a fresh create/update action (also fires when loading an old
// conversation that ends on a pending draft — that draft IS still pending).
watch(actionFor, () => {
	confirmError.value = ""
	const a = activeAction.value
	if (a && a.kind === "doc" && (a.verb === "create" || a.verb === "update" || !a.verb)) {
		const wasOpen = !!draftPanel.value
		openDraftPanel({ verb: a.verb || "create", ...a }).then(() => {
			if (wasOpen && draftPanel.value) draftPanel.value.updatedToast = true
		})
	}
})

// --- apply wiring: draft panel + confirm card round-trip via apply_action ---
const confirmBusy = ref(false)
const confirmError = ref("")

function _coerceOut(f) {
	if (f.control === "check") return f.value === "Yes" ? 1 : 0
	if (f.control === "number") return f.value === "" ? "" : Number(f.value)
	return f.value
}
function _coerceRow(t, r) {
	const out = {}
	for (const c of t.columns) {
		if (c.read_only) continue
		let v = r[c.fieldname]
		if (v === "" || v == null) continue
		if (["Int", "Float", "Currency", "Percent"].includes(c.fieldtype)) v = Number(v)
		if (c.fieldtype === "Check") v = Number(v) ? 1 : 0
		out[c.fieldname] = v
	}
	return out
}

async function applyDraft(submitFlag) {
	const p = draftPanel.value
	if (!p || p.applying) return
	const values = {}
	for (const f of p.fields) {
		if (f.read_only) continue
		const changed = String(f.value) !== String(f.orig)
		if (p.verb === "create" ? String(f.value).trim() !== "" : changed) values[f.fieldname] = _coerceOut(f)
	}
	for (const t of p.tables) {
		const rows = t.rows.map((r) => _coerceRow(t, r)).filter((r) => Object.keys(r).length)
		if (p.verb === "create") { if (rows.length) values[t.fieldname] = rows }
		else if (JSON.stringify(rows) !== JSON.stringify((JSON.parse(t.origJson) || []).map((r) => _coerceRow(t, Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v == null ? "" : String(v)])))))) {
			values[t.fieldname] = rows
		}
	}
	p.applying = true; p.error = ""
	try {
		await api.applyAction({
			verb: p.verb, doctype: p.doctype, name: p.docName || "",
			values, submit: submitFlag ? 1 : 0, conversation: currentId.value || "",
		})
		closeDraftPanel()
		await loadConversation(currentId.value)
		loadConversations()
	} catch (e) {
		p.applying = false
		p.error = (e && e.messages && e.messages[0]) || (e && e.message) || "Could not save — check the values."
	}
}

function discardDraft() {
	closeDraftPanel()
	send("No, cancel that.")
}

// submit/cancel/delete/amend confirm card → direct apply (no LLM turn).
// Old-format cards without `name` fall back to the conversational path.
async function confirmApply() {
	const a = activeAction.value
	if (!a) return
	if (!a.name) { actionSend("Yes, go ahead."); return }
	confirmBusy.value = true; confirmError.value = ""
	try {
		await api.applyAction({ verb: a.verb, doctype: a.doctype, name: a.name, conversation: currentId.value || "" })
		await loadConversation(currentId.value)
		loadConversations()
	} catch (e) {
		confirmError.value = (e && e.messages && e.messages[0]) || (e && e.message) || "Could not apply."
	} finally {
		confirmBusy.value = false
	}
}

// --- interactive clarifying questions (card on the last assistant message) ---
const activeAsk = computed(() =>
	_lastAssistant.value && !activeAction.value ? askOf(_lastAssistant.value) : null,
)
const askFor = computed(() => (activeAsk.value ? _lastAssistant.value.name : null))
const askSel = ref({}) // qIdx -> string (single/yesno/date/datetime/text/link) | string[] (multi)
const askOther = ref({}) // qIdx -> free-text (option types only)
const askLink = ref({}) // qIdx -> { q, items, open } for link-type record search
const _FIELD_TYPES = ["date", "datetime", "link", "text"]
// Reset the draft whenever a new question set appears (new message asks).
watch(askFor, () => {
	askSel.value = {}
	askOther.value = {}
	askLink.value = {}
})
async function onLinkSearch(i, doctype, val) {
	askLink.value = { ...askLink.value, [i]: { ...(askLink.value[i] || {}), q: val, open: true } }
	if (!doctype) return
	try {
		const r = await api.searchLink(doctype, val)
		const items = (r || []).map((x) => ({ value: x.value, label: x.description || "" })).slice(0, 8)
		askLink.value = { ...askLink.value, [i]: { q: val, items, open: true } }
	} catch (e) {
		askLink.value = { ...askLink.value, [i]: { q: val, items: [], open: true } }
	}
}
function pickLink(i, item) {
	askSel.value = { ...askSel.value, [i]: item.value }
	askLink.value = { ...askLink.value, [i]: { q: item.value, items: [], open: false } }
}
function pickSingle(i, opt) {
	askSel.value = { ...askSel.value, [i]: opt }
}
function toggleMulti(i, opt) {
	const cur = Array.isArray(askSel.value[i]) ? askSel.value[i].slice() : []
	const ix = cur.indexOf(opt)
	if (ix >= 0) cur.splice(ix, 1)
	else cur.push(opt)
	askSel.value = { ...askSel.value, [i]: cur }
}
function isPicked(i, opt) {
	const v = askSel.value[i]
	return Array.isArray(v) ? v.includes(opt) : v === opt
}
const askReady = computed(() => {
	const spec = activeAsk.value
	if (!spec) return false
	return spec.questions.every((q, i) => {
		const v = askSel.value[i]
		if (_FIELD_TYPES.includes(q.type)) return v != null && String(v).trim() !== ""
		const other = (askOther.value[i] || "").trim()
		if (q.type === "multi") return (Array.isArray(v) && v.length > 0) || !!other
		return (v != null && v !== "") || !!other
	})
})
function submitAsk() {
	const spec = activeAsk.value
	if (!spec || !askReady.value) return
	const lines = spec.questions.map((q, i) => {
		const ans = []
		const v = askSel.value[i]
		if (Array.isArray(v)) ans.push(...v)
		else if (v != null && v !== "") ans.push(v)
		const other = (askOther.value[i] || "").trim()
		if (other) ans.push(other)
		return `${i + 1}. ${q.q} → ${ans.join(", ") || "(no answer)"}`
	})
	askSel.value = {}
	askOther.value = {}
	send("Here are my answers:\n" + lines.join("\n"))
}
function copyText(t) {
	const s = t || ""
	// navigator.clipboard only exists in a secure context (https / localhost).
	// Over plain http (e.g. jarvis-test.localhost) it's undefined, so the old
	// `navigator.clipboard?.writeText` silently did nothing — that's why Copy
	// "didn't work". Fall back to the legacy execCommand path in that case.
	try {
		if (navigator.clipboard && window.isSecureContext) {
			navigator.clipboard.writeText(s).catch(() => fallbackCopy(s))
			return
		}
	} catch (e) {
		/* fall through to legacy copy */
	}
	fallbackCopy(s)
}
function fallbackCopy(s) {
	try {
		const ta = document.createElement("textarea")
		ta.value = s
		ta.setAttribute("readonly", "")
		ta.style.position = "fixed"
		ta.style.top = "-9999px"
		document.body.appendChild(ta)
		ta.select()
		ta.setSelectionRange(0, s.length)
		document.execCommand("copy")
		document.body.removeChild(ta)
	} catch (e) {
		/* clipboard truly unavailable */
	}
}
// Per-message Copy with a brief "copied" tick, and Edit (load a previous
// command back into the composer to tweak and resend).
const copiedId = ref("")
let _copyTimer = null
function copyMsg(id, text) {
	copyText(text)
	copiedId.value = id
	clearTimeout(_copyTimer)
	_copyTimer = setTimeout(() => { copiedId.value = "" }, 1300)
}
function editCommand(m) {
	input.value = m.content || ""
	nextTick(() => {
		autoGrow()
		const el = inputEl.value
		if (el) {
			el.focus()
			const p = input.value.length
			el.setSelectionRange(p, p)
		}
	})
}
const _VERB = { create: "Create", update: "Update", submit: "Submit", cancel: "Cancel", delete: "Delete", amend: "Amend" }
function actionVerb(a) {
	return _VERB[a && a.verb] || "Review"
}
function actionCta(a) {
	const v = a && a.verb
	if (v === "delete") return "Confirm & delete"
	if (v === "submit") return "Confirm & submit"
	if (v === "cancel") return "Confirm & cancel"
	if (v === "update" || v === "amend") return "Confirm & save"
	return "Confirm & create"
}
// Cached render payload for an artifact: HTML srcdoc (html/svg) or a base64
// data-url (pdf/image/file). Keyed by `${msgName}::${canvasName}::${theme}` —
// the theme is in the key because the backend themes the srcdoc shell (dark
// preview bg), so a toggle refetches instead of showing the stale scheme.
function cvOf(m, cv) {
	return canvasContent.value[m.name + "::" + cv.name + "::" + (effectiveDark.value ? 1 : 0)]
}
// What to feed the renderer. html/svg need the fetched srcdoc content (sandboxed
// iframe). pdf / image / file render straight from the on-site file_url instead:
// Chrome won't render a base64 data: PDF inline, and a real same-origin URL also
// avoids holding big files as base64 in memory. Every canvas item carries
// file_url (private File on this site, auth-gated by the session cookie).
function cvSrc(m, cv) {
	if (cv.type === "html" || cv.type === "svg") return cvOf(m, cv)
	return cv.file_url || cvOf(m, cv)
}
// Basename (with extension) for a download filename / file card label.
function cvFile(cv) {
	return (cv.name || "file").split("/").pop()
}
// ---- artifact preview side panel (ChatGPT/Claude-style: click a card → slide-
// in panel on the right; PDF/image render directly, xlsx/csv as a table) ----
const artifact = ref(null) // { m, cv, url, kind, content?, sheets?, sheetIdx?, text? }
const artifactPanelEl = ref(null)
// Move focus into the panel when it opens so keyboard users land inside it
// and Escape closes it right away (handled in onGlobalKey).
watch(() => !!artifact.value, (open) => {
	if (open) nextTick(() => artifactPanelEl.value && artifactPanelEl.value.focus())
})
const curSheet = computed(() => {
	const a = artifact.value
	if (!a || a.kind !== "table" || !a.sheets?.length) return { rows: [] }
	return a.sheets[a.sheetIdx] || { rows: [] }
})
function closeArtifact() {
	artifact.value = null
}
function setSheet(si) {
	if (artifact.value) artifact.value = { ...artifact.value, sheetIdx: si }
}
async function openArtifact(m, cv) {
	const url = cv.file_url || cvOf(m, cv)
	const t = cv.type
	if (t === "pdf" || t === "image") {
		artifact.value = { m, cv, url, kind: t }
		return
	}
	if (t === "html" || t === "svg") {
		let content = cvOf(m, cv)
		if (!content) {
			artifact.value = { m, cv, url, kind: "loading" }
			await ensureCanvas(m)
			content = cvOf(m, cv)
		}
		artifact.value = { m, cv, url, kind: content ? t : "nopreview", content }
		return
	}
	// "file" (xlsx / csv / txt / …) → ask the backend for a tabular/text preview.
	artifact.value = { m, cv, url, kind: "loading" }
	try {
		const r = await api.previewFile(cv.file_url)
		if (r && r.kind === "table" && Array.isArray(r.sheets) && r.sheets.length) {
			artifact.value = { m, cv, url, kind: "table", sheets: r.sheets, sheetIdx: 0 }
			return
		}
		if (r && r.kind === "text") {
			artifact.value = { m, cv, url, kind: "text", text: r.text || "" }
			return
		}
	} catch (e) {
		/* fall through to download-only */
	}
	artifact.value = { m, cv, url, kind: "nopreview" }
}
// Lazily fetch each artifact's render payload (srcdoc content for html/svg, a
// data-url for pdf/image/file) and cache it.
async function ensureCanvas(m) {
	if (!m || !Array.isArray(m.canvas) || !m.canvas.length) return
	for (const cv of m.canvas) {
		// pdf / image / file render from file_url directly — only html/svg need
		// the fetched srcdoc content.
		if (cv.file_url && cv.type !== "html" && cv.type !== "svg") continue
		const dark = effectiveDark.value ? 1 : 0
		const key = m.name + "::" + cv.name + "::" + dark
		if (canvasContent.value[key]) continue
		try {
			const r = await api.getCanvas(m.name, cv.name, dark)
			const payload = r && (r.content || r.data_url)
			if (payload) canvasContent.value = { ...canvasContent.value, [key]: payload }
		} catch (e) {
			/* leave it in the loading state; a reload retries */
		}
	}
	nextTick(scrollBottom)
}
function scrollBottom(smooth = false) {
	const el = threadEl.value
	if (!el) return
	if (smooth && "scrollTo" in el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" })
	else el.scrollTop = el.scrollHeight
}
// Distance in px from the very bottom of the thread. 0 == pinned to newest.
function distanceFromBottom() {
	const el = threadEl.value
	if (!el) return 0
	return el.scrollHeight - el.scrollTop - el.clientHeight
}
// Runs on every user scroll: decide whether we're "at the bottom" (keep pinning
// as new content arrives) and whether to reveal the jump-to-latest arrow.
function onThreadScroll() {
	const d = distanceFromBottom()
	pinnedToBottom.value = d <= 80
	showScrollDown.value = d > 140
}
// Arrow click: smooth-scroll to the newest message and re-pin.
function jumpToBottom() {
	pinnedToBottom.value = true
	showScrollDown.value = false
	scrollBottom(true)
}
// Keep the thread pinned to the newest message while its content is still
// settling — streaming text, plus images/charts/mermaid that finish loading
// *after* the initial scrollBottom() and would otherwise leave a freshly
// refreshed chat parked mid-thread (the "10 messages, opens at the top" bug).
// A ResizeObserver on the inner content re-pins on every growth, but only while
// the user hasn't deliberately scrolled up.
let threadRO = null
watch(threadInnerEl, (el) => {
	if (threadRO) {
		threadRO.disconnect()
		threadRO = null
	}
	if (el && typeof ResizeObserver !== "undefined") {
		threadRO = new ResizeObserver(() => {
			if (pinnedToBottom.value) scrollBottom()
			else onThreadScroll()
		})
		threadRO.observe(el)
	}
})
onBeforeUnmount(() => {
	if (threadRO) {
		threadRO.disconnect()
		threadRO = null
	}
})
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
	// Up/Down: recall sent prompts — only when the caret is at the very start
	// (Up) or end (Down) so it doesn't fight normal multi-line editing.
	const el = e.target
	if (e.key === "ArrowUp" && (input.value === "" || el.selectionStart === 0) && promptHistory.value.length) {
		e.preventDefault()
		if (histIdx.value === null) {
			histDraft.value = input.value
			histIdx.value = promptHistory.value.length
		}
		if (histIdx.value > 0) {
			histIdx.value -= 1
			input.value = promptHistory.value[histIdx.value]
			nextTick(() => {
				autoGrow()
				const p = input.value.length
				el.setSelectionRange(p, p)
			})
		}
		return
	}
	if (e.key === "ArrowDown" && histIdx.value !== null && el.selectionStart === input.value.length) {
		e.preventDefault()
		if (histIdx.value < promptHistory.value.length - 1) {
			histIdx.value += 1
			input.value = promptHistory.value[histIdx.value]
		} else {
			histIdx.value = null
			input.value = histDraft.value
		}
		nextTick(() => {
			autoGrow()
			const p = input.value.length
			el.setSelectionRange(p, p)
		})
		return
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
		promptHistory.value = []
		histIdx.value = null
		histDraft.value = ""
		return
	}
	const d = await api.getConversation(id)
	// Stale-response guard: if the user navigated to a different conversation
	// while this request was in flight, drop the result. Without this, a slow
	// get_conversation response clobbers the conversation you actually switched
	// to with the wrong (or empty) messages — and only a page refresh, which
	// does a single clean load, would put it right. (Root cause of "open a
	// chat, switch away and back, it shows empty until I refresh".)
	if (currentId.value !== id) return
	messages.value = d?.messages || []
	modelOverride.value = d?.model_override || ""
	// Seed Up/Down recall from THIS conversation's past prompts. Without this,
	// promptHistory only held prompts typed in the current page session, so
	// after a reload or when opening an existing chat the arrows did nothing.
	// Strip the trailing "📎 name" attachment marker so recall yields the
	// actual typed text.
	promptHistory.value = (d?.messages || [])
		.filter((m) => m.role === "user" && m.content)
		.map((m) => m.content.replace(/\n*📎[^\n]*$/, "").trim())
		.filter(Boolean)
	histIdx.value = null
	histDraft.value = ""
	for (const m of messages.value) {
		if (Array.isArray(m.canvas) && m.canvas.length) ensureCanvas(m)
	}
	// Resume the in-progress indicator if the last reply is still streaming, so a
	// refreshed or duplicated tab shows "Thinking…"/streaming (realtime deltas go
	// to every tab) instead of a frozen blank reply. Freshness-guarded so a stale
	// streaming=1 (crashed worker) can't lock the composer forever; live deltas +
	// run:end clear it normally.
	const _streaming = [...messages.value].reverse().find((m) => m.role === "assistant" && m.streaming)
	if (_streaming) {
		const fresh = _streaming.modified && new Date() - new Date(_streaming.modified.replace(" ", "T")) < 5 * 60 * 1000
		if (fresh) {
			sending.value = true
			waiting.value = !((_streaming.content || "").trim())
		}
	}
	// A freshly opened/refreshed chat should land on the newest message and stay
	// pinned there while late content settles; the ResizeObserver takes over.
	pinnedToBottom.value = true
	showScrollDown.value = false
	await nextTick()
	scrollBottom()
	processMermaid()
}

// Render any ```mermaid blocks (the agent's inline pie/flow charts) into SVG.
// Lazy-loads mermaid so it never bloats the initial bundle; only runs on
// finalized messages (mid-stream mermaid source is incomplete and would error).
let _mermaid = null
// Vibrant, high-contrast categorical palette for pie/bar slices — distinct
// hues that stay legible with white section labels in both light and dark.
// (The app's own palette is near-monochrome, which is why the old "neutral"
// mermaid theme rendered charts as washed-out grays.)
const MERMAID_PALETTE = [
	"#6366f1", "#06b6d4", "#f59e0b", "#ec4899", "#10b981", "#8b5cf6",
	"#ef4444", "#14b8a6", "#f97316", "#3b82f6", "#65a30d", "#f43f5e",
]
// Guard against overlapping runs: mermaid's render mutates a shared temp DOM
// node, so two concurrent passes can clobber each other and leave a chart as
// raw source. _mmQueued re-runs once if a trigger fires mid-pass.
let _mmRunning = false
let _mmQueued = false
async function processMermaid() {
	if (_mmRunning) {
		_mmQueued = true
		return
	}
	_mmRunning = true
	try {
		await _renderMermaid()
	} finally {
		_mmRunning = false
		if (_mmQueued) {
			_mmQueued = false
			setTimeout(processMermaid, 0)
		}
	}
}
async function _renderMermaid() {
	const nodes = rootEl.value?.querySelectorAll?.(".jv-mermaid:not([data-rendered])")
	if (!nodes || !nodes.length) return
	try {
		if (!_mermaid) _mermaid = (await import("mermaid")).default
	} catch (e) {
		return
	}
	// Re-initialize each run so the palette tracks the active light/dark theme —
	// mermaid snapshots its theme at init, so a one-time init would freeze it.
	const dark = effectiveDark.value
	const pie = Object.fromEntries(MERMAID_PALETTE.map((c, i) => [`pie${i + 1}`, c]))
	_mermaid.initialize({
		startOnLoad: false,
		securityLevel: "strict",
		theme: "base",
		fontFamily: "inherit",
		themeVariables: {
			...pie,
			pieStrokeColor: dark ? "#16161a" : "#ffffff",
			pieStrokeWidth: "2px",
			pieOuterStrokeColor: dark ? "#16161a" : "#ffffff",
			pieOuterStrokeWidth: "2px",
			pieSectionTextColor: "#ffffff",
			pieSectionTextSize: "14px",
			pieTitleTextColor: dark ? "#ededf2" : "#171717",
			pieLegendTextColor: dark ? "#b6b6c0" : "#4a4a4f",
			// flow / sequence / line charts, if the agent emits those
			primaryColor: dark ? "#1d1d22" : "#f7f7f8",
			primaryBorderColor: dark ? "#3a3a45" : "#d6e2fb",
			primaryTextColor: dark ? "#ededf2" : "#171717",
			lineColor: dark ? "#5b7cfa" : "#3b82f6",
			textColor: dark ? "#b6b6c0" : "#4a4a4f", xyChart: { backgroundColor: dark ? "#16161a" : "#ffffff", titleColor: dark ? "#ededf2" : "#171717", xAxisLabelColor: dark ? "#b6b6c0" : "#4a4a4f", xAxisTitleColor: dark ? "#b6b6c0" : "#4a4a4f", xAxisTickColor: dark ? "#3a3a45" : "#d6e2fb", xAxisLineColor: dark ? "#3a3a45" : "#d6e2fb", yAxisLabelColor: dark ? "#b6b6c0" : "#4a4a4f", yAxisTitleColor: dark ? "#b6b6c0" : "#4a4a4f", yAxisTickColor: dark ? "#3a3a45" : "#d6e2fb", yAxisLineColor: dark ? "#3a3a45" : "#d6e2fb", plotColorPalette: MERMAID_PALETTE.join(",") },
		},
	})
	let n = 0
	for (const el of nodes) {
		const src = (el.textContent || "").trim()
		if (!src) {
			el.setAttribute("data-rendered", "1")
			continue
		}
		try {
			const { svg } = await _mermaid.render(`jvmmd-${n++}-${Math.floor(performance.now())}`, src)
			el.innerHTML = svg
			el.setAttribute("data-rendered", "1") // mark only AFTER a successful render
			_addChartDownload(el) // hover button to save the chart as PNG
		} catch (e) {
			// Retry transient failures on a later pass; give up (show source) after 3.
			const t = (parseInt(el.getAttribute("data-try") || "0", 10) || 0) + 1
			if (t >= 3) el.setAttribute("data-rendered", "err")
			else el.setAttribute("data-try", String(t))
		}
	}
	nextTick(scrollBottom)
}
// Drop a hover "download PNG" button onto a rendered chart. The chart is raw
// (markdown-rendered) HTML, not a Vue node, so we wire the button imperatively.
function _addChartDownload(el) {
	if (el.querySelector(".jv-chart-dl")) return
	const btn = document.createElement("button")
	btn.className = "jv-chart-dl"
	btn.type = "button"
	btn.title = "Download chart as PNG"
	btn.setAttribute("aria-label", "Download chart as PNG")
	btn.innerHTML =
		'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>'
	btn.addEventListener("click", () => downloadSvgAsPng(el.querySelector("svg")))
	el.appendChild(btn)
}
// Rasterize an inline SVG (the chart) to a 2x PNG and trigger a download. The
// SVG is same-origin inline markup with no external refs, so the canvas isn't
// tainted and toBlob works.
function downloadSvgAsPng(svgEl) {
	if (!svgEl) return
	const vb = svgEl.viewBox && svgEl.viewBox.baseVal
	const w = (vb && vb.width) || svgEl.clientWidth || 640
	const h = (vb && vb.height) || svgEl.clientHeight || 420
	const xml = new XMLSerializer().serializeToString(svgEl)
	const img = new Image()
	img.onload = () => {
		const scale = 2
		const canvas = document.createElement("canvas")
		canvas.width = Math.ceil(w * scale)
		canvas.height = Math.ceil(h * scale)
		const ctx = canvas.getContext("2d")
		ctx.fillStyle = effectiveDark.value ? "#16161a" : "#ffffff"
		ctx.fillRect(0, 0, canvas.width, canvas.height)
		ctx.setTransform(scale, 0, 0, scale, 0, 0)
		ctx.drawImage(img, 0, 0, w, h)
		canvas.toBlob((blob) => {
			if (!blob) return
			const url = URL.createObjectURL(blob)
			const a = document.createElement("a")
			a.href = url
			a.download = "chart.png"
			document.body.appendChild(a)
			a.click()
			a.remove()
			setTimeout(() => URL.revokeObjectURL(url), 1000)
		}, "image/png")
	}
	img.src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml)))
}
// Clear all per-turn UI state that belongs to the conversation we are leaving,
// so a chat that was mid-stream does not strand the composer when we open
// another: without this, sending stays true (composer stuck in "Stop" mode and
// send() bails on sending) because the leaving run's run:end event is dropped
// by the conversation guard in onEvent.
function resetRunState() {
	sending.value = false
	waiting.value = false
	activeTools.value = []
	currentRunId.value = null
	pendingFiles.value = []
	mention.value = { ...mention.value, open: false }
	histIdx.value = null
	histDraft.value = ""
}
// Stash the leaving chat's draft and restore the target chat's own, so unsent
// text follows its conversation instead of bleeding into the next one.
function swapDraft(toId) {
	if (currentId.value) drafts.value[currentId.value] = input.value
	input.value = (toId && drafts.value[toId]) || ""
}
async function selectConversation(id) {
	if (id === currentId.value) return
	swapDraft(id)
	resetRunState()
	// Don't let the macro banner leak across conversations — clear it unless we're
	// navigating into the run's own conversation.
	if (macroRun.value && macroRun.value.conversation !== id) macroRun.value = null
	currentId.value = id
	await loadConversation(id)
	await nextTick()
	autoGrow()
	inputEl.value?.focus()
}
async function newChat() {
	swapDraft(null)
	resetRunState()
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
	if (!e.target.closest(".jv-conv-menu") && !e.target.closest(".jv-conv-more")) convMenuFor.value = null
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
	if (text && promptHistory.value[promptHistory.value.length - 1] !== text) {
		promptHistory.value.push(text) // for Up/Down recall
	}
	histIdx.value = null
	histDraft.value = ""
	if (fromMain) {
		input.value = ""
		pendingFiles.value = []
		mention.value = { ...mention.value, open: false }
		nextTick(autoGrow)
	}
	// No awaited pre-flight for a brand-new chat (latency plan, Phase 1.3):
	// the backend's send_message creates/focuses the empty conversation
	// itself and returns conversation_id — two fewer round-trips before the
	// first message even leaves the browser. The sidebar refresh happens
	// after the send resolves, off the critical path.
	const isNewConv = !currentId.value
	sending.value = true
	waiting.value = true
	stoppedRunId.value = null
	const isImgAtt = (a) => /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(a.file_name || a.file_url || "")
	const imgAtts = attachments.filter(isImgAtt)
	const otherAtts = attachments.filter((a) => !isImgAtt(a))
	const marker = otherAtts.length ? "📎 " + otherAtts.map((a) => a.file_name).join(", ") : ""
	const optimistic = [text, marker].filter(Boolean).join("\n\n")
	const optCanvas = imgAtts.map((a, i) => ({ name: `tmpimg-${Date.now()}-${i}`, type: "image", file_url: a.file_url, title: a.file_name || "image" }))
	messages.value = [...messages.value, { name: `tmp-${Date.now()}`, role: "user", content: optimistic, canvas: optCanvas.length ? optCanvas : undefined }]
	await nextTick()
	scrollBottom()
	try {
		const r = await api.sendMessage(currentId.value || "", text, undefined, attachments)
		if (isNewConv && r?.conversation_id) {
			// Adopt the server-created conversation so realtime events route to
			// this thread, then refresh the sidebar without blocking anything.
			currentId.value = r.conversation_id
			loadConversations()
		}
	} catch (e) {
		sending.value = false
		waiting.value = false
	}
}

// Proactive (Jarvis-initiated) conversation toast.
const proactiveToast = ref(null)
function openProactive() {
	const t = proactiveToast.value
	if (!t) return
	swapDraft(t.id)
	resetRunState()
	currentId.value = t.id
	loadConversation(t.id)
	proactiveToast.value = null
}
function onEvent(p) {
	// Auto-generated title arrives async (worker titles the chat after the
	// first real turn). Handle it before the current-conversation guard so the
	// sidebar updates even if the user has since switched chats.
	if (p.kind === "conversation:renamed" && p.conversation_id) {
		const c = conversations.value.find((x) => x.name === p.conversation_id)
		if (c && p.title) c.title = p.title
		return
	}
	// Jarvis started a conversation with us (proactive). Refresh the sidebar and
	// surface a toast; handled before the current-conversation guard.
	if (p.kind === "conversation:new" && p.conversation_id) {
		loadConversations()
		proactiveToast.value = { id: p.conversation_id, title: p.title || "Message from Jarvis", preview: p.preview || "" }
		return
	}
	// Macro-run events use `conversation` (not conversation_id) and are handled
	// before the current-conversation guard so the banner tracks the run.
	if (p.kind === "macro:progress") {
		if (p.conversation === currentId.value) {
			if (_macroDoneTimer) { clearTimeout(_macroDoneTimer); _macroDoneTimer = null }
			macroRun.value = {
				run: p.macro_run,
				conversation: p.conversation,
				step: p.step || 0,
				total: p.total || (macroRun.value && macroRun.value.total) || 0,
				label: p.label || "",
				status: "running",
			}
		}
		patchMacroRunRow(p, false) // live-advance the open run-history dashboard
		return
	}
	if (p.kind === "macro:done") {
		if (p.conversation === currentId.value && macroRun.value) {
			macroRun.value = { ...macroRun.value, status: p.status || "completed" }
			if (_macroDoneTimer) clearTimeout(_macroDoneTimer)
			_macroDoneTimer = setTimeout(() => {
				if (macroRun.value && macroRun.value.conversation === p.conversation) macroRun.value = null
				_macroDoneTimer = null
			}, 4000)
		}
		patchMacroRunRow(p, true)
		return
	}
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
			// Re-render charts after the reload settles — late re-renders can swap a
			// freshly-rendered mermaid node back to raw source; these idle passes
			// (mutex-guarded, no-op when nothing's pending) catch that race.
			setTimeout(processMermaid, 300)
			setTimeout(processMermaid, 900)
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
// Shared upload path for the file picker, clipboard paste, and drag-and-drop.
async function uploadFiles(list) {
	const files = Array.from(list || [])
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
async function onFilesPicked(e) {
	const picked = Array.from(e.target.files || [])
	e.target.value = ""
	await uploadFiles(picked)
}
// Drag-and-drop a file/image onto the composer (Claude-style). dragDepth guards
// against the flicker from dragenter/leave firing on child elements.
const dragActive = ref(false)
let _dragDepth = 0
function onDragEnter() {
	_dragDepth++
	dragActive.value = true
}
function onDragLeave() {
	_dragDepth = Math.max(0, _dragDepth - 1)
	if (!_dragDepth) dragActive.value = false
}
async function onDrop(e) {
	_dragDepth = 0
	dragActive.value = false
	await uploadFiles((e.dataTransfer && e.dataTransfer.files) || [])
}
// Transient hint shown when the clipboard holds only a file PATH, not the image
// bytes (e.g. copying an image FILE from a file manager - the OS exposes only
// the path and browsers can't read the bytes from it).
const pasteHint = ref("")
let _pasteHintTimer = null
function flashPasteHint() {
	pasteHint.value = "That copied the file's path, not the image. Use the 📎 button, or copy the image itself (e.g. a screenshot) and paste again."
	if (_pasteHintTimer) clearTimeout(_pasteHintTimer)
	_pasteHintTimer = setTimeout(() => { pasteHint.value = "" }, 6000)
}
// Paste an image straight from the clipboard (screenshot / copied image) →
// upload it as an attachment, the same path as the file picker. Plain-text
// pastes are left untouched (we only preventDefault when an image is present).
async function onPaste(e) {
	const cd = e.clipboardData
	if (!cd) return
	const imgs = []
	// Some browsers populate .files for a copied file; screenshots / "Copy image"
	// land in .items. Check both, .files first.
	for (const f of cd.files || []) {
		if ((f.type || "").startsWith("image/")) imgs.push(f)
	}
	if (!imgs.length) {
		for (const it of cd.items || []) {
			if (it.kind === "file" && (it.type || "").startsWith("image/")) {
				const f = it.getAsFile()
				if (f) imgs.push(f)
			}
		}
	}
	if (!imgs.length) {
		// No image bytes. If the clipboard is just a local image-file PATH/URI
		// (file-manager copy), don't dump the raw path into the box - hint the
		// user to the right method instead. Otherwise let normal text paste run.
		const text = (cd.getData && (cd.getData("text/uri-list") || cd.getData("text/plain"))) || ""
		if (/^\s*(file:\/\/|\/|[a-z]:\\).*\.(png|jpe?g|gif|webp|bmp|svg)\s*$/i.test(text)) {
			e.preventDefault()
			flashPasteHint()
		}
		return
	}
	e.preventDefault()
	uploading.value = true
	for (let i = 0; i < imgs.length; i++) {
		const f = imgs[i]
		const ext = (((f.type || "image/png").split("/")[1]) || "png").split("+")[0]
		// Clipboard images come in unnamed (or all "image.png"); give each a
		// unique, descriptive name so the upload + dedup behave.
		const named = new File([f], `pasted-${Date.now()}-${i}.${ext}`, { type: f.type || "image/png" })
		try {
			pendingFiles.value = [...pendingFiles.value, await api.uploadFile(named)]
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
function isImageFile(f) {
	return /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test((f && (f.file_name || f.file_url)) || "")
}

// ---- mentions (@ user, / doctype·tool) ----
let _mentionSeq = 0
function onInput() {
	histIdx.value = null // typing exits prompt-history navigation
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
			const q = query.toLowerCase()
			// Customer's own skills first (the "/" command, Claude-style).
			const skills = customSkills.value
				.filter((s) => s.enabled && (s.skill_name || "").includes(q))
				.map((s) => ({ value: s.skill_name, sub: "skill" }))
			const tools = jarvisTools.value.filter((t) => t.includes(q)).map((t) => ({ value: t, sub: "tool" }))
			const r = await api.searchLink("DocType", query)
			const dts = (r || []).map((x) => ({ value: x.value, sub: "doctype" }))
			items = [...skills, ...tools, ...dts].slice(0, 8)
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
	// Latency plan, Phase 1.3: the bootstrap network calls used to run as a
	// serial awaited chain (ready → ui settings → conversations), each a full
	// round-trip. Fire them concurrently and await in order below — the
	// onboarding redirect check still resolves before anything is revealed,
	// and list_conversations (which triggers the server-side prefix prewarm)
	// now starts ~2 RTTs earlier.
	const readyP = api.isReadyForChat().catch(() => null)
	const uiP = api.getChatUiSettings().catch(() => null)
	const convsP = loadConversations().catch(() => {})
	// Gate the chat the way the old Desk page did: if the customer hasn't
	// finished signup / LLM setup, send them to the onboarding wizard. A
	// transient failure falls through to the chat rather than trapping them.
	const r = await readyP
	if (r && r.ready === false) {
		window.location.assign("/app/jarvis-onboarding")
		return
	}
	socket?.on("jarvis:event", onEvent)
	// Live tool list for the "Tools available" count + /tool autocomplete
	// (best-effort; falls back to the seeded core set on failure).
	api.listTools().then((t) => { if (Array.isArray(t) && t.length) jarvisTools.value = t }).catch(() => {})
	document.addEventListener("pointerdown", onDocClick)
	window.addEventListener("keydown", onGlobalKey)
	_thinkTimer = setInterval(() => { thinkTick.value = busy.value ? thinkTick.value + 1 : 0 }, 2200)
	// Track the OS color scheme so theme:'system' updates live.
	_mq = window.matchMedia("(prefers-color-scheme: dark)")
	prefersDark.value = _mq.matches
	_mq.addEventListener("change", onColorScheme)
	ui.value = (await uiP) || {}
	// Load custom skills so the "/" composer menu can offer them.
	loadCustomSkills()
	try {
		await convsP
		// Restore the chat the user was last on (survives refresh + duplicated tab)
		// before falling back to the first sidebar entry, so a starred chat sorting
		// to the top never hijacks navigation away from your current chat.
		let _stored = null
		try { _stored = localStorage.getItem("jarvis-last-conv") } catch (e) {}
		const _storedValid = _stored && conversations.value.some((c) => c.name === _stored)
		const first = route.params.id || (_storedValid ? _stored : null) || conversations.value[0]?.name
		if (first) {
			currentId.value = first
			await loadConversation(first)
		}
	} finally {
		booting.value = false // reveal welcome/thread only after the first load
	}
	// The thread (and its chart skeletons) only enter the DOM now that booting is
	// false — loadConversation's earlier processMermaid pass ran against an empty
	// thread, so render the charts here once they're actually mounted.
	await nextTick()
	processMermaid()
	inputEl.value?.focus()
})
onBeforeUnmount(() => {
	socket?.off("jarvis:event", onEvent)
	document.removeEventListener("pointerdown", onDocClick)
	window.removeEventListener("keydown", onGlobalKey)
	clearInterval(_thinkTimer)
	_mq?.removeEventListener("change", onColorScheme)
})
// Global keyboard shortcuts (documented in Settings → Shortcuts).
function onGlobalKey(e) {
	if (e.defaultPrevented) return
	if (e.ctrlKey && e.shiftKey && (e.key === "O" || e.key === "o")) {
		e.preventDefault(); newChat()
	} else if (e.ctrlKey && !e.shiftKey && !e.altKey && (e.key === "B" || e.key === "b")) {
		e.preventDefault(); toggleSidebar()
	} else if (e.key === "Escape" && confirmBox.value) {
		_settleConfirm(false)
	} else if (e.key === "Escape" && artifact.value) {
		closeArtifact()
	} else if (e.key === "Escape" && macroMerge.value) {
		dropMacroMerge("")
	} else if (e.key === "Escape" && macroEditorOpen.value) {
		closeMacroEditor()
	} else if (e.key === "Escape" && macrosModalOpen.value) {
		closeMacrosModal()
	} else if (e.key === "Escape" && shareModalOpen.value) {
		closeShareModal()
	} else if (e.key === "Escape" && skillsModalOpen.value) {
		closeSkillsModal()
	} else if (e.key === "Escape" && settingsOpen.value) {
		settingsOpen.value = false
	}
}
</script>

<style scoped>
/* Native form controls (select dropdowns, date/time pickers, scrollbars)
   follow the app theme instead of the OS default — without this, a dark app
   pops white select menus and calendar popups. */
.jv-root { color-scheme: light; }
.jv-root.jv-dark { color-scheme: dark; }
/* Refined Indigo brand mark (dark mode): the spark boxes — sidebar brand,
   rail logo, empty-state hero, assistant avatars, proactive toast — trade the
   flat accent fill for an indigo→violet gradient with a soft indigo glow.
   !important beats the elements' inline background:var(--blue). */
.jv-dark .jv-logo,
.jv-dark .jv-rail-logo,
.jv-dark .jv-toast-ic {
	background: linear-gradient(135deg, #6e8bff, #8b5cf6) !important;
	box-shadow: 0 2px 10px rgba(110, 139, 255, .35) !important;
}
/* primary buttons also invert to black/white on hover (depends on their base
   color, so the white text/icon flips to the surface color). !important beats
   the inline backgrounds on the new-chat and send buttons. */
.jv-newchat:hover { background: var(--text) !important; color: var(--surface) !important; }
.jv-newchat:hover svg { stroke: var(--surface) !important; }
/* Send button: springy lift + arrow nudge on hover, press-in on click, and a
   one-shot pop when it becomes ready (text entered). */
.jv-sendbtn { transition: transform .16s cubic-bezier(.34, 1.56, .64, 1), background .14s ease; }
.jv-sendbtn svg { transition: transform .16s ease; }
.jv-sendbtn:not(:disabled):hover { transform: translateY(-2px) scale(1.07); }
.jv-sendbtn:not(:disabled):hover svg { transform: translateY(-2px); }
.jv-sendbtn:not(:disabled):active { transform: scale(.9); }
.jv-sendbtn.ready { animation: jv-send-pop .3s ease; }
@keyframes jv-send-pop { 0% { transform: scale(.7); } 55% { transform: scale(1.15); } 100% { transform: scale(1); } }
.jv-sendbtn:hover:not(:disabled) { background: var(--text) !important; }
.jv-sendbtn:hover:not(:disabled) svg { stroke: var(--surface) !important; }
/* Collapsible sidebar: slide it off-screen (root has overflow:hidden) so the
   chat reclaims the full width, openclaw-style. */
.jv-sidebar { transition: width .2s ease; }
/* Collapsed → slim icon rail: shrink to a bar and hide everything but the rail. */
.jv-sidebar.collapsed { width: 56px !important; }
/* `!important` is required: the sidebar header carries an inline
   `display:flex`, which beats a plain rule and would otherwise leak the logo +
   "ERPNext Assistant" text into (and below) the collapsed rail. */
.jv-sidebar.collapsed > *:not(.jv-rail) { display: none !important; }
.jv-rail { display: flex; flex-direction: column; align-items: center; gap: 7px; height: 100%; padding: 12px 0; }
.jv-rail-logo { width: 30px; height: 30px; border-radius: 8px; background: var(--blue); display: flex; align-items: center; justify-content: center; flex: none; margin-bottom: 3px; box-shadow: 0 1px 2px rgba(37,99,235,.35); }
.jv-rail-btn { width: 38px; height: 38px; display: flex; align-items: center; justify-content: center; background: transparent; border: none; border-radius: 9px; cursor: pointer; color: var(--text-2); flex: none; transition: background .12s, color .12s; }
.jv-rail-btn:hover { background: var(--surface-2); color: var(--text); }
.jv-rail-new { background: var(--blue); color: #fff; }
.jv-rail-new:hover { background: var(--blue); color: #fff; filter: brightness(1.08); }
.jv-rail-avatar { width: 32px; height: 32px; border-radius: 50%; background: #e7ddcf; color: #8a6d3b; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; cursor: pointer; flex: none; }
.jv-conv { position: relative; display: flex; align-items: center; gap: 9px; padding: 7px 9px; border-radius: 6px; cursor: pointer; margin-bottom: 1px; }
.jv-conv:hover { background: var(--surface-2); }
.jv-conv.on { background: var(--surface-3); }
.jv-conv-ic { flex: none; }
.jv-conv-title { flex: 1; min-width: 0; font-size: 13px; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.jv-conv.on .jv-conv-title { color: var(--text); font-weight: 500; }
.jv-conv-more { flex: none; width: 22px; height: 22px; display: flex; align-items: center; justify-content: center; border: none; background: transparent; border-radius: 5px; color: var(--text-3); cursor: pointer; opacity: 0; }
.jv-conv:hover .jv-conv-more, .jv-conv-more:focus { opacity: 1; }
.jv-conv-more:hover { background: var(--surface-3); color: var(--text); }
.jv-conv-menu { position: absolute; top: calc(100% - 2px); right: 6px; z-index: 25; min-width: 150px; background: var(--surface); border: 1px solid var(--border-2); border-radius: 9px; box-shadow: 0 10px 28px rgba(20, 20, 30, 0.18); padding: 5px; }
.jv-menuitem-danger { color: var(--red); }
.jv-menuitem-danger svg { color: var(--red); }
.jv-menuitem-danger:hover { background: var(--red-bg); }
.jv-rename-input { flex: 1; min-width: 0; font-family: inherit; font-size: 13px; color: var(--text); background: var(--surface); border: 1px solid var(--blue); border-radius: 5px; padding: 3px 6px; outline: none; }
.jv-suggest:hover { border-color: var(--border-2); background: var(--surface-1); }
/* buttons invert to black/white on hover (theme-adaptive: black on light,
   white on dark) — var(--text)/var(--surface) flip, with an svg-stroke
   override so the icon stays visible on the inverted background. */
.jv-iconbtn:hover { background: var(--text) !important; color: var(--surface) !important; }
.jv-iconbtn:hover svg { stroke: var(--surface) !important; }
.jv-iconbtn-bd:hover { background: var(--text) !important; border-color: var(--text) !important; }
.jv-iconbtn-bd:hover svg { stroke: var(--surface) !important; }
.jv-ctxbtn:hover { background: var(--surface-2); }
.jv-retry:hover { filter: brightness(0.94); }
.jv-modelpill:hover { background: var(--text) !important; border-color: var(--text) !important; }
.jv-modelpill:hover svg { stroke: var(--surface) !important; }
.jv-modelpill:hover span { color: var(--surface) !important; }
.jv-menuitem { display: flex; align-items: center; gap: 9px; width: 100%; padding: 7px 9px; border: none; background: transparent; border-radius: 7px; font-family: inherit; font-size: 12.5px; color: var(--text); cursor: pointer; text-align: left; }
.jv-menuitem:hover, .jv-menuitem.on { background: var(--surface-1); }
.jv-usercard { transition: background 0.12s; }
.jv-usercard:hover { background: var(--surface-2); }
/* black focus highlight on the composer */
.jv-composer:focus-within { border-color: var(--text); box-shadow: 0 0 0 3px rgba(23, 23, 23, 0.07); }
/* jump-to-latest arrow — floats just above the composer, centered */
.jv-scrolldown {
	position: absolute;
	left: 50%;
	bottom: 100%;
	margin-bottom: 12px;
	transform: translateX(-50%);
	z-index: 20;
	width: 38px;
	height: 38px;
	display: flex;
	align-items: center;
	justify-content: center;
	padding: 0;
	border-radius: 50%;
	background: var(--surface);
	color: var(--text-2);
	border: 1px solid var(--border-2);
	box-shadow: 0 6px 20px rgba(20, 20, 30, 0.18);
	cursor: pointer;
	transition: color .12s, border-color .12s, background .12s, transform .12s, box-shadow .12s;
}
.jv-scrolldown:hover { color: var(--text); border-color: var(--text-3); transform: translateX(-50%) translateY(-2px); box-shadow: 0 9px 24px rgba(20, 20, 30, 0.22); }
.jv-scrolldown:active { transform: translateX(-50%) scale(.92); }
.jv-sd-enter-active, .jv-sd-leave-active { transition: opacity .18s ease, transform .18s ease; }
.jv-sd-enter-from, .jv-sd-leave-to { opacity: 0; transform: translateX(-50%) translateY(10px); }
/* response metrics (tools · time) */
.jv-skillused { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
.jv-skillused-chip { display: inline-flex; align-items: center; gap: 5px; padding: 2px 9px 2px 7px; background: var(--blue-bg); border: 1px solid var(--blue); border-radius: 20px; font-size: 11px; font-weight: 600; color: var(--blue); }
.jv-meta { display: flex; align-items: center; gap: 14px; margin-top: 9px; font-size: 11px; color: var(--text-3); }
/* Tool activity (openclaw-style): collapsible list of tool calls with I/O */
.jv-activity { margin: 0 0 10px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-1); overflow: hidden; }
.jv-activity-head { display: flex; align-items: center; gap: 7px; width: 100%; padding: 7px 11px; background: transparent; border: none; cursor: pointer; font-family: inherit; font-size: 12px; color: var(--text-2); text-align: left; }
.jv-activity-head:hover { background: var(--surface-2); }
.jv-activity-chev { flex: none; color: var(--text-3); transition: transform .15s ease; }
.jv-activity-chev.open { transform: rotate(90deg); }
.jv-activity-count { font-weight: 600; color: var(--text); flex: none; }
.jv-activity-preview { color: var(--text-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.jv-activity-body { border-top: 1px solid var(--border); padding: 5px; display: flex; flex-direction: column; gap: 4px; }
.jv-tool { border: 1px solid var(--border); border-radius: 8px; background: var(--surface); overflow: hidden; }
.jv-tool-head { display: flex; align-items: center; gap: 8px; width: 100%; padding: 7px 10px; background: transparent; border: none; cursor: pointer; font-family: inherit; font-size: 12.5px; color: var(--text); text-align: left; }
.jv-tool-head:hover { background: var(--surface-1); }
.jv-tool-dot { width: 7px; height: 7px; border-radius: 50%; flex: none; }
.jv-tool-dot.ok { background: var(--green); }
.jv-tool-dot.err { background: var(--red); }
.jv-tool-dot.run { background: var(--amber); animation: jv-pulse 1s ease-in-out infinite; }
@keyframes jv-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
.jv-tool-name { font-weight: 550; font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; }
.jv-tool-status { margin-left: auto; font-size: 11px; color: var(--text-3); }
.jv-tool-chev { flex: none; color: var(--text-3); transition: transform .15s ease; }
.jv-tool-chev.open { transform: rotate(90deg); }
.jv-tool-detail { padding: 4px 11px 11px; border-top: 1px solid var(--border); }
.jv-tool-io-k { font-size: 10.5px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--text-3); margin: 9px 0 4px; }
.jv-tool-io { margin: 0; padding: 9px 11px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 7px; font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 11.5px; line-height: 1.5; color: var(--text); white-space: pre-wrap; word-break: break-word; overflow-x: auto; max-height: 320px; overflow-y: auto; }
/* per-message Copy/Edit bar — revealed on hover */
.jv-msgbar { display: flex; gap: 3px; margin-top: 5px; opacity: 0; transition: opacity .12s ease; }
.jv-umsg:hover .jv-msgbar, .jv-amsg:hover .jv-msgbar { opacity: 1; }
.jv-msgbtn { display: flex; align-items: center; justify-content: center; width: 26px; height: 26px; border: none; background: transparent; border-radius: 6px; cursor: pointer; color: var(--text-3); }
.jv-msgbtn:hover { background: var(--surface-2); color: var(--text); }
.jv-meta span { display: inline-flex; align-items: center; gap: 4px; }
/* live tool activity rows */
.jv-toolrow { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--text-2); padding: 2px 0; }
.jv-toolrow b { font-weight: 600; color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.jv-tooldone { color: var(--text-3); font-size: 12px; }
.jv-spin { animation: jv-spin 0.8s linear infinite; }
@keyframes jv-spin { to { transform: rotate(360deg); } }

/* inline canvas/chart artifacts (rendered sandboxed) */
.jv-canvas { margin-top: 12px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--surface); }
.jv-chartwrap { margin: 10px 0; border: 1px solid var(--border); border-radius: 10px; padding: 8px 10px; background: var(--surface); }
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
.jv-md :deep(.jv-mermaid) { position: relative; margin: 8px 0 12px; text-align: center; overflow-x: auto; }
.jv-md :deep(.jv-mermaid svg) { max-width: 100%; height: auto; }
/* skeleton shimmer while a chart hasn't rendered to SVG yet (no data-rendered) —
   hides the raw mermaid source so the user never sees the markup flash. */
.jv-md :deep(.jv-mermaid:not([data-rendered])) { min-height: 196px; color: transparent !important; user-select: none; overflow: hidden; border-radius: 10px; border: 1px solid var(--border); background: var(--surface-1); }
.jv-md :deep(.jv-mermaid:not([data-rendered])) * { color: transparent !important; }
.jv-md :deep(.jv-mermaid:not([data-rendered]))::after { content: ""; position: absolute; inset: 0; background: linear-gradient(100deg, transparent 20%, var(--surface-2) 50%, transparent 80%); background-size: 220% 100%; animation: jv-shimmer 1.25s ease-in-out infinite; }
@keyframes jv-shimmer { 0% { background-position: 180% 0; } 100% { background-position: -180% 0; } }
.jv-md :deep(.jv-chart-dl) { position: absolute; top: 6px; right: 6px; width: 26px; height: 26px; display: inline-flex; align-items: center; justify-content: center; padding: 0; background: var(--surface); color: var(--text-3); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; opacity: 0; transition: opacity .12s, color .12s, background .12s; }
.jv-md :deep(.jv-mermaid:hover .jv-chart-dl) { opacity: 1; }
.jv-md :deep(.jv-chart-dl:hover) { color: var(--text); background: var(--surface-1); border-color: var(--border-2); }
.jv-switch { width: 38px; height: 22px; flex: none; border: none; border-radius: 11px; background: var(--surface-3); position: relative; cursor: pointer; padding: 0; transition: background .15s; }
.jv-switch.on { background: var(--green); }
.jv-switch-knob { position: absolute; top: 2px; left: 2px; width: 18px; height: 18px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(0, 0, 0, .25); transition: left .15s; }
.jv-switch.on .jv-switch-knob { left: 18px; }
.jv-md :deep(.jv-md-pre) { margin: 6px 0 12px; padding: 12px 14px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; overflow-x: auto; }
.jv-md :deep(.jv-md-pre code) { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--text); white-space: pre; }

/* markdown content → the imported design's table look */
.jv-md :deep(.jv-md-p) { margin: 0 0 10px; }
.jv-md :deep(.jv-md-p:last-child) { margin-bottom: 0; }
.jv-md :deep(.jv-md-list) { margin: 0 0 10px; padding-left: 20px; }
.jv-md :deep(.jv-md-list li) { margin: 2px 0; }
.jv-md :deep(.jv-md-code) { background: var(--surface-2); padding: 1px 5px; border-radius: 4px; font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.jv-md :deep(.jv-md-link) { color: var(--blue); text-decoration: none; font-weight: 500; }
/* Auto-linked document IDs → open the record in ERPNext Desk. Dashed underline
   marks them as record links, distinct from plain markdown links. */
.jv-md :deep(.jv-doclink) { color: var(--blue); text-decoration: none; font-weight: 550; border-bottom: 1px dashed var(--blue); cursor: pointer; transition: background .12s; }
.jv-md :deep(.jv-doclink:hover) { border-bottom-style: solid; background: var(--blue-bg); border-radius: 3px; }
.jv-md :deep(.jv-md-tablewrap) { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; margin: 4px 0 10px; }
.jv-md :deep(.jv-md-table) { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.jv-md :deep(.jv-md-table th) { padding: 8px 13px; font-weight: 550; color: var(--text-3); background: var(--surface-1); border-bottom: 1px solid var(--border); }
.jv-md :deep(.jv-md-table td) { padding: 9px 13px; border-bottom: 1px solid var(--border); color: var(--text); font-variant-numeric: tabular-nums; }
.jv-md :deep(.jv-md-table tr:last-child td) { border-bottom: 0; }

/* ===== settings panel (slide-over console) ===== */
/* settings: centered modal (Claude-style) with a left section nav */
.jv-settings-overlay { position: absolute; inset: 0; z-index: 60; background: rgba(15, 15, 22, 0.34); display: flex; align-items: center; justify-content: center; padding: 24px; }
.jv-dark .jv-settings-overlay { background: rgba(0, 0, 0, 0.55); }
.jv-settings { width: 760px; max-width: 100%; height: 560px; max-height: 88vh; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; display: flex; overflow: hidden; box-shadow: 0 24px 70px rgba(20, 20, 30, 0.28); animation: jv-popin 0.16s ease; }
@keyframes jv-popin { from { transform: scale(0.97); opacity: 0; } to { transform: scale(1); opacity: 1; } }
.jv-settings-nav { width: 196px; flex: none; background: var(--surface-1); border-right: 1px solid var(--border); padding: 14px 10px; display: flex; flex-direction: column; gap: 2px; }
.jv-settings-nav-title { font-size: 15px; font-weight: 700; color: var(--text); padding: 4px 10px 12px; }
.jv-settings-navitem { display: flex; align-items: center; gap: 9px; width: 100%; padding: 8px 10px; border: none; background: transparent; border-radius: 8px; font-family: inherit; font-size: 13px; font-weight: 500; color: var(--text-2); cursor: pointer; text-align: left; }
.jv-settings-navitem svg { color: var(--text-3); flex: none; }
.jv-settings-navitem:hover { background: var(--surface-2); color: var(--text); }
.jv-settings-navitem.on { background: var(--surface-3); color: var(--text); }
.jv-settings-navitem.on svg { color: var(--text); }
.jv-settings-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.jv-settings-head { display: flex; align-items: center; justify-content: space-between; padding: 15px 18px; border-bottom: 1px solid var(--border); flex: none; }
.jv-settings-body { flex: 1; overflow-y: auto; padding: 18px 22px 28px; }
.jv-set-sec { font-size: 11px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; margin: 0 0 8px; }
/* openclaw-style usage stat cards */
.jv-statgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 11px; }
.jv-stat { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 13px 15px; }
.jv-stat-label { font-size: 10px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; color: var(--text-3); }
.jv-stat-val { font-size: 22px; font-weight: 650; color: var(--text); margin-top: 5px; line-height: 1.05; }
.jv-stat-sub { font-size: 11px; color: var(--text-3); margin-top: 3px; }
.jv-set-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--border); font-size: 13px; color: var(--text-2); }
.jv-set-row:last-child { border-bottom: 0; }
.jv-set-row b { font-weight: 600; color: var(--text); text-align: right; }
.jv-set-empty { font-size: 12.5px; color: var(--text-3); padding: 14px 0; }
.jv-set-hint { font-size: 11.5px; color: var(--text-3); margin-top: 9px; }
.jv-kbd-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--border); font-size: 13px; color: var(--text-2); }
.jv-kbd-row:last-of-type { border-bottom: 0; }
.jv-kbd { display: inline-flex; align-items: center; justify-content: center; min-width: 22px; height: 22px; padding: 0 6px; background: var(--surface-1); border: 1px solid var(--border-2); border-bottom-width: 2px; border-radius: 6px; font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 11.5px; font-weight: 600; color: var(--text); }
.jv-kbd-plus { color: var(--text-3); margin: 0 3px; font-size: 11px; }
.jv-est { font-size: 9.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; }
.jv-usage-bar { margin-top: 12px; height: 7px; border-radius: 99px; background: var(--surface-2); overflow: hidden; }
.jv-usage-fill { height: 100%; border-radius: 99px; background: var(--blue); transition: width .25s ease; }
/* custom skills */
.jv-skill-btn { padding: 6px 12px; background: var(--blue); border: 1px solid var(--blue); border-radius: 8px; font-family: inherit; font-size: 12.5px; font-weight: 600; color: #fff; cursor: pointer; white-space: nowrap; transition: opacity .12s; }
.jv-skill-btn:hover { opacity: .9; }
.jv-skill-btn:disabled { opacity: .5; cursor: default; }
.jv-skill-btn.ghost { background: transparent; color: var(--text-2); border-color: var(--border-2); }
.jv-skill-form { border: 1px solid var(--border); border-radius: 10px; padding: 14px; margin: 6px 0 14px; background: var(--surface-1); }
.jv-skill-err { font-size: 12px; color: var(--red); background: var(--red-bg); border: 1px solid var(--red-bd); border-radius: 7px; padding: 7px 10px; margin-bottom: 10px; }
.jv-skill-l { display: block; font-size: 11px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; margin: 0 0 4px; }
.jv-skill-in, .jv-skill-ta { width: 100%; box-sizing: border-box; padding: 8px 10px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; font-family: inherit; font-size: 13px; color: var(--text); outline: none; }
.jv-skill-ta { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; resize: vertical; line-height: 1.5; }
.jv-skill-in:focus, .jv-skill-ta:focus { border-color: var(--blue); }
.jv-skill-in:disabled { color: var(--text-3); }
.jv-skill-row { display: flex; align-items: center; gap: 8px; margin: 0 -10px; padding: 11px 10px; border-bottom: 1px solid var(--border); border-radius: 10px; transition: background .12s; }
.jv-skill-row:last-child { border-bottom: 0; }
.jv-skill-row:hover { background: var(--surface-1); }
/* ============ PREDEFINED PREMIUM BUTTON ============
   Reusable across the app. Compose a variant with the base:
     <button class="jv-btn jv-btn--primary">Save</button>
     <button class="jv-btn jv-btn--ghost">Cancel</button>
     <button class="jv-btn jv-btn--danger">Delete</button>
     <button class="jv-btn jv-btn--icon">…</button>   (icon-only)
   Add --sm for a compact size (header actions). */
.jv-btn { flex: none; display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 34px; padding: 0 15px; border-radius: 10px; border: 1px solid transparent; background: transparent; font-family: inherit; font-size: 12.5px; font-weight: 600; line-height: 1; white-space: nowrap; cursor: pointer; user-select: none; transition: background .15s ease, color .15s ease, border-color .15s ease, box-shadow .15s ease, transform .12s ease; }
.jv-btn:active { transform: scale(.97); }
.jv-btn:disabled { opacity: .5; cursor: default; pointer-events: none; box-shadow: none; transform: none; }
.jv-btn svg { flex: none; }
.jv-btn--primary { background: var(--blue); border-color: var(--blue); color: #fff; box-shadow: 0 1px 2px rgba(20, 20, 30, .12); }
.jv-btn--primary:hover { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(20, 20, 30, .18); }
.jv-btn--primary svg { stroke: #fff; }
.jv-btn--ghost { background: var(--surface); border-color: var(--border-2); color: var(--text-2); }
.jv-btn--ghost:hover { background: var(--surface-2); border-color: var(--border); color: var(--text); transform: translateY(-1px); }
.jv-btn--danger { background: var(--red); border-color: var(--red); color: #fff; box-shadow: 0 1px 2px rgba(220, 38, 38, .14); }
.jv-btn--danger:hover { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(220, 38, 38, .24); }
.jv-btn--danger svg { stroke: #fff; }
.jv-btn--sm { height: 32px; padding: 0 12px; font-size: 12px; border-radius: 9px; }
.jv-btn--icon { width: 32px; height: 32px; padding: 0; border-radius: 9px; color: var(--text-3); }
.jv-btn--icon:hover { background: var(--surface-2); color: var(--text); transform: none; }
.jv-btn--icon:active { transform: scale(.92); }
/* row action icons (skills/macros): color-coded semantic hovers + springy pop */
.jv-btn--icon.jv-ib:hover { transform: translateY(-1px); }
.jv-btn--icon.jv-ib:active { transform: scale(.88); }
.jv-btn--icon.jv-ib-accent:hover { background: var(--blue-bg); color: var(--blue); border-color: var(--blue-bd); }
.jv-btn--icon.jv-ib-danger:hover { background: var(--red-bg); color: var(--red); border-color: var(--red-bd); }

.jv-newpill { flex: none; display: inline-flex; align-items: center; gap: 5px; padding: 6px 12px 6px 10px; background: var(--blue); border: 1px solid var(--blue); border-radius: 9px; font-family: inherit; font-size: 12.5px; font-weight: 600; color: #fff; cursor: pointer; transition: opacity .12s, transform .06s; }
.jv-newpill:hover { opacity: .92; }
.jv-newpill:active { transform: scale(.97); }
.jv-newpill svg { stroke: #fff; }
.jv-skill-name { font-size: 13px; font-weight: 600; color: var(--text); font-family: ui-monospace, "SF Mono", Menlo, monospace; }
.jv-skill-off { font-size: 9.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; margin-left: 6px; font-family: inherit; }
.jv-skill-desc { font-size: 12px; color: var(--text-3); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* skill sharing: chips, dividers, read-only + share modal */
.jv-shared-chip { display: inline-flex; align-items: center; gap: 4px; margin-left: 8px; padding: 1px 7px 1px 6px; background: var(--blue-bg); color: var(--blue); border-radius: 999px; font-size: 10px; font-weight: 600; font-family: inherit; letter-spacing: .01em; vertical-align: middle; }
.jv-shared-chip svg { stroke: var(--blue); }
.jv-sharedby-chip { display: inline-flex; align-items: center; gap: 4px; margin-left: 8px; padding: 1px 7px 1px 6px; background: var(--surface-2); color: var(--text-3); border: 1px solid var(--border); border-radius: 999px; font-size: 10px; font-weight: 600; font-family: inherit; vertical-align: middle; }
.jv-share-divider { margin: 14px -10px 4px; padding: 6px 10px 4px; font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--text-3); border-top: 1px solid var(--border); }
.jv-skill-row-shared { opacity: .96; }
.jv-share-lock { flex: none; display: flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 8px; background: var(--surface-2); color: var(--text-3); border: 1px solid var(--border); }
.jv-ro-banner { display: flex; align-items: center; gap: 8px; padding: 9px 11px; margin-bottom: 13px; background: var(--blue-bg); border: 1px solid var(--blue); border-radius: 9px; font-size: 12.5px; color: var(--text-2); }
.jv-ro-banner svg { stroke: var(--blue); flex: none; }
.jv-ro-banner b { color: var(--text); font-weight: 600; }
/* share modal */
.jv-share-modal { height: auto; max-height: 82vh; }
.jv-share-chips { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 12px; }
.jv-share-chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 6px 3px 3px; background: var(--surface-1); border: 1px solid var(--border-2); border-radius: 999px; font-size: 12px; color: var(--text); box-shadow: 0 1px 2px rgba(20, 20, 30, .05); }
.jv-share-chip-name { font-weight: 500; max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jv-share-chip-x { flex: none; width: 18px; height: 18px; display: flex; align-items: center; justify-content: center; border: none; background: transparent; border-radius: 50%; color: var(--text-3); cursor: pointer; padding: 0; transition: background .12s, color .12s; }
.jv-share-chip-x:hover { background: var(--red-bg); color: var(--red); }
.jv-share-avatar { flex: none; width: 26px; height: 26px; border-radius: 50%; display: flex; align-items: center; justify-content: center; background: var(--blue); color: #fff; font-size: 10.5px; font-weight: 600; letter-spacing: .01em; box-shadow: 0 1px 2px rgba(37, 99, 235, .3); }
.jv-share-searchwrap { display: flex; align-items: center; gap: 8px; padding: 8px 11px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 9px; margin-bottom: 10px; }
.jv-share-searchwrap:focus-within { border-color: var(--blue); }
.jv-share-search { flex: 1; border: none; outline: none; background: transparent; font-family: inherit; font-size: 13px; color: var(--text); }
.jv-share-list { display: flex; flex-direction: column; gap: 2px; max-height: 280px; overflow-y: auto; margin: 0 -6px; }
.jv-share-row { display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; background: transparent; border: none; border-radius: 9px; cursor: pointer; text-align: left; transition: background .12s; }
.jv-share-row:hover { background: var(--surface-1); }
.jv-share-row.on { background: var(--blue-bg); }
.jv-share-row-info { display: flex; flex-direction: column; min-width: 0; flex: 1; line-height: 1.25; }
.jv-share-row-name { font-size: 13px; font-weight: 550; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jv-share-row-id { font-size: 11px; color: var(--text-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jv-share-check { flex: none; }
.jv-share-helper { display: flex; align-items: center; gap: 7px; margin-top: 13px; padding: 9px 11px; background: var(--surface-1); border: 1px solid var(--border); border-radius: 9px; font-size: 11.5px; color: var(--text-3); line-height: 1.4; }
.jv-share-helper svg { stroke: var(--text-3); flex: none; }
/* right sidebar: custom skills */
.jv-skillbar { width: 52px; flex: none; height: 100%; background: var(--surface-1); border-left: 1px solid var(--border); display: flex; flex-direction: column; min-width: 0; }
/* centered skills popup */
.jv-skills-overlay { position: absolute; inset: 0; z-index: 62; background: rgba(15, 15, 22, 0.34); display: flex; align-items: center; justify-content: center; padding: 24px; }
.jv-dark .jv-skills-overlay { background: rgba(0, 0, 0, 0.55); }
.jv-skills-modal { width: 760px; max-width: 100%; height: 560px; max-height: 88vh; display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; overflow: hidden; box-shadow: 0 24px 70px rgba(20, 20, 30, 0.28); animation: jv-popin 0.16s ease; }
.jv-skills-head { flex: none; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 15px 16px 14px 20px; border-bottom: 1px solid var(--border); }
.jv-skills-head > div:first-child { flex: 1 1 auto; min-width: 0; align-self: center; }
.jv-skills-title { font-size: 15px; font-weight: 600; color: var(--text); letter-spacing: -.01em; }
.jv-skills-sub { font-size: 11.5px; color: var(--text-3); margin-top: 2px; }
.jv-skills-status { flex: none; display: flex; align-items: center; gap: 7px; font-size: 11.5px; color: var(--text-3); padding: 11px 20px; background: var(--surface-1); border-bottom: 1px solid var(--border); }
.jv-skills-status.ok { color: var(--green); }
.jv-skills-status.err { color: var(--red); }
.jv-skills-body { flex: 1; overflow-y: auto; padding: 16px 20px 20px; }
.jv-skill-newrow { display: flex; align-items: center; gap: 8px; width: 100%; justify-content: center; padding: 10px; margin-bottom: 12px; background: var(--blue-bg); border: 1px dashed var(--blue); border-radius: 10px; font-family: inherit; font-size: 13px; font-weight: 600; color: var(--blue); cursor: pointer; }
.jv-skill-newrow:hover { background: var(--blue); color: #fff; }
.jv-skill-newrow:hover svg { stroke: #fff; }
.jv-skill-formfoot { display: flex; align-items: center; gap: 10px; margin-top: 15px; flex-wrap: wrap; }
.jv-skill-foothint { font-size: 11px; color: var(--text-3); }
.jv-skillrail { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 16px 0; }
.jv-skillrail-btn { position: relative; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; background: transparent; border: 1px solid transparent; border-radius: 12px; color: var(--text-2); cursor: pointer; transition: background .14s, border-color .14s, color .14s, transform .06s; }
.jv-skillrail-btn:hover { background: var(--surface-2); border-color: var(--border); color: var(--text); }
.jv-skillrail-btn:active { transform: scale(.94); }
.jv-skillrail-btn.active { background: var(--blue-bg); border-color: transparent; color: var(--blue); }
.jv-railtip { position: absolute; right: calc(100% + 12px); top: 50%; transform: translateY(-50%) translateX(4px); background: var(--text); color: var(--surface); font-size: 11.5px; font-weight: 600; letter-spacing: .01em; padding: 4px 9px; border-radius: 7px; white-space: nowrap; opacity: 0; pointer-events: none; transition: opacity .13s, transform .13s; box-shadow: 0 6px 18px rgba(0, 0, 0, .2); }
.jv-skillrail-btn:hover .jv-railtip { opacity: 1; transform: translateY(-50%) translateX(0); }
.jv-skillbar-head { flex: none; display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding: 14px 14px 12px 16px; border-bottom: 1px solid var(--border); }
.jv-skillbar-title { font-size: 15px; font-weight: 600; color: var(--text); letter-spacing: -.01em; }
.jv-skillbar-sub { font-size: 11px; color: var(--text-3); margin-top: 2px; }
.jv-skillbar-actions { flex: none; display: flex; gap: 8px; padding: 12px 16px 0; }
.jv-skillbar-actions .jv-skill-btn { flex: 1; text-align: center; }
.jv-skillbar-status { flex: none; display: flex; align-items: center; gap: 7px; font-size: 11.5px; color: var(--text-3); padding: 10px 16px 0; line-height: 1.4; }
.jv-skillbar-status.ok { color: var(--green); }
.jv-skillbar-status.err { color: var(--red); }
.jv-skill-dot { width: 7px; height: 7px; border-radius: 99px; background: var(--text-3); flex: none; }
.jv-skill-dot.ok { background: var(--green); }
.jv-skill-dot.err { background: var(--red); }
.jv-skill-dot.spin { border: 2px solid var(--border-2); border-top-color: var(--blue); background: transparent; width: 11px; height: 11px; animation: jv-spin .7s linear infinite; }
@keyframes jv-spin { to { transform: rotate(360deg); } }
.jv-skillbar-body { flex: 1; overflow-y: auto; padding: 12px 16px 18px; }
.jv-iconbtn-bd.on { background: var(--blue-bg) !important; border-color: var(--blue) !important; }
.jv-iconbtn-bd.on svg { stroke: var(--blue); }
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
/* macro run history dashboard (settings → Macro runs) */
.jv-runfilters { display: flex; align-items: center; gap: 10px; margin: 16px 0 6px; flex-wrap: wrap; }
.jv-runchips { display: inline-flex; background: var(--surface-1); border: 1px solid var(--border); border-radius: 9px; padding: 3px; gap: 2px; }
.jv-runchips button { font-family: inherit; font-size: 12px; font-weight: 550; padding: 5px 11px; border-radius: 6px; color: var(--text-3); cursor: pointer; border: none; background: transparent; }
.jv-runchips button.on { background: var(--surface-3); color: var(--text); }
.jv-runmacrosel { margin-left: auto; font-family: inherit; font-size: 12px; color: var(--text-2); background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; cursor: pointer; outline: none; }
.jv-runmacrosel:focus { border-color: var(--blue); }
.jv-run { display: flex; align-items: flex-start; gap: 11px; padding: 12px 2px; border-bottom: 1px solid var(--surface-2); }
.jv-run:last-of-type { border-bottom: none; }
.jv-run-dot { flex: none; width: 9px; height: 9px; border-radius: 50%; margin-top: 5px; }
.jv-run-dot.d-ok { background: var(--green); }
.jv-run-dot.d-err { background: var(--red); }
.jv-run-dot.d-run { background: var(--blue); box-shadow: 0 0 0 3px var(--blue-bg); }
.jv-run-dot.d-stop { background: var(--text-3); }
.jv-run-main { flex: 1; min-width: 0; }
.jv-run-top { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.jv-run-name { font-size: 13.5px; font-weight: 600; color: var(--text); }
.jv-run-badge { font-size: 10.5px; font-weight: 600; padding: 2px 8px; border-radius: 99px; text-transform: capitalize; }
.jv-run-badge.b-ok { background: var(--green-bg); color: var(--green); border: 1px solid var(--green-bd); }
.jv-run-badge.b-err { background: var(--red-bg); color: var(--red); border: 1px solid var(--red-bd); }
.jv-run-badge.b-run { background: var(--blue-bg); color: var(--blue); border: 1px solid var(--blue-bd); }
.jv-run-badge.b-stop { background: var(--surface-2); color: var(--text-3); border: 1px solid var(--border-2); }
.jv-run-trig { display: inline-flex; align-items: center; gap: 4px; font-size: 10.5px; color: var(--text-3); }
.jv-run-meta { display: flex; align-items: center; gap: 8px; font-size: 11.5px; color: var(--text-3); margin-top: 4px; flex-wrap: wrap; }
.jv-run-prog { font-family: ui-monospace, Menlo, monospace; }
.jv-run-sep { opacity: .5; }
.jv-run-err { display: flex; align-items: center; gap: 5px; margin-top: 5px; font-size: 11.5px; color: var(--red); word-break: break-word; }
.jv-run-err svg { flex: none; }
.jv-run-act { display: flex; align-items: center; gap: 6px; flex: none; }
.jv-run-btn { display: inline-flex; align-items: center; gap: 5px; font-family: inherit; font-size: 11.5px; font-weight: 550; padding: 5px 11px; border-radius: 7px; cursor: pointer; background: var(--surface); color: var(--text-2); border: 1px solid var(--border-2); }
.jv-run-btn:hover { color: var(--text); border-color: var(--text-3); }
.jv-run-btn.stop { background: var(--red-bg); color: var(--red); border-color: var(--red-bd); }
.jv-run-btn.stop:hover { background: var(--red); color: #fff; border-color: var(--red); }
.jv-run-loadmore { display: block; margin: 14px auto 2px; font-family: inherit; font-size: 12px; font-weight: 550; color: var(--text-2); background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 8px 18px; cursor: pointer; }
.jv-run-loadmore:disabled { opacity: .6; cursor: default; }
/* fade for the overlay */
.jv-fade-enter-active, .jv-fade-leave-active { transition: opacity .16s ease; }
.jv-fade-enter-from, .jv-fade-leave-to { opacity: 0; }

/* artifact card (in the message) */
/* generated-image artifact: clickable thumbnail */
.jv-img-artifact { display: block; position: relative; margin-top: 12px; padding: 0; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-1); cursor: zoom-in; overflow: hidden; max-width: 380px; line-height: 0; }
.jv-img-artifact:hover { border-color: var(--border-2); }
.jv-img-artifact img { display: block; width: 100%; max-height: 320px; object-fit: cover; }
.jv-img-artifact-cap { display: flex; align-items: center; gap: 6px; padding: 7px 10px; font-family: inherit; font-size: 11.5px; line-height: 1.3; color: var(--text-3); background: var(--surface); border-top: 1px solid var(--border); }
.jv-artifact { display: flex; align-items: center; gap: 11px; width: 100%; margin-top: 12px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); cursor: pointer; text-align: left; font-family: inherit; transition: border-color .12s, background .12s; }
.jv-artifact:hover { border-color: var(--border-2); background: var(--surface-1); }
.jv-artifact-ic { flex: none; width: 34px; height: 34px; border-radius: 8px; display: flex; align-items: center; justify-content: center; background: var(--blue-bg); color: var(--blue); }
.jv-artifact-ic.t-pdf { background: var(--red-bg); color: var(--red); }
.jv-artifact-ic.t-image { background: var(--green-bg); color: var(--green); }
.jv-artifact-ic.t-html, .jv-artifact-ic.t-svg { background: var(--amber-bg); color: var(--amber); }
.jv-artifact-txt { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.jv-artifact-title { font-size: 13px; font-weight: 550; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.jv-artifact-sub { font-size: 10px; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; }
.jv-artifact-go { color: var(--text-3); flex: none; }

/* confirm / cancel card for a pending ERP-mutating action */
.jv-confirm { display: flex; align-items: center; gap: 10px; margin-top: 12px; padding: 10px 12px; border: 1px solid var(--amber-bd); background: var(--amber-bg); border-radius: 10px; }
.jv-confirm > svg { flex: none; }
.jv-confirm-label { flex: 1; min-width: 0; font-size: 13px; font-weight: 550; color: var(--text); }
.jv-confirm-no, .jv-confirm-yes { font-family: inherit; font-size: 12.5px; font-weight: 600; padding: 6px 14px; border-radius: 7px; cursor: pointer; border: 1px solid var(--border-2); flex: none; }
.jv-confirm-no { background: var(--surface); color: var(--text-2); }
.jv-confirm-no:hover { background: var(--text); color: var(--surface); border-color: var(--text); }
.jv-confirm-yes { background: var(--blue); color: #fff; border-color: var(--blue); }
.jv-confirm-yes:hover { background: var(--text); color: var(--surface); border-color: var(--text); }

/* interactive clarifying-question cards */
.jv-ask { margin-top: 12px; padding: 14px; border: 1px solid var(--border); background: var(--surface-1); border-radius: 12px; }
.jv-ask-q { padding-bottom: 13px; margin-bottom: 13px; border-bottom: 1px solid var(--border); }
.jv-ask-q:last-of-type { border-bottom: 0; padding-bottom: 4px; margin-bottom: 4px; }
.jv-ask-qt { display: flex; align-items: flex-start; gap: 8px; font-size: 13.5px; font-weight: 600; color: var(--text); margin-bottom: 9px; line-height: 1.4; }
.jv-ask-num { flex: none; width: 19px; height: 19px; border-radius: 99px; background: var(--blue-bg); color: var(--blue); font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; margin-top: 1px; }
.jv-ask-opts { display: flex; flex-wrap: wrap; gap: 7px; }
.jv-ask-opt { display: inline-flex; align-items: center; gap: 6px; padding: 7px 12px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 9px; font-family: inherit; font-size: 12.5px; font-weight: 500; color: var(--text-2); cursor: pointer; transition: border-color .12s, background .12s, color .12s; }
.jv-ask-opt:hover { border-color: var(--border-2); color: var(--text); }
.jv-ask-opt.on { border-color: var(--blue); background: var(--blue-bg); color: var(--text); font-weight: 600; }
.jv-ask-tick { color: var(--blue); font-weight: 700; font-size: 11px; }
.jv-ask-field { width: 100%; box-sizing: border-box; padding: 8px 10px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; font-family: inherit; font-size: 13px; color: var(--text); outline: none; }
.jv-ask-field:focus { border-color: var(--blue); }
.jv-ask-link { position: relative; }
.jv-ask-linkmenu { position: absolute; left: 0; right: 0; top: calc(100% + 4px); z-index: 20; background: var(--surface); border: 1px solid var(--border-2); border-radius: 9px; box-shadow: 0 8px 24px rgba(20, 20, 30, .14); padding: 4px; max-height: 220px; overflow-y: auto; }
.jv-ask-linkmenu button { display: block; width: 100%; text-align: left; padding: 7px 9px; background: transparent; border: none; border-radius: 6px; font-family: inherit; font-size: 12.5px; color: var(--text-2); cursor: pointer; }
.jv-ask-linkmenu button:hover { background: var(--surface-2); color: var(--text); }
.jv-ask-other { width: 100%; box-sizing: border-box; margin-top: 8px; padding: 7px 10px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; font-family: inherit; font-size: 12.5px; color: var(--text); outline: none; }
.jv-ask-other:focus { border-color: var(--blue); }
.jv-ask-foot { display: flex; align-items: center; gap: 10px; margin-top: 14px; }
.jv-ask-submit { padding: 8px 16px; background: var(--blue); border: 1px solid var(--blue); border-radius: 8px; font-family: inherit; font-size: 13px; font-weight: 600; color: #fff; cursor: pointer; transition: opacity .12s; }
.jv-ask-submit:hover { opacity: .9; }
.jv-ask-submit:disabled { opacity: .45; cursor: default; }
.jv-ask-hint { font-size: 11.5px; color: var(--text-3); }
/* scrollable record cards (alternative to a wide table) */
.jv-cards { margin-top: 12px; }
.jv-cards-title { font-size: 12px; font-weight: 600; color: var(--text-2); margin-bottom: 8px; }
.jv-cards-strip { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 6px; scroll-snap-type: x proximity; }
.jv-cards-strip::-webkit-scrollbar { height: 7px; }
.jv-cards-strip::-webkit-scrollbar-thumb { background: var(--border-2); border-radius: 99px; }
.jv-card { flex: none; width: 210px; scroll-snap-align: start; box-sizing: border-box; padding: 12px; background: var(--surface-1); border: 1px solid var(--border); border-radius: 11px; }
.jv-card-title { display: block; font-size: 13.5px; font-weight: 600; color: var(--text); margin-bottom: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jv-card-link { color: var(--blue); text-decoration: none; }
.jv-card-link:hover { text-decoration: underline; }
.jv-card-sub { font-size: 11.5px; color: var(--text-3); margin-bottom: 9px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jv-card-field { display: flex; justify-content: space-between; gap: 8px; padding: 4px 0; border-top: 1px solid var(--border); font-size: 12px; }
.jv-card-field:first-of-type { border-top: 0; }
.jv-card-k { color: var(--text-3); flex: none; }
.jv-card-v { color: var(--text); font-weight: 500; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* reusable toast notifier (delete confirmations, "no data", any status) */
.jv-notes { position: absolute; top: 16px; left: 50%; transform: translateX(-50%); z-index: 90; display: flex; flex-direction: column; gap: 8px; align-items: center; pointer-events: none; }
.jv-note { pointer-events: auto; display: flex; align-items: center; gap: 10px; min-width: 220px; max-width: 400px; padding: 10px 12px; background: var(--surface); border: 1px solid var(--border-2); border-radius: 11px; box-shadow: 0 10px 30px rgba(20, 20, 30, .18); }
.jv-note-ic { flex: none; width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: #fff; }
.jv-note.success .jv-note-ic { background: var(--green); }
.jv-note.error .jv-note-ic { background: var(--red); }
.jv-note.info .jv-note-ic { background: var(--blue); }
.jv-note-body { min-width: 0; flex: 1; }
.jv-note-title { font-size: 12px; font-weight: 650; color: var(--text); }
.jv-note-msg { font-size: 13px; color: var(--text); }
.jv-note-x { flex: none; width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; background: transparent; border: none; border-radius: 6px; color: var(--text-3); cursor: pointer; }
.jv-note-x:hover { background: var(--surface-2); color: var(--text); }
.jv-note-enter-active, .jv-note-leave-active { transition: opacity .18s ease, transform .18s ease; }
.jv-note-enter-from, .jv-note-leave-to { opacity: 0; transform: translateY(-8px); }

/* reusable confirm dialog (replaces window.confirm) */
.jv-cdialog { width: 400px; max-width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 20px; box-shadow: 0 24px 70px rgba(20, 20, 30, .28); animation: jv-popin .16s ease; }
.jv-cdialog-title { font-size: 16px; font-weight: 650; color: var(--text); }
.jv-cdialog-msg { margin-top: 8px; font-size: 13.5px; line-height: 1.5; color: var(--text-2); }
.jv-cdialog-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }

/* proactive message toast */
.jv-toast { position: absolute; right: 20px; bottom: 22px; z-index: 70; display: flex; align-items: center; gap: 11px; width: 360px; max-width: calc(100% - 40px); padding: 13px 14px; background: var(--surface); border: 1px solid var(--border-2); border-radius: 13px; box-shadow: 0 12px 32px rgba(20, 20, 30, .22); cursor: pointer; }
.jv-toast-ic { flex: none; width: 30px; height: 30px; border-radius: 8px; background: var(--blue); display: flex; align-items: center; justify-content: center; }
.jv-toast-title { font-size: 13px; font-weight: 600; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jv-toast-preview { font-size: 12px; color: var(--text-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jv-toast-open { flex: none; padding: 6px 12px; background: var(--blue); border: 1px solid var(--blue); border-radius: 7px; font-family: inherit; font-size: 12px; font-weight: 600; color: #fff; cursor: pointer; }
.jv-toast-x { flex: none; width: 26px; height: 26px; display: flex; align-items: center; justify-content: center; background: transparent; border: none; border-radius: 6px; color: var(--text-3); cursor: pointer; }
.jv-toast-x:hover { background: var(--surface-2); color: var(--text); }

/* ===== Macros ===== */
/* list rows */
.jv-macro-sub { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-3); margin-top: 2px; }
.jv-macro-sched { display: inline-flex; align-items: center; gap: 4px; padding: 1px 7px; background: var(--blue-bg); color: var(--blue); border-radius: 99px; font-size: 10.5px; font-weight: 600; text-transform: capitalize; }
/* editor step rows */
.jv-macro-sched-fields { display: flex; gap: 12px; margin: 8px 0 4px; }
/* macro per-STEP skill tagging: compact pill multi-select under each prompt */
.jv-macro-step-skills { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 8px; }
.jv-macro-step-skills-l { display: inline-flex; align-items: center; gap: 4px; font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); margin-right: 2px; }
.jv-macro-skill-opt { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 999px; border: 1px solid var(--border-2); background: var(--surface); color: var(--text-2); font-family: ui-monospace, Menlo, monospace; font-size: 12px; font-weight: 500; cursor: pointer; transition: border-color .12s, background .12s, color .12s, box-shadow .12s; }
.jv-macro-skill-opt--sm { padding: 3px 9px; font-size: 11px; gap: 4px; }
.jv-macro-skill-opt:hover { border-color: var(--blue); color: var(--text); }
.jv-macro-skill-opt.on { background: var(--blue-bg); border-color: var(--blue-bd); color: var(--blue); box-shadow: 0 1px 2px rgba(20, 20, 30, .06); }
.jv-macro-skill-shared { font-family: 'Inter', system-ui, sans-serif; font-size: 9.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; padding: 1px 6px; border-radius: 999px; background: var(--amber-bg); color: var(--amber); border: 1px solid var(--amber-bd); }
.jv-macro-step { border: 1px solid var(--border); border-radius: 11px; padding: 10px; margin-top: 10px; background: var(--surface-1); transition: border-color .12s, box-shadow .12s, opacity .12s, transform .12s; }
.jv-macro-step.dragging { opacity: .45; }
.jv-macro-step.dragover { border-color: var(--blue); box-shadow: 0 0 0 3px var(--blue-bg); }
.jv-macro-step-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.jv-macro-grip { flex: none; display: flex; align-items: center; justify-content: center; width: 22px; height: 26px; color: var(--text-3); cursor: grab; border-radius: 6px; transition: background .12s, color .12s; }
.jv-macro-grip:hover { color: var(--text); background: var(--surface-2); }
.jv-macro-grip:active { cursor: grabbing; }
.jv-macro-step-num { flex: none; width: 20px; height: 20px; border-radius: 99px; background: var(--blue-bg); color: var(--blue); font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
.jv-macro-step-label { flex: 1; }
.jv-macro-step .jv-iconbtn:disabled { opacity: .35; cursor: default; }
/* progress banner */
.jv-macrobar { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border: 1px solid var(--blue); background: var(--blue-bg); border-radius: 11px; }
.jv-macrobar.ok { border-color: var(--green); background: var(--green-bg); }
.jv-macrobar.err { border-color: var(--red-bd); background: var(--red-bg); }
.jv-macrobar.stopped { border-color: var(--border-2); background: var(--surface-1); }
.jv-macrobar-dot { width: 11px; height: 11px; flex: none; border-radius: 99px; background: var(--blue); }
.jv-macrobar-dot.spin { border: 2px solid var(--border-2); border-top-color: var(--blue); background: transparent; animation: jv-spin .7s linear infinite; }
.jv-macrobar-txt { flex: 1; min-width: 0; font-size: 13px; font-weight: 550; color: var(--text); }
.jv-macrobar-stop { flex: none; padding: 6px 14px; background: var(--surface); border: 1px solid var(--border-2); border-radius: 7px; font-family: inherit; font-size: 12.5px; font-weight: 600; color: var(--text-2); cursor: pointer; }
.jv-macrobar-stop:hover { background: var(--red); border-color: var(--red); color: #fff; }
.jv-macrobar-chip { font-size: 13px; font-weight: 600; color: var(--text); }
/* save-as-macro card (in a message) */
.jv-macrocard { display: flex; align-items: center; gap: 11px; margin-top: 12px; padding: 11px 12px; border: 1px solid var(--border); background: var(--surface-1); border-radius: 11px; }
.jv-macrocard-ic { flex: none; width: 34px; height: 34px; border-radius: 8px; display: flex; align-items: center; justify-content: center; background: var(--blue-bg); color: var(--blue); }
.jv-macrocard-txt { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.jv-macrocard-title { font-size: 13px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.jv-macrocard-sub { font-size: 11.5px; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.jv-macrocard-btn { flex: none; padding: 7px 13px; background: var(--blue); border: 1px solid var(--blue); border-radius: 8px; font-family: inherit; font-size: 12.5px; font-weight: 600; color: #fff; cursor: pointer; transition: opacity .12s; }
.jv-macrocard-btn:hover { opacity: .9; }
/* --- macro merge review --- */
.jv-merge-modal { width: min(640px, 92vw); background: var(--surface); border: 1px solid var(--border-2); border-radius: 13px; padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }
.jv-merge-head { display: flex; align-items: center; gap: 10px; }
.jv-merge-head b { font-size: 15px; }
.jv-merge-head .jv-art-close { margin-left: auto; }
.jv-merge-pending { color: var(--text-2); display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 0; }
.jv-merge-sub { flex-basis: 100%; font-size: 12px; color: var(--text-3); }
.jv-merge-spin { width: 14px; height: 14px; border: 2px solid var(--border-2); border-top-color: var(--blue); border-radius: 50%; animation: jv-spin 0.9s linear infinite; }
.jv-merge-deps { display: flex; gap: 6px; flex-wrap: wrap; }
.jv-merge-chip { font-size: 11px; font-weight: 600; color: var(--blue); background: var(--blue-bg); border: 1px solid var(--blue-bd); border-radius: 99px; padding: 3px 9px; }
.jv-merge-text { width: 100%; box-sizing: border-box; background: var(--surface-1); border: 1px solid var(--border-2); border-radius: 9px; color: var(--text); padding: 10px 12px; font-size: 13.5px; line-height: 1.5; resize: vertical; }
.jv-merge-keep { color: var(--text-2); background: var(--surface-1); border: 1px solid var(--border); border-radius: 9px; padding: 12px 14px; }
.jv-merge-foot { display: flex; gap: 10px; align-items: center; }
.jv-merge-notice { position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%); z-index: 60; background: var(--surface-2); border: 1px solid var(--border-2); color: var(--text); border-radius: 99px; padding: 9px 16px; font-size: 13px; box-shadow: 0 8px 28px rgba(0,0,0,.35); }

/* rich action cards (doc confirm / email draft) */
/* .jv-action must stay overflow:visible — the edit form's Link dropdown
   (.jv-action-linkmenu, position:absolute) would be CLIPPED to the card
   otherwise, leaving a sliver you have to scroll inside. The rounded corners
   are preserved by rounding the footer's own bottom edge instead. */
.jv-action, .jv-email { margin-top: 12px; border: 1px solid var(--border); border-radius: 11px; background: var(--surface); }
.jv-email { overflow: hidden; }
.jv-action-foot { border-radius: 0 0 10px 10px; }
.jv-action-head { display: flex; align-items: center; gap: 8px; padding: 11px 14px; border-bottom: 1px solid var(--border); }
.jv-action-head svg { flex: none; }
.jv-action-title { font-size: 13px; font-weight: 600; color: var(--text); }
.jv-action-title b { font-weight: 700; }
.jv-action-fields { padding: 4px 0; }
.jv-action-row { display: flex; gap: 12px; padding: 6px 14px; font-size: 13px; }
.jv-action-row:not(:last-child) { border-bottom: 1px solid var(--surface-2); }
.jv-action-k { flex: none; width: 140px; color: var(--text-3); font-family: ui-monospace, Menlo, monospace; font-size: 12px; }
.jv-action-v { flex: 1; min-width: 0; color: var(--text); word-break: break-word; }
.jv-action-editrow { display: flex; align-items: flex-start; gap: 12px; padding: 7px 14px; }
.jv-action-editrow > .jv-action-k { padding-top: 7px; }
.jv-action-ctl { flex: 1; min-width: 0; position: relative; }
.jv-action-input { width: 100%; box-sizing: border-box; font-family: inherit; font-size: 13px; line-height: 1.45; color: var(--text); background: var(--surface); border: 1px solid var(--border-2); border-radius: 7px; padding: 6px 9px; outline: none; resize: vertical; transition: border-color .12s, box-shadow .12s; }
.jv-action-input:focus { border-color: var(--blue); box-shadow: 0 0 0 3px var(--blue-bg); }
.jv-action-sel { cursor: pointer; appearance: auto; }
.jv-action-link { position: relative; }
.jv-action-linkmenu { position: absolute; left: 0; right: 0; top: calc(100% + 4px); z-index: 20; background: var(--surface); border: 1px solid var(--border-2); border-radius: 9px; box-shadow: 0 8px 24px rgba(20, 20, 30, .14); padding: 4px; max-height: 220px; overflow-y: auto; }
.jv-action-linkmenu.up { top: auto; bottom: calc(100% + 4px); box-shadow: 0 -8px 24px rgba(20, 20, 30, .14); }
.jv-action-linkmenu button { display: block; width: 100%; text-align: left; padding: 7px 9px; background: transparent; border: none; border-radius: 6px; font-family: inherit; font-size: 12.5px; color: var(--text-2); cursor: pointer; }
.jv-action-linkmenu button:hover { background: var(--surface-2); color: var(--text); }
.jv-action-editrow.changed .jv-action-input { border-color: var(--blue); }
.jv-action-editrow.changed > .jv-action-k { color: var(--blue); font-weight: 600; }
.jv-action-edithint { padding: 2px 14px 8px; font-size: 11.5px; color: var(--text-3); line-height: 1.4; }
.jv-action-foot { display: flex; align-items: center; gap: 8px; padding: 11px 14px; border-top: 1px solid var(--border); background: var(--surface-1); }
.jv-action-primary { display: inline-flex; align-items: center; gap: 7px; font-family: inherit; font-size: 13px; font-weight: 600; padding: 8px 14px; border-radius: 8px; cursor: pointer; background: var(--blue); color: #fff; border: 1px solid var(--blue); }
.jv-action-primary:hover { background: var(--text); color: var(--surface); border-color: var(--text); }
.jv-action-2nd { display: inline-flex; align-items: center; gap: 7px; font-family: inherit; font-size: 13px; font-weight: 550; padding: 8px 13px; border-radius: 8px; cursor: pointer; background: var(--surface); color: var(--text-2); border: 1px solid var(--border-2); }
.jv-action-2nd:hover { background: var(--text); color: var(--surface); border-color: var(--text); }
/* Dark mode: a black hover is invisible on the dark surface and the invert
   would flash a stark white button, so neutral buttons get a subtle elevated
   grey hover and primaries keep their colour (just brighter). */
.jv-dark .jv-iconbtn:hover,
.jv-dark .jv-iconbtn-bd:hover,
.jv-dark .jv-artifact-head .jv-iconbtn:hover,
.jv-dark .jv-modelpill:hover,
.jv-dark .jv-confirm-no:hover,
.jv-dark .jv-action-2nd:hover { background: var(--surface-3) !important; color: var(--text) !important; border-color: var(--border-2) !important; }
.jv-dark .jv-iconbtn:hover svg,
.jv-dark .jv-iconbtn-bd:hover svg,
.jv-dark .jv-modelpill:hover svg { stroke: var(--text) !important; }
.jv-dark .jv-modelpill:hover span { color: var(--text) !important; }
.jv-dark .jv-newchat:hover,
.jv-dark .jv-sendbtn:hover:not(:disabled),
.jv-dark .jv-confirm-yes:hover,
.jv-dark .jv-action-primary:hover { background: var(--blue) !important; color: #fff !important; border-color: var(--blue) !important; filter: brightness(1.18); }
.jv-dark .jv-newchat:hover svg,
.jv-dark .jv-sendbtn:hover:not(:disabled) svg { stroke: #fff !important; }
.jv-action-discard { margin-left: auto; display: inline-flex; align-items: center; gap: 6px; font-family: inherit; font-size: 12.5px; font-weight: 600; padding: 8px 13px; border-radius: 8px; border: 1px solid var(--red-bd); background: var(--red-bg); color: var(--red); cursor: pointer; transition: background .12s, color .12s, border-color .12s; }
.jv-action-discard:hover { background: var(--red); color: #fff; border-color: var(--red); }
.jv-action-discard:hover svg { stroke: #fff; }
.jv-email-head { padding: 12px 14px 6px; }
.jv-email-line { display: flex; gap: 10px; font-size: 13px; padding: 2px 0; }
.jv-email-k { flex: none; width: 54px; color: var(--text-3); }
.jv-email-v { color: var(--text-2); word-break: break-word; }
.jv-email-subj { color: var(--text); font-weight: 600; }
.jv-email-body { padding: 12px 14px 14px; font-size: 13px; line-height: 1.6; color: var(--text); white-space: pre-wrap; word-break: break-word; border-top: 1px solid var(--surface-2); }

/* --- record draft panel --- */
.jv-draft-chip { display: inline-flex; align-items: center; gap: 9px; margin-top: 12px; padding: 10px 14px; border: 1px solid var(--blue-bd); background: var(--blue-bg); color: var(--text); border-radius: 11px; cursor: pointer; font-size: 13.5px; }
.jv-draft-chip svg { color: var(--blue); flex: none; }
.jv-draft-chip-cta { color: var(--blue); font-weight: 600; margin-left: 4px; }
.jv-draft-panel { display: flex; flex-direction: column; }
.jv-draft-badge { font-size: 10px; font-weight: 650; letter-spacing: .08em; text-transform: uppercase; color: var(--amber); background: var(--amber-bg); border: 1px solid var(--amber-bd); border-radius: 99px; padding: 3px 9px; margin-left: 8px; }
.jv-draft-body { flex: 1; overflow-y: auto; padding: 14px 16px; display: flex; flex-direction: column; gap: 14px; }
.jv-draft-toast { font-size: 12px; color: var(--blue); background: var(--blue-bg); border: 1px solid var(--blue-bd); border-radius: 8px; padding: 7px 11px; }
.jv-draft-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 12px; }
.jv-draft-fld label { display: block; font-size: 10.5px; font-weight: 650; letter-spacing: .06em; text-transform: uppercase; color: var(--text-3); margin-bottom: 4px; }
.jv-draft-fld .jv-req { color: var(--red); }
.jv-draft-fld.missing .jv-action-input { border-color: var(--amber-bd); }
.jv-draft-fld.changed .jv-action-input { border-color: var(--blue-bd); background: var(--blue-bg); }
.jv-draft-ctl { position: relative; }
.jv-draft-table-title { font-size: 12px; font-weight: 650; color: var(--text-2); margin-bottom: 6px; }
.jv-draft-gridwrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 9px; }
.jv-grid { width: 100%; border-collapse: collapse; font-size: 13px; }
.jv-grid th { font-size: 10.5px; font-weight: 650; letter-spacing: .05em; text-transform: uppercase; color: var(--text-3); text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--border-2); background: var(--surface-1); }
.jv-grid td { padding: 5px 6px; border-bottom: 1px solid var(--border); position: relative; min-width: 90px; }
.jv-grid td .jv-action-input { width: 100%; box-sizing: border-box; }
.jv-grid-ro { color: var(--text-3); }
.jv-grid-x { width: 30px; }
.jv-grid-del { background: none; border: none; color: var(--text-3); cursor: pointer; padding: 4px 6px; border-radius: 6px; }
.jv-grid-del:hover { color: var(--red); background: var(--red-bg); }
.jv-draft-addrow { align-self: flex-start; margin-top: 8px; background: none; border: none; color: var(--blue); font-weight: 600; font-size: 12.5px; cursor: pointer; padding: 4px 2px; }
.jv-draft-totals { font-size: 12.5px; color: var(--text-2); font-variant-numeric: tabular-nums; }
.jv-draft-est { color: var(--text-3); font-size: 11px; }
.jv-draft-error { font-size: 12.5px; color: var(--red); background: var(--red-bg); border: 1px solid var(--red-bd); border-radius: 8px; padding: 8px 11px; white-space: pre-wrap; }
.jv-draft-foot { display: flex; gap: 10px; align-items: center; padding: 12px 16px; border-top: 1px solid var(--border); }
@media (max-width: 700px) { .jv-draft-fields { grid-template-columns: 1fr; } }

/* artifact preview panel (right side-over) */
/* premium artifact-preview header actions (replaces the boxy .jv-iconbtn look) */
.jv-art-act, .jv-art-close { flex: none; width: 32px; height: 32px; display: inline-flex; align-items: center; justify-content: center; border-radius: 9px; border: 1px solid transparent; background: transparent; color: var(--text-3); cursor: pointer; text-decoration: none; transition: background .15s ease, color .15s ease, border-color .15s ease, transform .15s ease, box-shadow .15s ease; }
.jv-art-act svg, .jv-art-close svg { transition: transform .2s cubic-bezier(.34, 1.56, .64, 1); }
.jv-art-act:hover { background: var(--surface-2); border-color: var(--border); color: var(--text); transform: translateY(-1px); box-shadow: 0 4px 12px rgba(20, 20, 30, .10); }
.jv-art-act:active { transform: translateY(0) scale(.94); }
.jv-art-divider { flex: none; width: 1px; height: 18px; margin: 0 3px; background: var(--border); border-radius: 1px; }
.jv-art-close { border-radius: 50%; }
.jv-art-close:hover { background: var(--red-bg); border-color: var(--red-bd); color: var(--red); box-shadow: 0 4px 12px rgba(220, 38, 38, .14); }
.jv-art-close:hover svg { transform: rotate(90deg); }
.jv-art-close:active { transform: scale(.9); }
.jv-artifact-panel:focus { outline: none; }
.jv-artifact-overlay { position: absolute; inset: 0; z-index: 60; background: rgba(15, 15, 22, 0.32); display: flex; justify-content: flex-end; }
.jv-dark .jv-artifact-overlay { background: rgba(0, 0, 0, 0.5); }
.jv-artifact-panel { width: min(720px, 82%); height: 100%; background: var(--surface); border-left: 1px solid var(--border); display: flex; flex-direction: column; box-shadow: -14px 0 44px rgba(20, 20, 30, 0.14); }
.jv-artifact-head { display: flex; align-items: center; gap: 9px; padding: 11px 12px 11px 14px; border-bottom: 1px solid var(--border); flex: none; }
.jv-artifact-head svg { color: var(--text-3); flex: none; }
.jv-artifact-head-title { font-size: 14px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; min-width: 0; }
.jv-artifact-head .jv-iconbtn:hover { background: var(--text) !important; color: var(--surface) !important; }
.jv-artifact-body { flex: 1; min-height: 0; overflow: auto; background: var(--surface-1); display: flex; flex-direction: column; }
.jv-artifact-frame { flex: 1; width: 100%; border: 0; background: #fff; }
/* Dark preview: the frame behind html/svg srcdoc follows the app surface (the
   srcdoc itself is themed by get_canvas's dark param); PDFs keep the white
   frame — pages are white paper either way. */
.jv-dark .jv-artifact-frame:not([title="PDF preview"]) { background: var(--surface-1); }
.jv-artifact-img { max-width: 100%; height: auto; margin: auto; padding: 16px; }
.jv-artifact-text { margin: 0; padding: 16px; font-size: 12.5px; line-height: 1.55; white-space: pre-wrap; word-break: break-word; color: var(--text); font-family: ui-monospace, "SF Mono", Menlo, monospace; }
.jv-artifact-loading, .jv-artifact-nopreview { margin: auto; padding: 30px; text-align: center; color: var(--text-3); font-size: 13px; display: flex; flex-direction: column; gap: 12px; align-items: center; }
.jv-sheet-tabs { display: flex; gap: 4px; padding: 8px 10px; border-bottom: 1px solid var(--border); background: var(--surface); flex: none; overflow-x: auto; }
.jv-sheet-tabs button { font-family: inherit; font-size: 12px; padding: 4px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-1); color: var(--text-2); cursor: pointer; white-space: nowrap; }
.jv-sheet-tabs button.on { background: var(--blue); color: #fff; border-color: var(--blue); }
.jv-sheet-scroll { flex: 1; min-height: 0; overflow: auto; }
.jv-sheet { border-collapse: collapse; font-size: 12.5px; width: max-content; min-width: 100%; }
.jv-sheet th, .jv-sheet td { border: 1px solid var(--border); padding: 6px 10px; text-align: left; white-space: nowrap; }
.jv-sheet th { background: var(--surface-2); font-weight: 600; color: var(--text); position: sticky; top: 0; z-index: 1; }
.jv-sheet td { color: var(--text-2); }
.jv-sheet tbody tr:nth-child(even) td { background: var(--surface); }

.jv-slide-enter-active, .jv-slide-leave-active { transition: opacity .18s ease; }
.jv-slide-enter-active .jv-artifact-panel, .jv-slide-leave-active .jv-artifact-panel { transition: transform .24s cubic-bezier(.4, 0, .2, 1); }
.jv-slide-enter-from, .jv-slide-leave-to { opacity: 0; }
.jv-slide-enter-from .jv-artifact-panel, .jv-slide-leave-to .jv-artifact-panel { transform: translateX(100%); }
</style>
