"""Send an email about a record - through the same code path as the
Desk "New Email" button, so a Communication audit row is created
alongside the queued send.

Wraps ``frappe.core.doctype.communication.email.make`` with
``send_email=True`` so the underlying helper both queues the send AND
creates the audit-trail Communication doc. The agent's mental model is
"send email to X about doc Y"; we forward subject + content + reference
+ recipients and let Frappe handle the rest.

Permission: ``email.make`` checks email permission on the reference
document internally (requires read perm + the EMAIL perm if defined
on the DocType). We add a boundary doctype/name existence check so
the agent gets a clean InvalidArgumentError on typos.

ALWAYS-CONFIRM territory: this fires an email to a real recipient.
The descriptor's agent-facing copy is explicit about that requirement.
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import InvalidArgumentError
from jarvis.tools import require_doctype_and_name


def send_email(
    recipients: str | list[str],
    subject: str,
    content: str,
    doctype: str,
    name: str,
    cc: str | list[str] | None = None,
    bcc: str | list[str] | None = None,
    send_me_a_copy: bool = False,
    print_format: str | None = None,
) -> dict:
    """Send an email about ``doctype/name`` and log it as a
    Communication row. Returns ``{communication_name, recipients,
    subject, doctype, name}``.
    """
    if not recipients:
        raise InvalidArgumentError("recipients is required")
    if not subject:
        raise InvalidArgumentError("subject is required")
    if content is None or content == "":
        raise InvalidArgumentError("content is required")
    require_doctype_and_name(doctype, name)
    if not frappe.db.exists(doctype, name):
        raise InvalidArgumentError(f"unknown {doctype}: {name}")

    from frappe.core.doctype.communication.email import make as _make

    result = _make(
        doctype=doctype,
        name=name,
        subject=subject,
        content=content,
        sent_or_received="Sent",
        recipients=recipients,
        cc=cc,
        bcc=bcc,
        send_email=True,
        send_me_a_copy=bool(send_me_a_copy),
        print_format=print_format,
    )
    return {
        "communication_name": (result or {}).get("name"),
        "recipients": recipients,
        "subject": subject,
        "doctype": doctype,
        "name": name,
    }
