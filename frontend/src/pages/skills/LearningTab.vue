<template>
	<div class="flex h-full flex-col overflow-hidden">
		<LayoutHeader>
			<template #left-header>
				<Breadcrumbs
					:items="[
						{ label: 'Skills', route: { name: 'SkillsList' } },
						{ label: 'Learning' },
					]"
				/>
			</template>
			<template #right-header>
				<Button
					v-if="!selfHosted"
					icon="refresh-cw"
					variant="ghost"
					:tooltip="'Refresh'"
					:loading="board.loading"
					@click="reloadAll"
				/>
			</template>
		</LayoutHeader>

		<!-- self-host: feature fully disabled (plan §13.3 / §7 T5) -->
		<div
			v-if="selfHosted"
			class="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center"
		>
			<FeatherIcon name="cloud-off" class="size-8 text-ink-gray-5" />
			<span class="text-lg font-medium text-ink-gray-8">
				Behavioural learning is available on managed plans
			</span>
			<span class="max-w-md text-p-base text-ink-gray-6">
				Pattern learning mines this site's history into reviewable defaults. It runs only on
				Jarvis-managed benches and is disabled on self-hosted installs.
			</span>
		</div>

		<div v-else class="min-h-0 flex-1 overflow-y-auto">
			<div class="mx-auto flex w-full max-w-4xl flex-col gap-5 px-5 py-5">
				<!-- ══════════════ Settings ══════════════ -->
				<section class="rounded-lg border p-4">
					<div class="flex items-start justify-between gap-3">
						<div>
							<div class="text-base font-semibold text-ink-gray-9">Behavioural learning</div>
							<div class="mt-0.5 text-sm text-ink-gray-6">
								Analyse this site's history overnight and propose learned defaults for review.
							</div>
						</div>
						<Switch v-model="settings.pattern_learning_enabled" size="md" />
					</div>

					<div class="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
						<FormControl
							type="time"
							label="Window start"
							:modelValue="settings.pattern_window_start"
							@update:modelValue="(v) => (settings.pattern_window_start = v)"
						/>
						<FormControl
							type="time"
							label="Window end"
							:modelValue="settings.pattern_window_end"
							@update:modelValue="(v) => (settings.pattern_window_end = v)"
						/>
						<FormControl
							type="number"
							label="Max proposals / run"
							:modelValue="settings.pattern_max_proposals_per_run"
							@update:modelValue="(v) => (settings.pattern_max_proposals_per_run = v)"
						/>
					</div>
					<p class="mt-2 text-sm text-ink-gray-5">
						Analysis runs inside this daily window (at least one hour, site time). Approved
						patterns still need an explicit Apply before they reach your assistant.
					</p>

					<div class="mt-4 flex flex-wrap items-center gap-2">
						<Button
							variant="solid"
							label="Save settings"
							:loading="savingSettings"
							@click="saveSettings"
						/>
						<Button
							variant="subtle"
							label="Run first analysis now"
							iconLeft="play"
							:loading="runningNow"
							@click="runNow"
						/>
					</div>

					<!-- run status line: Enabled/Disabled is the ONLY pill; the run-status
					     Long Text is plain text (not a Badge); coverage note once. -->
					<div class="mt-4 flex flex-col gap-1.5 border-t pt-3 text-sm">
						<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
							<span class="text-ink-gray-5">Status:</span>
							<Badge
								variant="subtle"
								:theme="status.enabled ? 'green' : 'gray'"
								:label="status.enabled ? 'Enabled' : 'Disabled'"
							/>
							<template v-if="status.lastRunAt">
								<span class="text-ink-gray-4">·</span>
								<span class="text-ink-gray-6">Last run</span>
								<Tooltip :text="exactDate(status.lastRunAt)">
									<span class="text-ink-gray-8">{{ timeAgo(status.lastRunAt) }}</span>
								</Tooltip>
							</template>
							<template v-if="status.nextRunAt">
								<span class="text-ink-gray-4">·</span>
								<span class="text-ink-gray-6">Next run</span>
								<Tooltip :text="exactDate(status.nextRunAt)">
									<span class="text-ink-gray-8">{{ timeAgo(status.nextRunAt) }}</span>
								</Tooltip>
							</template>
						</div>
						<div v-if="status.lastRunStatus" class="text-ink-gray-6">
							{{ status.lastRunStatus }}
						</div>
						<div v-if="coverageNote" class="text-ink-gray-5">
							{{ coverageNote }}
						</div>
					</div>
				</section>

				<!-- ══════════════ Apply bar ══════════════ -->
				<!-- Stays mounted while an apply is in flight (applyActive) even after
				     the pending count hits 0, so the SyncPill's push progress / failure
				     never unmounts mid-push. -->
				<div
					v-if="pendingApplyCount > 0 || applyActive"
					class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-outline-gray-2 bg-surface-gray-1 p-4"
				>
					<div class="flex items-center gap-2">
						<FeatherIcon name="upload-cloud" class="size-4 text-ink-gray-6" />
						<span v-if="pendingApplyCount > 0" class="text-base text-ink-gray-8">
							{{ pendingApplyCount }} approved change{{ pendingApplyCount === 1 ? "" : "s" }}
							pending
						</span>
						<span v-else class="text-base text-ink-gray-8">Applying learned skills</span>
						<!-- stale-but-still-pushed patterns leave the assistant on Apply (§6.5) -->
						<span v-if="staleRemovalCount > 0" class="text-sm text-ink-gray-6">
							· {{ staleRemovalCount }} stale pattern{{ staleRemovalCount === 1 ? "" : "s" }}
							will be removed
						</span>
						<SyncPill ref="syncPill" />
					</div>
					<Button
						v-if="pendingApplyCount > 0"
						variant="solid"
						label="Apply learned skills"
						iconLeft="upload-cloud"
						:loading="applyActive"
						@click="applyLearned"
					/>
				</div>

				<!-- ══════════════ Review board ══════════════ -->
				<section class="flex flex-col gap-3">
					<div class="flex flex-wrap items-center justify-between gap-2">
						<div class="text-base font-semibold text-ink-gray-9">Review board</div>
						<div class="w-44">
							<FormControl
								type="select"
								:options="STATUS_OPTIONS"
								:modelValue="boardStatus"
								@update:modelValue="setBoardStatus"
							/>
						</div>
					</div>

					<div
						v-if="reviewActivity.total"
						class="text-sm text-ink-gray-5"
					>
						{{ reviewActivity.decided }} of {{ reviewActivity.total }} decided<template
							v-if="reviewActivity.last_by_name"
						>
							· last by {{ reviewActivity.last_by_name }}</template
						>
					</div>

					<!-- domain facet chips (count-sorted by the server) -->
					<div class="flex flex-wrap items-center gap-2">
						<Button
							label="All domains"
							:variant="domain === '' ? 'solid' : 'subtle'"
							@click="setDomain('')"
						/>
						<Button
							v-for="f in facets"
							:key="f.value"
							:label="`${domainLabel(f.value)} · ${f.count}`"
							:variant="domain === f.value ? 'solid' : 'subtle'"
							@click="setDomain(f.value)"
						/>
					</div>

					<!-- batch-approve bar (A-class only) -->
					<div
						v-if="boardStatus === 'Proposed' && selectedNames.length"
						class="flex items-center justify-between gap-3 rounded-lg border border-outline-gray-2 bg-surface-gray-1 px-4 py-2"
					>
						<span class="text-sm text-ink-gray-7">
							{{ selectedNames.length }} aggregate-safe pattern{{
								selectedNames.length === 1 ? "" : "s"
							}}
							selected
						</span>
						<div class="flex items-center gap-2">
							<Button variant="ghost" label="Clear" @click="selected = new Set()" />
							<Button
								variant="solid"
								theme="green"
								label="Approve selected"
								:loading="acting === '__batch__'"
								@click="doBatchApprove"
							/>
						</div>
					</div>

					<!-- cards -->
					<div v-if="board.loading && !board.rows.length" class="py-10 text-center">
						<LoadingIndicator class="size-5 text-ink-gray-5" />
					</div>
					<div
						v-else-if="!board.rows.length"
						class="flex flex-col items-center gap-1 rounded-lg border border-dashed py-14 text-center"
					>
						<FeatherIcon name="inbox" class="size-7 text-ink-gray-5" />
						<span class="mt-1 text-base font-medium text-ink-gray-8">{{ emptyTitle }}</span>
						<span class="text-p-base text-ink-gray-6">{{ emptyDescription }}</span>
					</div>

					<div v-else class="flex flex-col gap-3">
						<div
							v-for="row in board.rows"
							:key="row.name"
							class="rounded-lg border p-4"
						>
							<!-- badges row -->
							<div class="flex flex-wrap items-center gap-1.5">
								<Checkbox
									v-if="boardStatus === 'Proposed' && row.effective_sensitivity === 'A'"
									:modelValue="selected.has(row.name)"
									@update:modelValue="() => toggleSelect(row)"
								/>
								<Badge
									variant="subtle"
									:theme="strengthTheme(row.strength_band)"
									:label="row.strength_band || 'Low'"
								/>
								<Badge variant="outline" theme="gray" :label="domainLabel(row.domain)" />
								<Badge v-if="row.company" variant="outline" theme="gray" :label="row.company" />
								<Badge
									variant="subtle"
									:theme="sensBadge(row).theme"
									:label="sensBadge(row).label"
								/>
								<Badge
									v-if="isAcknowledged(row)"
									variant="subtle"
									theme="gray"
									label="Acknowledged"
								/>
								<Badge
									v-else-if="boardStatus !== 'Proposed'"
									variant="subtle"
									:theme="STATUS_THEME[row.status] || 'gray'"
									:label="row.status"
								/>
								<!-- caveats -->
								<Tooltip v-if="row.has_overlap_warning" :text="row.overlap_warning">
									<Badge variant="subtle" theme="orange" label="Overlaps a custom skill" />
								</Tooltip>
								<Tooltip
									v-if="row.exceptions_cluster"
									:text="row.exceptions_cluster"
								>
									<Badge variant="subtle" theme="blue" label="Possible sub-rule" />
								</Tooltip>
								<Badge v-if="row.not_applicable" variant="subtle" theme="gray" label="Not applicable" />
								<Badge v-if="row.draft_edited" variant="subtle" theme="gray" label="Edited" />
								<!-- correction loop (§6.5): chat users flagged this default as wrong -->
								<Tooltip
									v-if="row.flags_count"
									:text="`Chat users flagged this default as wrong ${row.flags_count} time${row.flags_count === 1 ? '' : 's'}.`"
								>
									<Badge
										variant="subtle"
										theme="red"
										:label="`${row.flags_count} flag${row.flags_count === 1 ? '' : 's'}`"
									/>
								</Tooltip>
							</div>

							<!-- plain-English pattern sentence -->
							<p class="mt-2.5 text-base text-ink-gray-9">{{ row.pattern_statement }}</p>
							<div class="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-ink-gray-5">
								<span v-if="row.exception_n">
									{{ row.exception_n }} known exception{{ row.exception_n === 1 ? "" : "s" }}
								</span>
								<span v-if="row.approved_by">· Approved by {{ row.approved_by }}</span>
								<span v-else-if="row.reviewed_by">· Reviewed by {{ row.reviewed_by }}</span>
							</div>

							<!-- Stale banner (§6.5): drift re-validation found the habit no longer
							     holds. Never a silent edit: the SM re-approves (Approve) or rejects;
							     a still-pushed row is removed from the assistant on the next Apply. -->
							<div
								v-if="row.status === 'Stale'"
								class="mt-2.5 flex items-start gap-2 rounded-lg border border-outline-amber-2 bg-surface-amber-1 px-3 py-2 text-sm text-ink-amber-3"
							>
								<FeatherIcon name="trending-down" class="mt-0.5 size-4 shrink-0" />
								<span>
									{{ row.stale_reason || "This pattern no longer holds in recent data." }}
									<template v-if="row.materialized_skill">
										Still pushed to the assistant; it will be removed on the next Apply
										unless re-approved.
									</template>
								</span>
							</div>

							<!-- B-class exact-text disclosure banner (plan §6.6): learned skill
							     files are bench-global, so role scoping steers activation but is
							     not a confidentiality boundary. -->
							<div
								v-if="row.effective_sensitivity === 'B'"
								class="mt-2.5 flex items-start gap-2 rounded-lg border border-outline-amber-2 bg-surface-amber-1 px-3 py-2 text-sm text-ink-amber-3"
							>
								<FeatherIcon name="alert-triangle" class="mt-0.5 size-4 shrink-0" />
								<span>{{ disclosureText(bRoles(row)) }}</span>
							</div>

							<!-- drill-down toggle -->
							<button
								class="mt-2 flex items-center gap-1 text-sm text-ink-gray-6 hover:text-ink-gray-8"
								@click="toggleExpand(row.name)"
							>
								<FeatherIcon
									:name="expanded[row.name] ? 'chevron-down' : 'chevron-right'"
									class="size-3.5"
								/>
								Evidence &amp; details
							</button>

							<div v-if="expanded[row.name]" class="mt-3 border-t pt-3">
								<div v-if="expanded[row.name] === 'loading'" class="py-4 text-center">
									<LoadingIndicator class="size-4 text-ink-gray-5" />
								</div>
								<template v-else>
									<div
										v-if="expanded[row.name].frozen_evidence_label"
										class="mb-3 rounded border border-outline-gray-2 bg-surface-gray-1 px-3 py-2 text-sm text-ink-gray-6"
									>
										{{ expanded[row.name].frozen_evidence_label }}
									</div>

									<!-- raw stats -->
									<div class="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-3">
										<div>
											<span class="text-ink-gray-5">Confidence</span>
											<span class="ml-1.5 text-ink-gray-8">{{ pct(expanded[row.name].confidence_pct) }}</span>
										</div>
										<div>
											<span class="text-ink-gray-5">Support</span>
											<span class="ml-1.5 text-ink-gray-8">{{ expanded[row.name].support_n }} units</span>
										</div>
										<div>
											<span class="text-ink-gray-5">Rows</span>
											<span class="ml-1.5 text-ink-gray-8">{{ expanded[row.name].n_rows }}</span>
										</div>
										<div>
											<span class="text-ink-gray-5">Wilson low</span>
											<span class="ml-1.5 text-ink-gray-8">{{ pct(mul100(expanded[row.name].wilson_low)) }}</span>
										</div>
										<div>
											<span class="text-ink-gray-5">Gap vs base</span>
											<span class="ml-1.5 text-ink-gray-8">{{ pct(mul100(expanded[row.name].gap)) }}</span>
										</div>
										<div>
											<span class="text-ink-gray-5">Exceptions</span>
											<span class="ml-1.5 text-ink-gray-8">{{ expanded[row.name].exception_n }}</span>
										</div>
										<div v-if="expanded[row.name].last_validated_at">
											<span class="text-ink-gray-5">Last validated</span>
											<Tooltip :text="exactDate(expanded[row.name].last_validated_at)">
												<span class="ml-1.5 text-ink-gray-8">{{
													timeAgo(expanded[row.name].last_validated_at)
												}}</span>
											</Tooltip>
										</div>
									</div>

									<!-- role chips -->
									<div
										v-if="(expanded[row.name].roles || []).length"
										class="mt-3 flex flex-wrap items-center gap-1.5"
									>
										<span class="text-sm text-ink-gray-5">Roles:</span>
										<Badge
											v-for="r in expanded[row.name].roles"
											:key="r"
											variant="outline"
											theme="gray"
											:label="r"
										/>
									</div>

									<!-- compiled bullet preview -->
									<div v-if="expanded[row.name].compiled_preview" class="mt-3">
										<div class="mb-1 text-sm text-ink-gray-5">Compiled rule</div>
										<pre
											class="overflow-x-auto whitespace-pre-wrap rounded border bg-surface-gray-1 px-3 py-2 text-sm text-ink-gray-8"
										>{{ expanded[row.name].compiled_preview }}</pre>
									</div>

									<!-- known exceptions (SM may see named parties) + Desk links -->
									<div
										v-if="(expanded[row.name].exceptions || []).length"
										class="mt-3"
									>
										<div class="mb-1 text-sm text-ink-gray-5">Known exceptions</div>
										<div class="flex flex-wrap gap-1.5">
											<a
												v-for="(ex, i) in expanded[row.name].exceptions"
												:key="i"
												:href="exDeskUrl(ex)"
												:target="exDeskUrl(ex) ? '_blank' : undefined"
												rel="noopener"
												class="inline-flex items-center gap-1 rounded bg-surface-gray-2 px-2 py-0.5 text-sm text-ink-gray-8"
												:class="exDeskUrl(ex) ? 'hover:bg-surface-gray-3' : 'cursor-default'"
											>
												{{ exLabel(ex) }}
												<FeatherIcon
													v-if="exDeskUrl(ex)"
													name="external-link"
													class="size-3 text-ink-gray-5"
												/>
											</a>
										</div>
									</div>

									<!-- Desk links: runs + materialized skill -->
									<div class="mt-3 flex flex-wrap items-center gap-3 text-sm">
										<a
											v-if="expanded[row.name].last_seen_run"
											:href="deskUrl('Jarvis Pattern Run', expanded[row.name].last_seen_run)"
											target="_blank"
											rel="noopener"
											class="inline-flex items-center gap-1 text-ink-gray-7 hover:underline"
										>
											<FeatherIcon name="activity" class="size-3.5" />
											Run {{ expanded[row.name].last_seen_run }}
										</a>
										<a
											v-if="expanded[row.name].materialized_skill"
											:href="deskUrl('Jarvis Custom Skill', expanded[row.name].materialized_skill)"
											target="_blank"
											rel="noopener"
											class="inline-flex items-center gap-1 text-ink-gray-7 hover:underline"
										>
											<FeatherIcon name="zap" class="size-3.5" />
											{{ expanded[row.name].materialized_skill }}
										</a>
										<span class="text-ink-gray-4">{{ row.name }}</span>
									</div>
								</template>
							</div>

							<!-- actions -->
							<div class="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
								<template v-if="row.status === 'Proposed' || row.status === 'Stale'">
									<!-- A-class: approvable + compiled + pushed -->
									<template v-if="row.effective_sensitivity === 'A'">
										<Button
											variant="solid"
											theme="green"
											label="Approve"
											:loading="acting === row.name"
											:disabled="!!acting"
											@click="doApprove(row)"
										/>
										<Button
											variant="subtle"
											label="Edit &amp; approve"
											:disabled="!!acting"
											@click="openEdit(row)"
										/>
										<Dropdown
											v-if="row.status === 'Proposed'"
											:options="snoozeOptions(row)"
										>
											<Button variant="subtle" label="Snooze" iconRight="chevron-down" :disabled="!!acting" />
										</Dropdown>
										<Button
											variant="subtle"
											theme="red"
											label="Reject"
											:disabled="!!acting"
											@click="openReject(row)"
										/>
									</template>
									<!-- B/C: insight-only in Phase 1 (never compiled/pushed), so
									     Acknowledge (records reviewed) replaces Approve. "Apply to
									     skill…" (D5) folds the insight into an org custom skill via
									     an LLM-drafted, SM-confirmed update instead. -->
									<template v-else>
										<Button
											variant="subtle"
											label="Acknowledge (insight only)"
											:loading="acting === row.name"
											:disabled="!!acting"
											@click="doAcknowledge(row)"
										/>
										<Button
											variant="subtle"
											label="Apply to skill…"
											:disabled="!!acting"
											@click="openInsightApply(row)"
										/>
										<Dropdown
											v-if="row.status === 'Proposed'"
											:options="snoozeOptions(row)"
										>
											<Button variant="subtle" label="Snooze" iconRight="chevron-down" :disabled="!!acting" />
										</Dropdown>
										<Button
											variant="subtle"
											theme="red"
											label="Reject"
											:disabled="!!acting"
											@click="openReject(row)"
										/>
										<span class="text-sm text-ink-gray-5">
											Insight only in Phase 1: recorded as reviewed, not pushed to the assistant.
										</span>
									</template>
								</template>
								<template v-else-if="row.status === 'Approved'">
									<Button
										variant="subtle"
										label="Un-approve"
										:loading="acting === row.name"
										:disabled="!!acting"
										@click="doUnapprove(row)"
									/>
									<span
										v-if="row.effective_sensitivity !== 'A'"
										class="text-sm text-ink-gray-5"
									>
										Approved but insight-only: not pushed to the assistant.
									</span>
								</template>
								<template v-else-if="row.status === 'Rejected'">
									<span v-if="isAcknowledged(row)" class="text-sm text-ink-gray-5">
										Acknowledged as insight: reviewed, not pushed.
									</span>
									<Button
										variant="subtle"
										label="Restore"
										:loading="acting === row.name"
										:disabled="!!acting"
										@click="doRestore(row)"
									/>
								</template>
								<span v-else class="text-sm text-ink-gray-5">No actions available.</span>
							</div>
						</div>

						<div v-if="board.hasMore" class="flex justify-center pt-1">
							<Button variant="subtle" label="Load more" :loading="board.loading" @click="fetchBoard('more')" />
						</div>
					</div>

					<div
						v-if="boardStatus === 'Proposed' && queuedCount > 0"
						class="text-sm text-ink-gray-5"
					>
						{{ queuedCount }} more queued — not yet surfaced for review.
					</div>
				</section>
			</div>
		</div>

		<!-- Reject reason modal -->
		<Dialog
			v-model="rejectDialog.show"
			:options="{ title: 'Reject pattern', size: 'md' }"
		>
			<template #body-content>
				<p class="text-sm text-ink-gray-6">
					Rejected patterns are hidden but reversible — you can restore them from the Rejected
					filter later.
				</p>
				<FormControl
					type="textarea"
					class="mt-3"
					label="Reason"
					placeholder="Why is this not a habit worth teaching?"
					:modelValue="rejectDialog.reason"
					@update:modelValue="(v) => (rejectDialog.reason = v)"
				/>
			</template>
			<template #actions>
				<div class="flex items-center gap-2">
					<Button
						variant="solid"
						theme="red"
						label="Reject"
						:loading="acting === rejectDialog.name"
						@click="submitReject"
					/>
					<Button label="Cancel" @click="rejectDialog.show = false" />
				</div>
			</template>
		</Dialog>

		<!-- Edit-then-approve modal -->
		<Dialog
			v-model="editDialog.show"
			:options="{ title: 'Edit and approve', size: 'lg' }"
		>
			<template #body-content>
				<p class="text-sm text-ink-gray-6">
					Your edit is used verbatim in the compiled skill. The evidence line stays frozen — it
					still reflects the originally detected pattern, which was not re-measured.
				</p>
				<FormControl
					type="textarea"
					class="mt-3"
					label="Skill rule"
					:modelValue="editDialog.draft"
					:rows="8"
					@update:modelValue="(v) => (editDialog.draft = v)"
				/>
			</template>
			<template #actions>
				<div class="flex items-center gap-2">
					<Button
						variant="solid"
						theme="green"
						label="Approve with edits"
						:loading="acting === editDialog.name"
						@click="submitEdit"
					/>
					<Button label="Cancel" @click="editDialog.show = false" />
				</div>
			</template>
		</Dialog>

		<!-- Apply confirm modal: the restart warning is mandatory before Apply
		     proceeds; shows a live active-chat count when available and points to
		     tonight's quiet window as an alternative. -->
		<Dialog v-model="applyDialog.show" :options="{ title: 'Apply learned skills?', size: 'md' }">
			<template #body-content>
				<div class="flex flex-col gap-3 text-sm">
					<div
						class="flex items-start gap-2 rounded-lg border border-outline-amber-2 bg-surface-amber-1 px-3 py-2 text-ink-amber-3"
					>
						<FeatherIcon name="alert-triangle" class="mt-0.5 size-4 shrink-0" />
						<span>
							Applying restarts the assistant for everyone for up to ~3 min. Active chats may
							be briefly interrupted.
						</span>
					</div>
					<p class="text-ink-gray-6">
						Recompiles approved patterns into the learned-&lt;domain&gt; skills and pushes them
						to your assistant. Only A-class (aggregate-safe) patterns are compiled; B and C
						insights are never pushed.
					</p>
					<p v-if="activeChatCount != null" class="text-ink-gray-7">
						{{ activeChatCount }} chat{{ activeChatCount === 1 ? "" : "s" }} active right now.
					</p>
					<p v-if="status.nextRunAt" class="text-ink-gray-5">
						Prefer off-hours? Cancel and apply during a quiet period (next analysis window
						{{ timeAgo(status.nextRunAt) }}).
					</p>
				</div>
			</template>
			<template #actions>
				<div class="flex items-center gap-2">
					<Button
						variant="solid"
						label="Apply now"
						iconLeft="upload-cloud"
						:loading="applyActive"
						@click="confirmApply"
					/>
					<Button label="Cancel" @click="applyDialog.show = false" />
				</div>
			</template>
		</Dialog>

		<!-- Apply-insight-to-skill modal (D5): self-contained — drafts an LLM
		     skill update for a B/C insight and applies it on confirm (the server
		     marks the pattern acknowledged with an applied-to-skill note); the
		     board only opens it and refreshes on completion. -->
		<InsightApplyDialog
			v-model="insightApplyDialog.show"
			:pattern="insightApplyDialog.row || {}"
			@applied="afterAction"
		/>
	</div>
