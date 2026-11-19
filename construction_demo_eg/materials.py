"""Egyptian construction demo materials workflows."""

from datetime import timedelta
from odoo import Command, fields
from . import payments


def materials(builder, project, start, target, over_boq=False):
    """Transfers from the main warehouse and direct purchases (PO, receipt, vendor bill),
    in line with the progress of the works (a little ahead of the invoiced quantities)."""
    span = 60
    for requirement in project.material_requirement_ids:
        ratio = target * builder.context.rng.uniform(0.98, 1.06)
        transfer_qty = round(requirement.boq_quantity * ratio * 0.45, 2)
        purchase_qty = round(requirement.boq_quantity * ratio * 0.55, 2)
        if transfer_qty > 0:
            request = builder.context.env['construction.material.request'].create(
                {
                    'project_id': project.id,
                    'request_type': 'transfer',
                    'source_warehouse_id': builder.accounting.main_wh.id,
                    'date': start + timedelta(days=15),
                    'line_ids': [
                        Command.create({'requirement_id': requirement.id, 'quantity': transfer_qty})
                    ],
                }
            )
            request.action_submit()
            if request.state == 'to_approve':
                request.action_approve()
            request.action_process()
            validate_picking(request.picking_id)
        if purchase_qty > 0:
            if over_boq and requirement == project.material_requirement_ids[:1]:
                purchase_qty = round(requirement.boq_quantity - transfer_qty + 5, 2)
            vendor = requirement.product_id.seller_ids[:1].partner_id
            request = builder.context.env['construction.material.request'].create(
                {
                    'project_id': project.id,
                    'request_type': 'purchase',
                    'vendor_id': vendor.id,
                    'date': start + timedelta(days=min(45, span // 2)),
                    'line_ids': [
                        Command.create({'requirement_id': requirement.id, 'quantity': purchase_qty})
                    ],
                }
            )
            request.action_submit()
            if request.state == 'to_approve':
                request.action_approve()
            request.action_process()
            order = request.purchase_order_id
            order.write({'date_order': fields.Datetime.to_datetime(request.date)})
            order.button_confirm()
            for picking in order.picking_ids:
                validate_picking(picking)
            order.action_create_invoice()
            bill = order.invoice_ids.filtered(lambda m: m.state == 'draft')
            bill.write(
                {'invoice_date': request.date + timedelta(days=5), 'ref': f'INV-{order.name!s}'}
            )
            bill.action_post()
            if builder.context.rng.random() < 0.8:
                payments.pay(builder, bill, bill.invoice_date + timedelta(days=30))


def validate_picking(picking):
    """Validate picking."""
    picking = picking.sudo()
    if picking.state in ('done', 'cancel'):
        return
    if picking.state == 'draft':
        picking.action_confirm()
    picking.action_assign()
    for move in picking.move_ids:
        move.quantity = move.product_uom_qty
    picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
