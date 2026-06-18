"""Link an existing File DocType entry to a target doc as an attachment.

Composes naturally with ``download_pdf``: the agent first generates a
PDF (which lands attached to the source record), then the customer can
ask to attach the same artifact to a different record (e.g. "attach the
invoice PDF to the related Customer doc"). Without this tool the agent
would have to re-render the PDF, doubling the storage cost and creating
a content-hash mismatch in the File doctype's dedup table.

The underlying ``frappe.utils.file_manager.add_attachments`` accepts a
file_url OR a File doc name; we forward whichever the agent supplies.

Permission contract: **write** permission on the target record (a user
who can't write to the doc can't add an attachment to it, mirroring the
Desk attachments UI). The source file's own permission gate is enforced
by Frappe's File doc read check when ``add_attachments`` resolves the
URL.
"""
import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools import require_doctype_and_name


def attach_to_doc(
    file_url: str,
    target_doctype: str,
    target_name: str,
) -> dict:
    """Attach the File at ``file_url`` to ``target_doctype/target_name``.

    ``file_url`` is the path-style URL the File doctype exposes
    (``/private/files/...`` or ``/files/...``); a download_pdf result's
    ``file_url`` plugs straight in.

    Returns ``{file_url, target_doctype, target_name, attached_file_name}``
    where ``attached_file_name`` is the new File doc id (distinct from
    the source File's id, since attachments are tracked per linked
    record).
    """
    if not file_url:
        raise InvalidArgumentError("file_url is required")
    require_doctype_and_name(target_doctype, target_name)

    if not frappe.db.exists(target_doctype, target_name):
        raise InvalidArgumentError(f"unknown {target_doctype}: {target_name}")

    if not frappe.has_permission(target_doctype, ptype="write", doc=target_name):
        raise PermissionDeniedError(
            f"no write permission on {target_doctype} {target_name}",
        )

    from frappe.utils.file_manager import add_attachments

    add_attachments(target_doctype, target_name, [file_url])

    # add_attachments doesn't return a handle; look up the file the
    # caller just attached so the agent can confirm which File doc id
    # the chat will reference next time.
    new_file = frappe.db.get_value(
        "File",
        {
            "file_url": file_url,
            "attached_to_doctype": target_doctype,
            "attached_to_name": target_name,
        },
        "name",
    )

    return {
        "file_url": file_url,
        "target_doctype": target_doctype,
        "target_name": target_name,
        "attached_file_name": new_file,
    }