</template>

<script setup>
// LearningTab — the pattern-learning review board + settings, the "Learning"
// tab inside the Skills page (plan §6.4). Managed-only: get_learning_status
// reports self_hosted → this renders the managed-only empty state and stops.
// Otherwise: a Settings card (enable / window / max proposals / Run now), an
// Apply bar (learned skills ride the shared custom-skill push — the SyncPill
// pattern), and a review board of plain-English cards with strength/sensitivity
// chips, caveat badges, an expandable drill-down (raw stats + roles + compiled
// bullet + Desk links via get_learned_pattern), and the Approve / Edit-then-
// approve / Reject / Snooze / Un-approve / Restore / batch-approve actions.
import { ref, reactive, computed, onMounted, onBeforeUnmount } from "vue"
import {
	Badge,
	Breadcrumbs,
	Button,
	Checkbox,
	Dialog,
	Dropdown,
	FeatherIcon,
	FormControl,
	LoadingIndicator,
	Switch,
	Tooltip,
	toast,
	confirmDialog,
} from "frappe-ui"
import LayoutHeader from "@/components/LayoutHeader.vue"
import SyncPill from "./SyncPill.vue"
import InsightApplyDialog from "@/components/learning/InsightApplyDialog.vue"
import { timeAgo, exactDate } from "@/utils/datetime"
import {
	listLearnedPatternsPage,
	getLearnedPattern,
	approveLearnedPattern,
	unapproveLearnedPattern,
	rejectLearnedPattern,
	acknowledgeLearnedPattern,
	restoreRejectedPattern,
	snoozeLearnedPattern,
	batchApprove,
	applyLearnedSkills,
	getLearnedApplyStatus,
	runPatternAnalysisNow,
	getLearningSettings,
	setLearningSettings,
	getLearningStatus,
} from "@/api/learning"

