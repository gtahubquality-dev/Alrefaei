"""Construction Management 19.0.1.15.0: the weight of the BOQ items is computed from their estimated cost
(estimated cost of the item / total estimated cost of the BOQ)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Item = env['construction.boq.item']
    items = Item.with_context(active_test=False).search([])
    env.add_to_compute(Item._fields['weight_percent'], items)
    env.add_to_compute(Item._fields['cost_percent'], items)
    env.flush_all()
