"""Latency telemetry logger (2026-07 latency plan, Phase 0).

One place that hands out the ``jarvis.chat.latency`` logger with its level
pinned to INFO. ``frappe.logger`` defaults to ERROR (WARNING on a dev
server), which would silently drop every telemetry line — these lines are
the measurement harness for the chat-latency work, so they must be visible
on any bench without asking operators to flip ``frappe.log_level``. The
logger writes to its own file (``logs/jarvis.chat.latency.log``), so INFO
here does not make any other logger chattier.
"""

import logging

import frappe


def get_logger() -> logging.Logger:
	logger = frappe.logger("jarvis.chat.latency", allow_site=True)
	if logger.level == 0 or logger.level > logging.INFO:
		logger.setLevel(logging.INFO)
	return logger