const emit = defineEmits(["changed"])

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

// ── static config ────────────────────────────────────────────────────────────
const STATUS_OPTIONS = [
	{ label: "To review", value: "Proposed" },
	{ label: "Approved", value: "Approved" },
	{ label: "Active", value: "Active" },
	{ label: "Snoozed", value: "Snoozed" },
	{ label: "Stale", value: "Stale" },
	{ label: "Rejected", value: "Rejected" },
	{ label: "All", value: "All" },
]
const STATUS_THEME = {
	Proposed: "blue",
	Approved: "green",
	Active: "green",
	Rejected: "red",
	Snoozed: "gray",
	Stale: "orange",
	Superseded: "gray",
	Archived: "gray",
}
const DOMAIN_LABELS = {
	selling: "Selling",
	buying: "Buying",
	stock: "Stock",
	accounts: "Accounts",
	projects: "Projects",
	org: "Org",
}
const SNOOZE_DAYS = [7, 30, 90]
// Mirror learned_api.ACK_NOTE: the review_note a B/C Acknowledge stamps. Keep in
// sync with the server constant; used to render an acknowledged (insight-only)
// row distinctly from a real rejection. Needs the card to expose review_note.
const ACK_NOTE = "Acknowledged - insight only"

// ── state ────────────────────────────────────────────────────────────────────
const selfHosted = ref(false)
const savingSettings = ref(false)
const runningNow = ref(false)
const acting = ref("") // pattern name (or "__batch__") currently acting

