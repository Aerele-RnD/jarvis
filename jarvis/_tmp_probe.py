"""Temporary diagnostic module (session scratch) — remove after use."""
import json

import frappe

from jarvis.chat.openclaw_client import OpenclawSession


def _connect():
	s = frappe.get_single("Jarvis Settings")
	gw = (s.agent_url or "").replace("http://", "ws://").replace("https://", "wss://")
	return OpenclawSession.connect(gw)


def probe():
	sess = _connect()
	try:
		res = sess._request("config.get", {}, timeout_s=15)
		payload = res.get("payload") or {}
		cfg = payload.get("config") if isinstance(payload.get("config"), dict) else payload
		print("CONFIG.GET OK")
		print("tools:", json.dumps(cfg.get("tools")))
		print("plugins:", json.dumps(cfg.get("plugins"))[:300])
		print("top-level keys:", sorted(cfg.keys()))
	except Exception as e:
		print("config.get FAILED:", type(e).__name__, str(e)[:300])
	finally:
		sess.close()


def probe_tools():
	sess = _connect()
	try:
		for method in ("tools.list", "gateway.tools.list", "agents.tools"):
			try:
				res = sess._request(method, {}, timeout_s=10)
				print(method, "OK:", json.dumps(res.get("payload"))[:400])
			except Exception as e:
				print(method, "->", str(e)[:120])
	finally:
		sess.close()


def probe_turn():
	sess = _connect()
	try:
		key = sess.create_session(label=f"jarvis-diag-{frappe.generate_hash(length=6)}")
		print("session:", key)
		events = sess.stream_agent_turn(
			key,
			"Call the tool jarvis__get_list with doctype Customer, fields [name], limit 3, "
			"and show the result. If you cannot see any tool named jarvis__get_list in your "
			"available tools, reply with exactly: TOOLS-MISSING",
			f"diag:{key}",
		)
		text = ""
		tool_events = []
		for ev in events:
			if ev.get("kind") == "tool":
				tool_events.append((ev.get("name") or ev.get("tool_name"), ev.get("phase")))
			elif ev.get("kind") == "assistant" and ev.get("text"):
				text = ev["text"]
		print("tool events:", tool_events)
		print("assistant text:", (text or "")[:400])
	finally:
		sess.close()


def probe_restart():
	sess = _connect()
	try:
		for method in ("update.restart", "gateway.restart", "restart", "system.restart", "server.restart"):
			try:
				res = sess._request(method, {}, timeout_s=8)
				print(method, "ACCEPTED:", json.dumps(res.get("payload"))[:200])
				return
			except Exception as e:
				print(method, "->", str(e)[:110])
	finally:
		try:
			sess.close()
		except Exception:
			pass


def probe_status():
	sess = _connect()
	try:
		for method in ("status", "plugins.list", "plugins.status", "health", "about", "version"):
			try:
				res = sess._request(method, {}, timeout_s=8)
				print(method, "OK:", json.dumps(res.get("payload"))[:600])
			except Exception as e:
				print(method, "->", str(e)[:100])
	finally:
		try:
			sess.close()
		except Exception:
			pass


def plugin_state():
	"""One-line plugin load state for polling: PLUGIN-OK / PLUGIN-ERR / GATEWAY-DOWN."""
	try:
		sess = _connect()
	except Exception as e:
		print("GATEWAY-DOWN:", str(e)[:120])
		return
	try:
		res = sess._request("health", {}, timeout_s=10)
		p = (res.get("payload") or {}).get("plugins") or {}
		loaded = p.get("loaded") or []
		errors = p.get("errors") or []
		if any((x or {}).get("id") == "jarvis-openclaw-plugin" for x in loaded) or (
			"jarvis-openclaw-plugin" in loaded
		):
			print("PLUGIN-OK")
		elif errors:
			err = (errors[0] or {}).get("error") or ""
			print("PLUGIN-ERR:", err[:160])
		else:
			print("PLUGIN-ABSENT (not loaded, no error)")
	except Exception as e:
		print("HEALTH-FAILED:", str(e)[:120])
	finally:
		try:
			sess.close()
		except Exception:
			pass


