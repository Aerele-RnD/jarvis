// wiki-graph-core — canonical shared knowledge-graph component set + pure analysis.
// Consumed by the tenant (jarvis/frontend) and admin (jarvis_admin) Vite builds.
// Presentational only: components take data via props and emit actions; each
// surface wraps them with its own data-fetching + action wiring.

// Pure analysis (graphology) — no Vue, no fetch.
export { analyze } from "./src/graphAnalysis.js";
export { overlayFilter, egoGraph, searchGraph, collapseClusters } from "./src/graphView.js";
export { computeSimilarity, contentSuggestions } from "./src/similarity.js";
export { fullAnalysis } from "./src/analysis.js";
export { computeActions } from "./src/actions.js";
// Worker-backed analysis (off the render thread, R4; sync fallback). Preferred
// entry for surfaces: `await runAnalysis(data)`.
export { runAnalysis } from "./src/runAnalysis.js";
export { nodeStyle, edgeStyle, LEGEND } from "./src/graphStyle.js";

// Renderer feature flag (R10) + WebGL detection (R5).
export { renderer3dEnabled } from "./src/flag.js";
export { webglAvailable } from "./src/Graph3D.vue";

// Presentational components. Graph3D (3d-force-graph) is THE renderer; the
// rollback path (R10) is handled at the mount site (flag-off = don't mount the
// new graph; admin keeps its untouched old esbuild page until 3D soaks), so the
// sigma GraphCanvas is not shipped here.
export { default as Graph3D } from "./src/Graph3D.vue";
export { default as HealthPanel } from "./src/HealthPanel.vue";
export { default as ExpertPanel } from "./src/ExpertPanel.vue";
export { default as RiskPanel } from "./src/RiskPanel.vue";
export { default as SuggestPanel } from "./src/SuggestPanel.vue";
export { default as DetailPanel } from "./src/DetailPanel.vue";
export { default as FilterBar } from "./src/FilterBar.vue";
export { default as DemandPanel } from "./src/DemandPanel.vue";
export { default as AnalysisTabs } from "./src/AnalysisTabs.vue";
export { default as EvolutionTab } from "./src/EvolutionTab.vue";
export { default as ActionsTab } from "./src/ActionsTab.vue";
export { default as ExclusionRules } from "./src/ExclusionRules.vue";