const settings = reactive({
	pattern_learning_enabled: false,
	pattern_window_start: "",
	pattern_window_end: "",
	pattern_max_proposals_per_run: 10,
	pattern_row_budget_per_night: 500000,
})
const status = reactive({
	enabled: false,
	lastRunAt: "",
	lastRunStatus: "",
	nextRunAt: "",
	scanMode: "",
	latestRun: null,
})

const board = reactive({ rows: [], total: 0, hasMore: false, loading: false })
const facets = ref([])
const queuedCount = ref(0)
const pendingApplyCount = ref(0)
// Stale rows still compiled into a live skill: removed on the next Apply (§6.5).
const staleRemovalCount = ref(0)
const reviewActivity = ref({ decided: 0, total: 0, last_by_name: "" })
const domain = ref("")
const boardStatus = ref("Proposed")

const expanded = reactive({}) // name -> detail object | "loading"
const selected = ref(new Set())
const selectedNames = computed(() => Array.from(selected.value))
const syncPill = ref(null)

// apply lifecycle: applyActive keeps the Apply bar (and its SyncPill) mounted
// through the apply->poll->done cycle even after pendingApplyCount drops to 0,
// so the push progress / failure never vanishes mid-flight (mirrors the Skills
// list banner, which is always mounted).
const applyActive = ref(false)
let applyTimer = null
// A cheap "active chats right now" count would render in the Apply modal; no
// endpoint exposes it yet, so it stays null and the line is omitted gracefully.
const activeChatCount = ref(null)