def do_dev_onboard():
	"""Wrapper: run dev_onboard as Administrator, print result or traceback."""
	import json as _json
	frappe.set_user("Administrator")
	from jarvis import onboarding
	try:
		res = onboarding.dev_onboard(email="dev@local.test", company="Local Dev Co", plan="Free Dev")
		print("DEV_ONBOARD OK:", _json.dumps(res)[:600])
	except Exception as e:
		print("DEV_ONBOARD FAILED:", type(e).__name__, str(e)[:400])
		print(frappe.get_traceback()[:1500])


def push_llm(api_key="placeholder-set-a-real-key", provider="OpenAI", model="gpt-5.5", auth_mode="api_key"):
	"""Set LLM creds on Jarvis Settings + save (triggers on_update -> admin ->
	fleet-agent llm-creds -> writes openclaw.json + restarts container)."""
	frappe.set_user("Administrator")
	s = frappe.get_single("Jarvis Settings")
	s.deployment_mode = "Managed"
	s.llm_provider = provider
	s.llm_model = model
	s.llm_auth_mode = auth_mode
	s.llm_api_key = api_key
	s.save(ignore_permissions=True)
	frappe.db.commit()
	print("saved; last_sync_status=", frappe.db.get_single_value("Jarvis Settings", "last_sync_status"))


def show_llm_settings():
	import json as _json
	s = frappe.get_single("Jarvis Settings")
	print("auth_mode:", s.llm_auth_mode, "provider:", s.llm_provider, "model:", s.llm_model)
	print("oauth_email:", s.llm_oauth_account_email, "connected_at:", s.llm_oauth_connected_at)
	print("pool models count:", len(s.models or []))
	for m in (s.models or []):
		print("  model:", m.model, "cred_type:", getattr(m,'credential_type',None), "accounts:", len(getattr(m,'accounts',[]) or []))
	# probe for a stored oauth blob anywhere
	for f in ("llm_api_key","llm_oauth_blob"):
		try:
			v = s.get_password(f, raise_exception=False)
			print(f, "->", ("<set>" if v else "<empty>"))
		except Exception as e:
			print(f, "-> n/a", str(e)[:40])


def begin_openai_signin():
	"""Clear the placeholder api_key clobber, then begin OpenAI PKCE paste-signin.
	Prints the auth URL + nonce. Run complete_openai_signin(redirected_url) after."""
	import json as _json
	frappe.set_user("Administrator")
	s = frappe.get_single("Jarvis Settings")
	# undo the verification clobber
	s.llm_api_key = ""
	s.db_set("llm_api_key", "", update_modified=False)
	frappe.db.commit()
	from jarvis.oauth import api as oauth_api
	res = oauth_api.begin_paste_signin(provider="OpenAI", model="gpt-5.5")
	print("BEGIN:", _json.dumps(res)[:1200])


def complete_openai_signin(nonce, redirected_url):
	frappe.set_user("Administrator")
	from jarvis.oauth import api as oauth_api
	import json as _json
	res = oauth_api.complete_paste_signin(nonce=nonce, redirected_url=redirected_url)
	print("COMPLETE:", _json.dumps(res)[:1200])


def clear_device_and_probe():
	"""Clear stale chat-device creds (paired with the remote container) so the
	next connect pairs fresh with the LOCAL container, then run the health probe."""
	frappe.set_user("Administrator")
	s = frappe.get_single("Jarvis Settings")
	for f in ("chat_device_id","chat_device_public_key","chat_device_private_key","chat_device_token"):
		s.db_set(f, "", update_modified=False)
	frappe.db.commit()
	print("cleared stale device creds; connecting fresh...")
	plugin_state()


def health_raw():
	import json as _json
	frappe.set_user("Administrator")
	sess = _connect()
	try:
		res = sess._request("health", {}, timeout_s=12)
		p = (res.get("payload") or {})
		print("plugins:", _json.dumps(p.get("plugins"))[:800])
	finally:
		try: sess.close()
		except Exception: pass


def complete_now():
	import json as _json
	frappe.set_user("Administrator")
	from jarvis.oauth import api as oauth_api
	nonce = "87d54ea0e5783c354a7cc40f9e429bdcc30525274dcaea30"
	url = "http://localhost:1455/auth/callback?code=ac_7KVHFRhM8WUWDj_IfnTMtkhfCfFGpodqSoXha49ieh4.og2YJGPZe1i9DWyAOQfF2-Fe06QwXrQUxcKt_I4LZ0E&scope=openid+profile+email+offline_access+api.connectors.read+api.connectors.invoke&state=FTvdwVQOpU6kHpKJ_MckkA"
	try:
		res = oauth_api.complete_paste_signin(nonce=nonce, redirected_url=url)
		print("COMPLETE:", _json.dumps(res)[:1000])
	except Exception as e:
		print("COMPLETE FAILED:", type(e).__name__, str(e)[:400])
		print(frappe.get_traceback()[:1200])


