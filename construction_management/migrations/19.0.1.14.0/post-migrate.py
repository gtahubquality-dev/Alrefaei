"""Construction Management 19.0.1.14.0: remaining quantities of the invoice lines rounded (a rounding difference
showed lines in red as exceeding the BOQ)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    for model, field in (('construction.owner.invoice.line', 'remaining_quantity'),
                         ('construction.subcontract.invoice.line', 'remaining_quantity')):
        records = env[model].with_context(active_test=False).search([])
        env.add_to_compute(env[model]._fields[field], records)
    env.flush_all()
