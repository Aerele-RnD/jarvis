// Web Worker: run the (heavy) graphology + TF-IDF analysis off the main thread
// so the 3D graph stays responsive (R4). Echoes the request id back.
import { fullAnalysis } from "./analysis.js";

self.onmessage = (e) => {
	const { id, data } = e.data || {};
	try {
		self.postMessage({ id, ok: true, result: fullAnalysis(data) });
	} catch (err) {
		self.postMessage({ id, ok: false, error: String((err && err.message) || err) });
	}
};