// dialogs
const rejectDialog = reactive({ show: false, name: "", reason: "" })
const editDialog = reactive({ show: false, name: "", draft: "" })
const applyDialog = reactive({ show: false })
const insightApplyDialog = reactive({ show: false, row: null })

// ── display helpers ──────────────────────────────────────────────────────────
function domainLabel(s) {
	return DOMAIN_LABELS[s] || (s ? s[0].toUpperCase() + s.slice(1) : s)
}
function strengthTheme(b) {
	return b === "High" ? "green" : b === "Medium" ? "orange" : "gray"
}
// Sensitivity badge. B is two different things and must not both read as
// "Party-specific": a row DECLARED A but escalated to B by content (a specific
// customer/supplier is named) is genuinely party-specific; a detector that
// DECLARES B (process-control shortcuts like the update_stock bypass or rounding
// disable: buy-pi-update-stock, acct-rounding-habit) is org-level
// operational friction, so it reads as "Sensitive". We infer the split from
// declared vs effective; a dedicated sensitivity_kind field on the card would be
// more robust (see the API note).
function sensBadge(row) {
	const eff = row.effective_sensitivity || ""
	if (eff === "C") return { theme: "red", label: "Financial (insight only)" }
	if (eff === "B") {
		return (row.sensitivity || "") === "A"
			? { theme: "orange", label: "Party-specific" }
			: { theme: "orange", label: "Sensitive" }
	}
	return { theme: "gray", label: "Aggregate-safe" }
}
// The exact-text B-class disclosure banner (plan section 6.6): learned skill
// files are bench-global, so Allowed Roles steers activation but is not a
// confidentiality boundary. Names the detected roles when the drill-down has
// loaded them; otherwise a generic phrasing.
function disclosureText(roles) {
	const named = roles && roles.length ? roles.join(", ") : "its detected roles"
	return (
		"This text becomes readable by every chat user on this site, regardless of ERP " +
		`permissions; scoped to ${named} in normal operation but not hidden from a user who looks.`
	)
}
function bRoles(row) {
	const d = expanded[row.name]
	return d && d !== "loading" && Array.isArray(d.roles) ? d.roles : []
}
// An acknowledged (insight-only) row is stored as a terminal Rejected + ACK_NOTE;
// render it as "Acknowledged", not a rejection. Requires review_note on the card
// payload (see the API note); falls back to plain Rejected until then.
function isAcknowledged(row) {
	return (row.review_note || "") === ACK_NOTE
}
function pct(v) {
	const n = Number(v || 0)
	return `${Math.round(n * 10) / 10}%`
}
function mul100(v) {
	return Number(v || 0) * 100
}
function toHHMM(t) {
	const m = /^(\d{1,2}):(\d{2})/.exec(String(t || ""))
	return m ? `${m[1].padStart(2, "0")}:${m[2]}` : ""
}
// Coerce an Int field to a number, falling back to a default only for a truly
// absent value (null / undefined / ""); a legitimate 0 is kept.
function intOr(v, d) {
	if (v === null || v === undefined || v === "") return d
	const n = Number(v)
	return Number.isFinite(n) ? n : d
}
// Never let a valid submitted window round-trip to blank. A midnight Time (00:00)
// can serialize back as "" through a falsy timedelta server-side; when the echo
// is blank but we sent a real value, keep what we sent.
function keepTime(returned, submitted) {
	return toHHMM(returned) || toHHMM(submitted) || String(submitted || "")
}
function deskUrl(doctype, name) {
	if (!doctype || !name) return ""
	const dt = String(doctype).toLowerCase().replace(/ /g, "-")
	return `/app/${dt}/${encodeURIComponent(name)}`
}
// exceptions items may be strings or {doctype,name,label,...} — render defensively
function exLabel(ex) {
	if (ex == null) return ""
	if (typeof ex === "string") return ex
	return ex.label || ex.name || ex.value || JSON.stringify(ex)
}
function exDeskUrl(ex) {
	if (ex && typeof ex === "object" && ex.doctype && ex.name) return deskUrl(ex.doctype, ex.name)
	return ""
}

