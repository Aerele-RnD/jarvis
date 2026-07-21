"""Panel-hardening tests for ``jarvis.chat.agents_api`` (PP-1 / PP-4 / PP-6).

Covers the three adversarial-panel findings fixed on the agents SPA endpoints:

  * PP-1 read-path strong-verb gate (findings #2/#5): ``list_findings`` serves the
    stored authored ``title``/``detail_md`` through the SAME shared helper the
    fallback dashboard uses, so a "saved/recovered/prevented" token on any row that
    is NOT a ``confirmed_outcome`` with a resolving provenance link is neutralised
    server-side — no read surface can emit an unearned strong verb — and every row
    carries its ``result_class`` + class-conditional metadata for the SPA badge.
  * PP-6 per-customer ceiling (finding #3): the activation-ceiling raise is bound to
    ONE named customer and system-verifies that customer's reviewer covers two packs;
    a raise for customer A never unlocks a second live module for customer B.
  * PP-6 promotion TOCTOU (finding #1): promotion serializes on a per-customer redis
    lock; when the lock is unavailable the promotion refuses rather than racing the
    budget check.

Run:
  bench --site patterntest.localhost run-tests --app jarvis \
    --module jarvis.tests.test_platform_agents_api_hardening
"""

import json
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat import agents_api

LISTING = "Jarvis Agent Listing"
INSTALLATION = "Jarvis Agent Installation"
FINDING = "Jarvis Agent Finding"
PROVENANCE = "Jarvis Agent Provenance Event"
SETTINGS = "Jarvis Settings"

PREFIX = "hardening-h-"


def _mk_user(email: str) -> str:
	if not frappe.db.exists("User", email):
		u = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"enabled": 1,
				"user_type": "System User",
			}
		)
		u.insert(ignore_permissions=True)
		u.add_roles("Jarvis User")
	return email


def _mk_listing(slug: str) -> str:
	if not frappe.db.exists(LISTING, slug):
		frappe.get_doc(
			{
				"doctype": LISTING,
				"agent_slug": slug,
				"title": f"Hardening {slug}",
				"rule_tokens": json.dumps(["tok"]),
				"doctypes_required": json.dumps([]),
			}
		).insert(ignore_permissions=True)
	return slug


def _mk_install(owner: str, slug: str, reviewer: str, activation_state: str = "shadow") -> object:
	_mk_listing(slug)
	name = frappe.db.get_value(INSTALLATION, {"agent": slug, "owner": owner}, "name")
	if name:
		return frappe.get_doc(INSTALLATION, name)
	doc = frappe.get_doc(
		{
			"doctype": INSTALLATION,
			"agent": slug,
			"run_as_user": owner,
			"reviewer": reviewer,
			"activation_state": activation_state,
		}
	)
	doc.owner = owner
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	frappe.db.set_value(INSTALLATION, doc.name, "owner", owner, update_modified=False)
	return frappe.get_doc(INSTALLATION, doc.name)


def _mk_finding(owner: str, slug: str, **over) -> object:
	f = {
		"doctype": FINDING,
		"agent": slug,
		"rule_id": "R1",
		"severity": "note",
		"result_class": "observed_fact",
		"title": "a plain title",
		"detail_md": "a plain detail",
		"state": "open",
	}
	f.update(over)
	doc = frappe.get_doc(f)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	frappe.db.set_value(FINDING, doc.name, "owner", owner, update_modified=False)
	return frappe.get_doc(FINDING, doc.name)


def _wipe(slugs) -> None:
	for n in frappe.get_all(FINDING, filters={"agent": ["in", slugs]}, pluck="name", ignore_permissions=True):
		frappe.delete_doc(FINDING, n, force=True, ignore_permissions=True)
	for n in frappe.get_all(
		INSTALLATION, filters={"agent": ["in", slugs]}, pluck="name", ignore_permissions=True
	):
		frappe.delete_doc(INSTALLATION, n, force=True, ignore_permissions=True)
	frappe.db.set_single_value(SETTINGS, "activation_module_ceiling", 1)
	frappe.db.commit()


