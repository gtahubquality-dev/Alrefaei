"""Construction Management 19.0.1.8.0: project cost report.

Rental bills already recorded for equipment requests are charged to their request and BOQ equipment.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['account.move.line'].search([
        ('purchase_line_id', '!=', False), ('construction_cost_type', '=', False),
        '|', ('purchase_line_id.order_id.construction_equipment_request_id', '!=', False),
        ('purchase_line_id.order_id.construction_equipment_rental_id', '!=', False)])
    for line in lines:
        order = line.purchase_line_id.order_id
        request = order.construction_equipment_request_id or order.construction_equipment_rental_id.request_id
        line.write(request._get_cost_line_values() if request else {'construction_cost_type': 'equipment'})
    if lines:
        _logger.info("Construction Management: %s rental bill lines linked to their equipment request", len(lines))
