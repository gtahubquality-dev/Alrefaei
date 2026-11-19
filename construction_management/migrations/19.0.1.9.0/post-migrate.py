"""Construction Management 19.0.1.9.0: the cost percentage of the BOQ items is computed from the estimated cost
(share of each item in the total estimated cost of its project, change orders included)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    items = env['construction.boq.item'].with_context(active_test=False).search([])
    env.add_to_compute(items._fields['cost_percent'], items)
    items.flush_recordset(['cost_percent'])
