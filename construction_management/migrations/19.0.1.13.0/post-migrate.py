"""Construction Management 19.0.1.13.0: link of the supply documents to the BOQ items.

The transfers and purchase order lines already created from material requests are linked to their request
line, and the bills already posted are charged to the BOQ item of their purchase / subcontract line.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    requests = env['construction.material.request'].search(
        ['|', ('picking_id', '!=', False), ('purchase_order_id', '!=', False)])
    moves = po_lines = 0
    for request in requests:
        for move in request.picking_id.move_ids.filtered(lambda m: not m.construction_material_line_id):
            line = request.line_ids.filtered(lambda l, m=move: l.product_id == m.product_id)[:1]
            if line:
                move.construction_material_line_id = line
                moves += 1
        for po_line in request.purchase_order_id.order_line.filtered(
                lambda l: not l.construction_material_line_id and l.product_id):
            line = request.line_ids.filtered(lambda l, p=po_line: l.product_id == p.product_id)[:1]
            if line:
                po_line.construction_material_line_id = line
                po_lines += 1

    bill_lines = env['account.move.line'].search([
        ('purchase_line_id.construction_material_line_id', '!=', False),
        ('construction_boq_component_id', '=', False)])
    for line in bill_lines:
        po_line = line.purchase_line_id
        values = {'construction_cost_type': line.construction_cost_type or 'material'}
        if po_line.construction_boq_component_id:
            values['construction_boq_component_id'] = po_line.construction_boq_component_id.id
            values['construction_boq_item_id'] = po_line.construction_boq_item_id.id
        line.write(values)

    sub_lines = 0
    for invoice in env['construction.subcontract.invoice'].search([('move_id', '!=', False)]):
        for move_line in invoice.move_id.line_ids.filtered(
                lambda l: l.construction_boq_item_id and not l.construction_boq_component_id):
            contract_line = invoice.contract_id.line_ids.filtered(
                lambda l, m=move_line: l.boq_item_id == m.construction_boq_item_id and l.boq_component_id)[:1]
            if contract_line:
                move_line.construction_boq_component_id = contract_line.boq_component_id
                sub_lines += 1
    _logger.info("Construction Management: %s transfer moves, %s purchase lines, %s bill lines and %s subcontractor "
                 "bill lines linked to the BOQ", moves, po_lines, len(bill_lines), sub_lines)
