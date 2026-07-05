// Shared extractor for a user-facing message out of a Frappe API error.
// Single source for AccountView / OnboardingView / LlmPoolEditor so a change to
// Frappe's error envelope only has to be made once.
export function errMessage(e) {
  return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}