@contextmanager
def _lock_denied(*a, **k):
	"""Stand-in for ``redis_lock`` that never grants the lock (simulates a concurrent
	activation change already holding it)."""
	yield False


# --------------------------------------------------------------------------- #
# PP-1 — list_findings read-path strong-verb gate + class metadata
# --------------------------------------------------------------------------- #
class TestListFindingsStrongVerbGate(FrappeTestCase):
	SLUG = PREFIX + "lf"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.user = _mk_user("h-lf-owner@example.com")
		_mk_listing(cls.SLUG)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		_wipe([self.SLUG])

	def tearDown(self):
		frappe.set_user("Administrator")
		_wipe([self.SLUG])

	def _rows(self):
		frappe.set_user(self.user)
		try:
			return agents_api.list_findings()["rows"]
		finally:
			frappe.set_user("Administrator")

	def test_strong_verb_neutralised_on_observed_fact(self):
		"""An observed_fact whose authored note says 'recovered X' is delivered to the
		SPA with the strong verb NEUTRALISED (never intact) on both title and detail."""
		_mk_finding(
			self.user,
			self.SLUG,
			result_class="observed_fact",
			title="recovered 5,00,000 from vendor",
			detail_md="We recovered 500000 and saved 20000 in duplicate payments.",
		)
		rows = self._rows()
		self.assertEqual(len(rows), 1)
		r = rows[0]
		self.assertEqual(r["result_class"], "observed_fact")
		for field in ("title", "detail_md"):
			self.assertNotIn("recovered", r[field].lower())
			self.assertNotIn("saved", r[field].lower())
			self.assertIn("[unverified]", r[field])

	def test_confirmed_outcome_with_provenance_keeps_verb(self):
		"""Control: a genuine confirmed_outcome row WITH a resolving outcome_provenance
		link keeps the strong verb — the gate neutralises only UNEARNED claims."""
		ev = agents_api._append_provenance_event(event_type="transaction_posted", agent=self.SLUG)
		_mk_finding(
			self.user,
			self.SLUG,
			result_class="confirmed_outcome",
			outcome_provenance=ev,
			title="recovered 5,00,000",
			detail_md="recovered 500000 confirmed by ledger",
		)
		r = self._rows()[0]
		self.assertEqual(r["result_class"], "confirmed_outcome")
		self.assertIn("recovered", r["detail_md"].lower())
		self.assertNotIn("[unverified]", r["detail_md"])

	def test_class_conditional_metadata_rides_on_each_row(self):
		"""A derived_candidate is no longer visually indistinguishable from an
		observed_fact: its confidence / match_basis / false_positive_path /
		confirmation_status ride on the read row for the SPA badge."""
		_mk_finding(
			self.user,
			self.SLUG,
			result_class="derived_candidate",
			confidence=80,
			match_basis="2B-match",
			false_positive_path="vendor alias",
			confirmation_status="unconfirmed",
			title="candidate mismatch",
			detail_md="a possible duplicate",
		)
		r = self._rows()[0]
		self.assertEqual(r["result_class"], "derived_candidate")
		self.assertEqual(r["match_basis"], "2B-match")
		self.assertEqual(r["false_positive_path"], "vendor alias")
		self.assertEqual(r["confirmation_status"], "unconfirmed")
		self.assertIn("confidence", r)