// Coverage note is printed ONCE. The engine appends it to pattern_last_run_status
// (rendered as plain text above), so suppress the standalone line when the
// summary already contains it, otherwise it prints twice.
const coverageNote = computed(() => {
	const note = (status.latestRun && status.latestRun.coverage_note) || ""
	if (!note) return ""
	return (status.lastRunStatus || "").includes(note) ? "" : note
})

const emptyTitle = computed(() =>
	boardStatus.value === "Proposed" ? "Nothing to review yet" : "No patterns here"
)
const emptyDescription = computed(() => {
	if (boardStatus.value === "Proposed") {
		return status.enabled
			? "Proposals appear the morning after an analysis run."
			: "Enable behavioural learning above, then run an analysis to see proposals."
	}
	return "Try a different domain or status filter."
})

// ── loaders ──────────────────────────────────────────────────────────────────
async function loadStatus() {
	try {
		const st = await getLearningStatus()
		selfHosted.value = !!st.self_hosted
		status.enabled = !!st.enabled
		status.lastRunAt = st.last_run_at || ""
		status.lastRunStatus = st.last_run_status || ""
		status.nextRunAt = st.next_run_at || ""
		status.scanMode = st.scan_mode || ""
		status.latestRun = st.latest_run || null
	} catch (e) {
		// parent mounts this only for SMs; a failure here means no access
		selfHosted.value = false
		toast.error(errMsg(e))
	}
}

