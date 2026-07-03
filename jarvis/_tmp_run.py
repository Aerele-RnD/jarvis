import sys, frappe
frappe.init(site="jarvis.localhost", sites_path="/home/vignesh/frappe-bench/sites")
frappe.connect()
frappe.set_user("Administrator")
fn = sys.argv[1] if len(sys.argv) > 1 else "probe_toolsurface"
from jarvis import _tmp_probe
getattr(_tmp_probe, fn)()