# --------------------------------------------------------------------------- #
# PP-6 — per-customer activation ceiling (finding #3)
# --------------------------------------------------------------------------- #
class TestPerCustomerCeiling(FrappeTestCase):
	A1 = PREFIX + "a1"
	A2 = PREFIX + "a2"
	B1 = PREFIX + "b1"
	B2 = PREFIX + "b2"
	C1 = PREFIX + "c1"
	ALL = (A1, A2, B1, B2, C1)

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.cust_a = _mk_user("h-cust-a@example.com")
		cls.rev_a = _mk_user("h-rev-a@example.com")
		cls.cust_b = _mk_user("h-cust-b@example.com")
		cls.rev_b = _mk_user("h-rev-b@example.com")
		cls.cust_c = _mk_user("h-cust-c@example.com")
		cls.rev_c = _mk_user("h-rev-c@example.com")
		for s in cls.ALL:
			_mk_listing(s)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		_wipe(list(self.ALL))
		# customer A + B each cover two packs (a reviewer of record on two distinct
		# agents); customer C covers only one pack.
		_mk_install(self.cust_a, self.A1, self.rev_a)
		_mk_install(self.cust_a, self.A2, self.rev_a)
		self.b1 = _mk_install(self.cust_b, self.B1, self.rev_b)
		self.b2 = _mk_install(self.cust_b, self.B2, self.rev_b)
		_mk_install(self.cust_c, self.C1, self.rev_c)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		_wipe(list(self.ALL))

	def test_raise_for_a_does_not_unlock_b(self):
		"""The core isolation property: raising customer A's ceiling to 2 leaves
		customer B at the default 1 — B's second promotion is still refused."""
		frappe.set_user("Administrator")
		agents_api.raise_activation_ceiling(self.cust_a, "A's reviewer covers two packs")

		self.assertEqual(agents_api._activation_ceiling(self.cust_a), 2)
		self.assertEqual(agents_api._activation_ceiling(self.cust_b), 1)

		# B promotes its first module (ok) but the second is refused — the A-grant
		# never leaked to B.
		frappe.set_user(self.rev_b)
		agents_api.promote_installation(self.b1.name)
		with self.assertRaises(frappe.ValidationError):
			agents_api.promote_installation(self.b2.name)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value(INSTALLATION, self.b2.name, "activation_state"), "shadow")

	def test_reviewer_capacity_gate_blocks_single_pack_customer(self):
		"""A raise for a customer whose reviewer covers only ONE pack is refused by
		the system-verified capacity gate (not just a free-text justification)."""
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			agents_api.raise_activation_ceiling(self.cust_c, "please just trust me")
		self.assertEqual(agents_api._activation_ceiling(self.cust_c), 1)

	def test_raise_requires_a_real_named_customer(self):
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			agents_api.raise_activation_ceiling("", "no customer named")


# --------------------------------------------------------------------------- #
# PP-6 — promotion budget TOCTOU serialization (finding #1)
# --------------------------------------------------------------------------- #
class TestPromotionLockSerialization(FrappeTestCase):
	SLUG = PREFIX + "lock"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.owner = _mk_user("h-lock-owner@example.com")
		cls.reviewer = _mk_user("h-lock-rev@example.com")
		_mk_listing(cls.SLUG)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		_wipe([self.SLUG])
		self.inst = _mk_install(self.owner, self.SLUG, self.reviewer)

	def tearDown(self):
		frappe.set_user("Administrator")
		_wipe([self.SLUG])

	def test_promotion_refused_when_activation_lock_unavailable(self):
		"""The budget check is serialized on a per-customer lock; when the lock is held
		elsewhere the promotion refuses rather than racing the read-check-flip window,
		and the row stays shadow."""
		frappe.set_user(self.reviewer)
		with patch("jarvis._redis_lock.redis_lock", _lock_denied):
			with self.assertRaises(frappe.ValidationError):
				agents_api.promote_installation(self.inst.name)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value(INSTALLATION, self.inst.name, "activation_state"), "shadow")

	def test_promotion_holds_the_per_owner_lock(self):
		"""The lock is keyed on the OWNER (customer), so all of a customer's activation
		changes serialize against each other."""
		seen = {}

		@contextmanager
		def _spy(name, **k):
			seen["name"] = name
			yield True

		frappe.set_user(self.reviewer)
		with patch("jarvis._redis_lock.redis_lock", _spy):
			agents_api.promote_installation(self.inst.name)
		frappe.set_user("Administrator")
		self.assertEqual(seen["name"], f"jarvis_agent_activation:{self.owner}")
		self.assertEqual(frappe.db.get_value(INSTALLATION, self.inst.name, "activation_state"), "live")