async function loadSettings() {
	try {
		const res = await getLearningSettings()
		const s = res.settings || {}
		settings.pattern_learning_enabled = !!s.pattern_learning_enabled
		settings.pattern_window_start = toHHMM(s.pattern_window_start)
		settings.pattern_window_end = toHHMM(s.pattern_window_end)
		settings.pattern_max_proposals_per_run = intOr(s.pattern_max_proposals_per_run, 10)
		settings.pattern_row_budget_per_night = intOr(s.pattern_row_budget_per_night, 500000)
	} catch (e) {
		toast.error(errMsg(e))
	}
}

async function fetchBoard(mode = "reset") {
	const append = mode === "more"
	if (!append) selected.value = new Set()
	board.loading = true
	try {
		const surfaced = boardStatus.value === "Proposed" ? 1 : "all"
		const res = await listLearnedPatternsPage({
			domain: domain.value,
			status: boardStatus.value,
			surfaced,
			start: append ? board.rows.length : 0,
			page_length: 20,
		})
		const rows = res.rows || []
		board.rows = append ? [...board.rows, ...rows] : rows
		board.total = res.total || 0
		board.hasMore = !!res.has_more
		facets.value = (res.facets && res.facets.domain) || []
		queuedCount.value = res.queued_count || 0
		pendingApplyCount.value = res.pending_apply_count || 0
		staleRemovalCount.value = res.stale_pending_removal || 0
		reviewActivity.value = res.review_activity || { decided: 0, total: 0, last_by_name: "" }
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		board.loading = false
	}
}

function reloadAll() {
	loadStatus()
	fetchBoard("reset")
}

// ── filters ──────────────────────────────────────────────────────────────────
function setDomain(v) {
	if (domain.value === v) return
	domain.value = v
	fetchBoard("reset")
}
function setBoardStatus(v) {
	if (boardStatus.value === v) return
	boardStatus.value = v
	fetchBoard("reset")
}

// ── drill-down ───────────────────────────────────────────────────────────────
async function toggleExpand(name) {
	if (expanded[name]) {
		delete expanded[name]
		return
	}
	expanded[name] = "loading"
	try {
		expanded[name] = await getLearnedPattern(name)
	} catch (e) {
		delete expanded[name]
		toast.error(errMsg(e))
	}
}

// ── selection / batch ────────────────────────────────────────────────────────
function toggleSelect(row) {
	if (row.effective_sensitivity !== "A") return
	const s = new Set(selected.value)
	if (s.has(row.name)) s.delete(row.name)
	else s.add(row.name)
	selected.value = s
}
async function doBatchApprove() {
	if (!selectedNames.value.length) return
	acting.value = "__batch__"
	try {
		const r = await batchApprove(selectedNames.value)
		toast.success(`Approved ${r.count || selectedNames.value.length}`)
		afterAction()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		acting.value = ""
	}
}

// ── single-pattern actions ───────────────────────────────────────────────────
function afterAction() {
	fetchBoard("reset")
	emit("changed")
}

