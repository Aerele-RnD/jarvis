<template>
	<div class="jv-settings-body">
		<div style="font-size: 12px; color: var(--text-3); margin: 0 0 14px">
			Speed up the composer and chat.
		</div>
		<div class="jv-set-sec">Composer</div>
		<div class="jv-kbd-row">
			<span>Recall previous / next prompt</span
			><span><kbd class="jv-kbd">↑</kbd><kbd class="jv-kbd">↓</kbd></span>
		</div>
		<div class="jv-kbd-row"><span>Send message</span><kbd class="jv-kbd">Enter</kbd></div>
		<div class="jv-kbd-row">
			<span>New line</span
			><span
				><kbd class="jv-kbd">Shift</kbd><span class="jv-kbd-plus">+</span
				><kbd class="jv-kbd">Enter</kbd></span
			>
		</div>
		<div class="jv-kbd-row">
			<span>Mention a doctype / record</span><kbd class="jv-kbd">@</kbd>
		</div>
		<div class="jv-set-sec" style="margin-top: 20px">Chat</div>
		<div class="jv-kbd-row">
			<span>New chat</span
			><span
				><kbd class="jv-kbd">Ctrl</kbd><span class="jv-kbd-plus">+</span
				><kbd class="jv-kbd">Shift</kbd><span class="jv-kbd-plus">+</span
				><kbd class="jv-kbd">O</kbd></span
			>
		</div>
		<div class="jv-kbd-row">
			<span>Toggle sidebar</span
			><span
				><kbd class="jv-kbd">Ctrl</kbd><span class="jv-kbd-plus">+</span
				><kbd class="jv-kbd">B</kbd></span
			>
		</div>
		<div class="jv-kbd-row">
			<span>Close panel / cancel</span><kbd class="jv-kbd">Esc</kbd>
		</div>
		<div class="jv-set-hint" style="margin-top: 14px">
			Tip: <kbd class="jv-kbd">↑</kbd> at the start of an empty composer walks back through
			your earlier prompts in this chat.
		</div>
	</div>
</template>

<script setup></script>