def complete_from_file():
	"""Reads nonce + pasted URL from /tmp/oauth2.json, completes signin fast."""
	import json as _json
	frappe.set_user("Administrator")
	from jarvis.oauth import api as oauth_api
	d = _json.loads(open("/tmp/oauth2.json").read())
	try:
		res = oauth_api.complete_paste_signin(nonce=d["nonce"], redirected_url=d["url"])
		print("COMPLETE:", _json.dumps(res)[:1000])
	except Exception as e:
		print("COMPLETE FAILED:", type(e).__name__, str(e)[:400])


def probe_toolsurface():
	"""Ask the agent to enumerate its own tools + dump config.get tools block."""
	import json as _json
	sess = _connect()
	try:
		try:
			r = sess._request("config.get", {}, timeout_s=15)
			p = r.get("payload") or {}
			cfg = p.get("config") if isinstance(p.get("config"), dict) else p
			print("CFG.tools:", _json.dumps(cfg.get("tools"))[:400])
			ag = (cfg.get("agents") or {}).get("defaults", {})
			print("CFG.model:", _json.dumps(ag.get("model")))
			print("CFG.plugins:", _json.dumps(cfg.get("plugins"))[:300])
		except Exception as e:
			print("CFG.get ERR:", str(e)[:200])
		key = sess.create_session(label=f"jarvis-toolprobe-{frappe.generate_hash(length=6)}")
		print("SESSION:", key)
		events = sess.stream_agent_turn(
			key,
			"List EVERY tool you can call right now, as a plain comma-separated list of "
			"their exact names. Do not call any tool. If you have a tool named "
			"jarvis__get_list, include it. If you truly have zero tools, reply NO-TOOLS.",
			f"toolprobe:{key}",
		)
		text = ""
		for ev in events:
			if ev.get("kind") == "assistant" and ev.get("text"):
				text = ev["text"]
		print("AGENT-TOOLS:", (text or "")[:1500])
	finally:
		sess.close()


def probe_toolsearch():
	"""Force the agent to use its tool_search tool to find + call a jarvis tool."""
	sess = _connect()
	try:
		key = sess.create_session(label=f"jarvis-toolsearch-{frappe.generate_hash(length=6)}")
		print("SESSION:", key)
		events = sess.stream_agent_turn(
			key,
			"You have a tool called tool_search (tool_search.tool_search_tool). "
			"Use it NOW to search for a tool to list ERP documents — search the query "
			"'get_list' and also 'customer'. Report back the exact names of any tools it "
			"returns (especially anything starting with jarvis__). Then, if you find "
			"jarvis__get_list, call it with doctype=Customer, fields=[\"name\"], limit=3 "
			"and show the result. If tool_search returns nothing, reply SEARCH-EMPTY.",
			f"toolsearch:{key}",
		)
		text = ""
		tool_events = []
		for ev in events:
			if ev.get("kind") == "tool":
				tool_events.append((ev.get("name") or ev.get("tool_name"), ev.get("phase")))
			elif ev.get("kind") == "assistant" and ev.get("text"):
				text = ev["text"]
		print("TOOL-EVENTS:", tool_events)
		print("AGENT-REPLY:", (text or "")[:1500])
	finally:
		sess.close()


def push_ollama():
	"""Point the bench at the local Ollama (api_key mode -> no doctor needed).
	Triggers on_update -> admin -> fleet-agent llm-creds -> openclaw.json + restart."""
	frappe.set_user("Administrator")
	s = frappe.get_single("Jarvis Settings")
	s.deployment_mode = "Managed"
	s.llm_auth_mode = "api_key"
	s.llm_provider = "ollama"
	s.llm_model = "qwen2.5:3b"
	s.llm_base_url = "http://host.docker.internal:11434/v1"
	s.llm_api_key = "ollama-local"
	s.save(ignore_permissions=True)
	frappe.db.commit()
	print("pushed ollama config; last_sync_status=",
	      frappe.db.get_single_value("Jarvis Settings", "last_sync_status"))
