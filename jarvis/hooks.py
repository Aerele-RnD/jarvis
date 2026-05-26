app_name = "jarvis"
app_title = "Jarvis"
app_publisher = "Aerele"
app_description = "AI superpowers for Frappe/ERPNext"
app_email = "navin@aerele.in"
app_license = "MIT"

# ---------------------------------------------------------------------------
# Deployment constants
# ---------------------------------------------------------------------------
# Default URL of the Jarvis Cloud control plane the customer bench targets
# for signup, billing, plan list, container connection, and account summary.
# A per-customer override at ``Jarvis Settings.jarvis_admin_url`` wins; this
# is the bench-wide fallback for fresh installs.
#
# Rebranding the deployment? Change this string + ship a new release.
# (Re-exported by ``jarvis.admin_client`` so existing imports keep working.)
DEFAULT_ADMIN_URL = "https://admin.jarvis.aerele.in"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "jarvis",
# 		"logo": "/assets/jarvis/logo.png",
# 		"title": "Jarvis",
# 		"route": "/jarvis",
# 		"has_permission": "jarvis.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/jarvis/css/jarvis.css"
# app_include_js = "/assets/jarvis/js/jarvis.js"

# include js, css files in header of web template
# web_include_css = "/assets/jarvis/css/jarvis.css"
# web_include_js = "/assets/jarvis/js/jarvis.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "jarvis/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "jarvis/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "jarvis.utils.jinja_methods",
# 	"filters": "jarvis.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "jarvis.install.before_install"
# after_install = "jarvis.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "jarvis.uninstall.before_uninstall"
# after_uninstall = "jarvis.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "jarvis.utils.before_app_install"
# after_app_install = "jarvis.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "jarvis.utils.before_app_uninstall"
# after_app_uninstall = "jarvis.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "jarvis.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "jarvis.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

scheduler_events = {
	"cron": {
		"*/5 * * * *": [
			"jarvis.chat.stale_scan.scan_and_mark_errored",
		],
	},
	"daily": [
		"jarvis.onboarding.sync_connection",
	],
}

# Testing
# -------

# before_tests = "jarvis.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "jarvis.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "jarvis.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "jarvis.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["jarvis.utils.before_request"]
# after_request = ["jarvis.utils.after_request"]

# Job Events
# ----------
# before_job = ["jarvis.utils.before_job"]
# after_job = ["jarvis.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"jarvis.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
export_python_type_annotations = True

# Require all whitelisted methods to have type annotations
require_type_annotated_api_methods = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

