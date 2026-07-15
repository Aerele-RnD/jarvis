import frappe

from jarvis.permissions import has_jarvis_access

no_cache = 1


def get_context(context):
	"""Landing page for a signed-in user who lacks Jarvis access — the redirect
	target of www/jarvis.py and www/jarvis_mobile.py's gates (and the desk's
	floating Jarvis button once it reads bootinfo.jarvis_has_access). Read-only:
	no frappe.db.commit()."""
	if frappe.session.user == "Guest":
		# Not reachable via the two www gates above (they keep Guests on the
		# /app -> login bounce), but a Guest can still land here directly.
		frappe.local.flags.redirect_location = "/login"
		raise frappe.Redirect

	if has_jarvis_access():
		# Self-heals: access may have been granted after the link that sent the
		# user here was generated (a stale bookmark, or an admin who granted
		# the role mid-session), so don't strand an already-authorized user.
		frappe.local.flags.redirect_location = "/jarvis"
		raise frappe.Redirect

	context.user_fullname = frappe.utils.get_fullname(frappe.session.user)
	context.admin_emails = _admin_contacts()
	return context


def _admin_contacts(limit: int = 5) -> list[str]:
	"""Emails of up to ``limit`` enabled System Users holding System Manager,
	used to seed the page's "request access" mailto CTA.

	Reuses Frappe's ``get_users_with_role`` — the same idiom as
	``notify_system_managers`` (jarvis/learning/lifecycle.py) and
	``_users_with_role`` (jarvis/learning/questions.py) elsewhere in jarvis —
	which already filters to enabled users and excludes ``Administrator``. The
	``user_type`` check below is a defensive extra: System Manager is a
	desk-access role and shouldn't land on a portal user, but this keeps the
	guarantee explicit rather than assumed."""
	from frappe.utils.user import get_users_with_role

	try:
		names = [n for n in get_users_with_role("System Manager") if n and n != "Guest"]
	except Exception:
		return []
	if not names:
		return []

	try:
		users = frappe.get_all(
			"User",
			filters={"name": ["in", names], "user_type": "System User"},
			fields=["email"],
			order_by="full_name asc",
			limit=limit,
		)
	except Exception:
		# This page exists to deny gracefully — an empty CTA beats a 500.
		return []
	return [u.email for u in users if u.email]
