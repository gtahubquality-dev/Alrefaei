"""Construction Equipment 19.0.1.4.0: equipment costs are charged to the equipment request and its BOQ equipment.

The usage logs and expenses already recorded are linked to their request (computed on upgrade); their posted
journal items receive the request, the BOQ equipment and the cost type so that they appear in the project
cost report.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    count = 0
    usages = env['construction.equipment.usage'].search([('state', '=', 'posted'), ('move_id', '!=', False)])
    for usage in usages:
        lines = usage.move_id.line_ids.filtered(lambda l: l.debit > 0 and not l.construction_cost_type)
        if lines:
            lines.write(usage._get_cost_line_values())
            count += len(lines)
    expenses = env['construction.equipment.expense'].search([('state', '=', 'billed'), ('move_id', '!=', False)])
    for expense in expenses:
        values = expense.request_id._get_cost_line_values() if expense.request_id \
            else {'construction_cost_type': 'equipment'}
        lines = expense.move_id.invoice_line_ids.filtered(lambda l: not l.construction_cost_type)
        if lines:
            lines.write(values)
            count += len(lines)
    if count:
        _logger.info("Construction Equipment: %s journal items linked to their equipment request", count)
