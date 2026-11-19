"""Construction material request line construction boq consumption for construction management."""

from odoo import api
from odoo import fields
from odoo import models

from .boq_consumption_common import boq_component_field, done_stock_moves
from .runtime import model_attribute


class ConstructionMaterialRequestLine(models.Model):
    """Construction material request line."""

    _inherit = 'construction.material.request.line'

    boq_component_id = boq_component_field(
        'For BOQ Item',
        domain=(
            "[('project_id', '=', project_id), ('component_type', '=', 'material'), "
            "('product_id', '=', product_id)]"
        ),
        help_text=(
            "BOQ item this material is requested for. Filled automatically when the material is"
            " used by a single BOQ item; when left empty, the quantities are spread over the BOQ"
            " items using this material in proportion to their BOQ quantities."
        ),
    )
    boq_item_id = fields.Many2one(related='boq_component_id.item_id', store=True, string='BOQ Item')
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    purchased_quantity = fields.Float(
        compute='_compute_supply',
        digits='Product Unit',
        string='Purchased',
        help="Quantity of the confirmed purchase order of the request, in the unit of the request.",
    )
    received_quantity = fields.Float(
        compute='_compute_supply',
        digits='Product Unit',
        string='Received',
        help=(
            "Quantity actually received in the project warehouse (purchase receipts or transfers"
            " done), net of the returns, in the unit of the request."
        ),
    )
    billed_quantity = fields.Float(
        compute='_compute_supply',
        digits='Product Unit',
        string='Billed',
        help=(
            "Quantity of the posted vendor bills (credit notes deducted), in the unit of the"
            " request."
        ),
    )
    actual_cost = fields.Monetary(
        compute='_compute_supply',
        string='Actual Cost',
        help=(
            "Purchases: amount of the posted vendor bills (credit notes deducted). Transfers: value"
            " of the quantities transferred to the project warehouse (net of the returns)."
        ),
    )

    @api.depends(
        'request_id.state', 'request_id.purchase_order_id', 'request_id.picking_id', 'quantity'
    )
    def _compute_supply(self):
        """Compute purchased, received and billed quantities and actual cost."""
        lines = self.filtered('id')
        (self - lines).update(
            {
                'purchased_quantity': 0.0,
                'received_quantity': 0.0,
                'billed_quantity': 0.0,
                'actual_cost': 0.0,
            }
        )
        if not lines:
            return
        values = {line.id: [0.0, 0.0, 0.0, 0.0] for line in lines}
        line_ids = lines.ids
        self._accumulate_purchase_supply(line_ids, values)
        self._accumulate_transfer_supply(line_ids, values)
        for line in lines:
            (
                line.purchased_quantity,
                line.received_quantity,
                line.billed_quantity,
                line.actual_cost,
            ) = values[line.id]

    def _accumulate_purchase_supply(self, line_ids, values):
        """Add confirmed order quantities and posted vendor bills and refunds."""
        order_lines = (
            self.env['purchase.order.line']
            .sudo()
            .search(
                [
                    ('construction_material_line_id', 'in', line_ids),
                    ('order_id.state', 'in', ('purchase', 'done')),
                ]
            )
        )
        for order_line in order_lines:
            line = order_line.construction_material_line_id
            uom = line.uom_id or order_line.product_uom_id
            data = values[line.id]
            for index, quantity in enumerate((order_line.product_qty, order_line.qty_received)):
                data[index] += model_attribute(order_line.product_uom_id, '_compute_quantity')(
                    quantity, uom, round=False, raise_if_failure=False
                )
            for bill_line in order_line.invoice_lines.filtered(
                lambda l: l.parent_state == 'posted' and l.display_type == 'product'
            ):
                sign = -1.0 if bill_line.move_id.move_type == 'in_refund' else 1.0
                bill_uom = bill_line.product_uom_id or order_line.product_uom_id
                data[2] += sign * model_attribute(bill_uom, '_compute_quantity')(
                    bill_line.quantity, uom, round=False, raise_if_failure=False
                )
                data[3] += bill_line.balance

    def _accumulate_transfer_supply(self, line_ids, values):
        """Add completed non-purchase moves and subtract their returns."""
        moves = done_stock_moves(
            self.env,
            [
                ('purchase_line_id', '=', False),
                '|',
                ('construction_material_line_id', 'in', line_ids),
                ('origin_returned_move_id.construction_material_line_id', 'in', line_ids),
            ],
        )
        for move in moves:
            origin = (
                move.origin_returned_move_id
                if move.origin_returned_move_id.construction_material_line_id
                else move
            )
            line = origin.construction_material_line_id
            if line.id not in values:
                continue
            sign = -1.0 if origin != move else 1.0
            uom = line.uom_id or move.product_uom
            values[line.id][1] += sign * model_attribute(move.product_uom, '_compute_quantity')(
                move.quantity, uom, round=False, raise_if_failure=False
            )
            value = (
                abs(move.value)
                if 'value' in move._fields and move.value
                else model_attribute(move.product_uom, '_compute_quantity')(
                    move.quantity, move.product_id.uom_id, round=False
                )
                * move.product_id.with_company(move.company_id).standard_price
            )
            values[line.id][3] += sign * value

    @api.depends('requirement_id')
    def _compute_boq_component_id(self):
        component_model = self.env['construction.boq.component'].sudo()
        for line in self:
            product = line.requirement_id.product_id
            if line.boq_component_id and line.boq_component_id.product_id == product:
                line.boq_component_id = line.boq_component_id
                continue
            project = line.requirement_id.project_id
            components = (
                component_model.search(
                    [
                        ('project_id', '=', project.id),
                        ('component_type', '=', 'material'),
                        ('product_id', '=', product.id),
                    ],
                    limit=2,
                )
                if project and product
                else component_model
            )
            line.boq_component_id = components if len(components) == 1 else False
