// Shared extractor for a user-facing message out of a Frappe API error.
// Single source for AccountView / OnboardingView / LlmPoolEditor so a change to
// Frappe's error envelope only has to be made once.
//
// Frappe HTML-escapes throw() messages before they reach the client, so a
// backend "Settings -> Developer" arrives here as "Settings -&gt; Developer"
// and would render literally if shown as-is. Decode entities + strip any
// wrapping tags via a detached element (never inserted into the live DOM, so
// nothing in the message - script/img/etc. - ever executes) before handing
// the string to a caller.
export function errMessage(e) {
  const raw = (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
  if (typeof document === "undefined") return raw
  const d = document.createElement("div")
  d.innerHTML = raw // decodes &gt; &amp; &#39; etc; detached, so no script/img runs
  return (d.textContent || d.innerText || raw).trim()
}
