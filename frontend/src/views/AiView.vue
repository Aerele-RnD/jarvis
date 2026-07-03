<template>
  <div class="jv-root" :class="{ 'jv-dark': dark }" :style="paletteVars"
       style="--rad:8px;font-family:'Inter',system-ui,sans-serif;min-height:100vh;color:var(--text);background:var(--surface);">

    <!-- Header with tab strip -->
    <header style="height:52px;display:flex;align-items:center;gap:14px;padding:0 18px;border-bottom:1px solid var(--border);">
      <router-link to="/" style="color:var(--text-2);text-decoration:none;font-size:13px;">← Chat</router-link>
      <span style="font-size:14px;font-weight:600;">AI / Models</span>
      <nav style="margin-left:12px;display:flex;gap:4px;">
        <button v-for="t in ['manage','monitor']" :key="t" @click="activeTab=t"
          :style="{fontSize:'13px',padding:'6px 12px',border:'none',cursor:'pointer',background:'transparent',
                   borderBottom: activeTab===t ? '2px solid var(--blue)' : '2px solid transparent',
                   color: activeTab===t ? 'var(--text)' : 'var(--text-3)'}">{{ t[0].toUpperCase()+t.slice(1) }}</button>
      </nav>
      <button @click="toggleTheme" :title="dark ? 'Switch to light theme' : 'Switch to dark theme'"
              style="margin-left:auto;width:32px;height:32px;display:flex;align-items:center;justify-content:center;background:var(--surface);border:1px solid var(--border);border-radius:7px;cursor:pointer;flex:none;">
        <svg v-if="dark" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
        <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
      </button>
    </header>

    <!-- Manage tab: the shared LLM-pool editor (extracted to a reusable component) -->
    <main v-show="activeTab==='manage'" style="max-width:760px;margin:0 auto;padding:22px 18px;">
      <LlmPoolEditor :editable="true" />
    </main>

    <!-- Monitor tab -->
    <main v-show="activeTab==='monitor'" style="max-width:900px;margin:0 auto;padding:22px 18px;">
      <MonitorTab :dark="dark" />
    </main>
  </div>
</template>

<script setup>
import { ref } from "vue"
import { useTheme } from "@/composables/useTheme"
import LlmPoolEditor from "@/components/LlmPoolEditor.vue"
import MonitorTab from "@/views/MonitorTab.vue"

// Theme — shared composable: honours "jarvis-theme" pref, cross-tab sync, OS live.
const { effectiveDark: dark, paletteVars, toggleTheme } = useTheme()

const activeTab = ref("manage")
</script>
