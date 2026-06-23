import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import frappeui from "frappe-ui/vite"
import path from "path"

export default defineConfig({
	plugins: [
		frappeui({
			frontendRoute: "/jarvis",
			buildConfig: {
				outDir: path.resolve(__dirname, "../jarvis/public/frontend"),
				indexHtmlPath: path.resolve(__dirname, "../jarvis/www/jarvis.html"),
				baseUrl: "/assets/jarvis/frontend/",
			},
		}),
		vue(),
	],
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "src"),
		},
	},
	optimizeDeps: {
		include: ["frappe-ui > feather-icons", "showdown", "engine.io-client"],
	},
})
