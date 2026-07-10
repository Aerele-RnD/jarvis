"""Shared helper for writing Jarvis Settings Password fields OUTSIDE the
normal Document.save() pipeline.

Frappe only encrypts a Password field into the __Auth table when a value
passes through Document._save_passwords() - i.e. a real doc.save(). Writing
via doc.db_set(...) or frappe.db.set_value(...) bypasses that entirely and
stores the raw value in plaintext in the Single's row in tabSingles. Several
call sites in this app use db_set deliberately (to avoid re-triggering
on_update's admin-sync push during onboarding/rotation flows) but were
writing secrets straight into that plaintext column.

This mirrors the idiom already established in
jarvis_settings.py::_on_update_unified_llm for mirroring models[0].api_key
into the legacy llm_api_key field: encrypt the real value into __Auth via
set_encrypted_password, then write only an all-asterisk mask to the doc's
own field (db_set) so tabSingles never holds the secret. Every reader in
this app already goes through get_password(), so this is a drop-in swap.
"""

from frappe.utils.password import set_encrypted_password

SETTINGS = "Jarvis Settings"

# Same masking shape jarvis_settings.py already uses for llm_api_key - a
# fixed-length mask (not len(value)-length like Document._save_passwords)
# so the mask itself never leaks the secret's length.
_MASK = "*" * 10


def set_settings_password(doc, fieldname: str, value: str, *, update_modified: bool = True) -> None:
	"""Encrypt ``value`` into __Auth for Jarvis Settings.<fieldname>, then
	write only the mask to ``doc`` via db_set (never the plaintext).

	No-op when ``value`` is falsy - callers already guard on truthiness
	before calling (matching the db_set(...) call sites this replaces, which
	only wrote when the incoming value was present).

	``doc`` must be the Jarvis Settings singleton Document (or a doc whose
	db_set targets it) so the __Auth row (keyed to doctype+name) and the
	db_set column write land on the same record.
	"""
	if not value:
		return
	set_encrypted_password(SETTINGS, SETTINGS, value, fieldname)
	doc.db_set(fieldname, _MASK, update_modified=update_modified)


def clear_settings_password(doc, fieldname: str) -> None:
	"""Wipe a Jarvis Settings Password field: blank the tabSingles column AND
	drop the __Auth row.

	db_set(field, "") alone only blanks the masked placeholder in tabSingles;
	__Auth retains the prior secret, so get_password() keeps returning it
	after a "clear" (see jarvis/dev.py's _PASSWORD_FIELDS comment for the
	same footgun). Both writes are needed for the field to actually read
	as cleared afterwards.
	"""
	from frappe.utils.password import remove_encrypted_password

	doc.db_set(fieldname, "")
	remove_encrypted_password(SETTINGS, SETTINGS, fieldname)