async function doApprove(row) {
	acting.value = row.name
	try {
		await approveLearnedPattern(row.name)
		toast.success("Approved")
		afterAction()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		acting.value = ""
	}
}
async function doUnapprove(row) {
	acting.value = row.name
	try {
		await unapproveLearnedPattern(row.name)
		toast.success("Un-approved")
		afterAction()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		acting.value = ""
	}
}
async function doAcknowledge(row) {
	acting.value = row.name
	try {
		await acknowledgeLearnedPattern(row.name)
		toast.success("Acknowledged")
		afterAction()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		acting.value = ""
	}
}
async function doRestore(row) {
	acting.value = row.name
	try {
		await restoreRejectedPattern(row.name)
		toast.success("Restored")
		afterAction()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		acting.value = ""
	}
}
function snoozeOptions(row) {
	return SNOOZE_DAYS.map((d) => ({ label: `${d} days`, onClick: () => doSnooze(row, d) }))
}
async function doSnooze(row, days) {
	acting.value = row.name
	try {
		await snoozeLearnedPattern(row.name, days)
		toast.success(`Snoozed ${days} days`)
		afterAction()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		acting.value = ""
	}
}

// reject modal
function openReject(row) {
	rejectDialog.name = row.name
	rejectDialog.reason = ""
	rejectDialog.show = true
}
async function submitReject() {
	const reason = (rejectDialog.reason || "").trim()
	if (!reason) {
		toast.error("A rejection reason is required.")
		return
	}
	acting.value = rejectDialog.name
	try {
		await rejectLearnedPattern(rejectDialog.name, reason)
		toast.success("Rejected")
		rejectDialog.show = false
		afterAction()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		acting.value = ""
	}
}

// insight → skill modal (D5): the dialog drafts, confirms and applies on its
// own (incl. the "Acknowledge instead" shortcut); @applied → afterAction so
// the board refetches and the parent badge updates.
function openInsightApply(row) {
	insightApplyDialog.row = row
	insightApplyDialog.show = true
}

// edit-then-approve modal
function openEdit(row) {
	editDialog.name = row.name
	editDialog.draft = row.skill_draft || ""
	editDialog.show = true
}
async function submitEdit() {
	acting.value = editDialog.name
	try {
		await approveLearnedPattern(editDialog.name, editDialog.draft)
		toast.success("Approved with edits")
		editDialog.show = false
		afterAction()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		acting.value = ""
	}
}

// ── settings actions ─────────────────────────────────────────────────────────
async function saveSettings() {
	savingSettings.value = true
	try {
		const res = await setLearningSettings({
			pattern_learning_enabled: settings.pattern_learning_enabled ? 1 : 0,
			pattern_window_start: settings.pattern_window_start,
			pattern_window_end: settings.pattern_window_end,
			pattern_max_proposals_per_run: Number(settings.pattern_max_proposals_per_run) || 0,
			pattern_row_budget_per_night: Number(settings.pattern_row_budget_per_night) || 0,
		})
		const s = (res && res.settings) || {}
		settings.pattern_window_start = keepTime(
			s.pattern_window_start,
			settings.pattern_window_start
		)
		settings.pattern_window_end = keepTime(s.pattern_window_end, settings.pattern_window_end)
		toast.success("Settings saved")
		loadStatus()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		savingSettings.value = false
	}
}

function runNow() {
	confirmDialog({
		title: "Run analysis now?",
		message:
			"Runs a full pattern analysis immediately, bypassing the nightly window. It scans this site's history and can add database load during business hours. New proposals appear here once the run finishes.",
		onConfirm: async ({ hideDialog }) => {
			runningNow.value = true
			try {
				const r = await runPatternAnalysisNow()
				hideDialog()
				if (r && r.ok === false) {
					toast.error(r.reason || "Could not start the run.")
				} else {
					toast.success("Analysis started" + (r && r.run ? ` (${r.run})` : ""))
				}
				loadStatus()
			} catch (e) {
				toast.error(errMsg(e))
			} finally {
				runningNow.value = false
			}
		},
	})
}

// Apply opens a confirm modal (restart warning is mandatory before proceeding);
// confirmApply does the push and keeps progress mounted through the poll.
function applyLearned() {
	applyDialog.show = true
}

async function confirmApply() {
	try {
		await applyLearnedSkills()
		applyDialog.show = false
		applyActive.value = true
		toast.success("Applying learned skills…")
		// learned skills ride the shared custom-skill push; the SyncPill polls
		// the live status; we also poll to keep the bar mounted and surface the
		// final success/failure.
		syncPill.value && syncPill.value.checkNow()
		startApplyPoll()
		fetchBoard("reset")
		emit("changed")
	} catch (e) {
		toast.error(errMsg(e))
	}
}

function stopApplyPoll() {
	if (applyTimer) {
		clearInterval(applyTimer)
		applyTimer = null
	}
}
function startApplyPoll() {
	stopApplyPoll()
	applyTimer = setInterval(async () => {
		let st
		try {
			st = await getLearnedApplyStatus()
		} catch (e) {
			return // transient; keep the bar up and keep polling
		}
		if (st && st.pending) return
		stopApplyPoll()
		applyActive.value = false
		const s = (st && st.last_sync_status) || ""
		if (s.startsWith("failed")) {
			toast.error(s.replace(/^failed:?/, "").trim() || "Applying learned skills failed.")
		} else {
			toast.success("Learned skills applied to your assistant.")
		}
		fetchBoard("reset")
		emit("changed")
	}, 3000)
}

// ── init ─────────────────────────────────────────────────────────────────────
onMounted(async () => {
	await loadStatus()
	if (selfHosted.value) return
	loadSettings()
	fetchBoard("reset")
	// resume progress if an Apply is already in flight (page reloaded mid-push)
	try {
		const st = await getLearnedApplyStatus()
		if (st && st.pending) {
			applyActive.value = true
			syncPill.value && syncPill.value.checkNow()
			startApplyPoll()
		}
	} catch (e) {
		// best-effort resume; never block the tab
	}
})
onBeforeUnmount(stopApplyPoll)
</script>
