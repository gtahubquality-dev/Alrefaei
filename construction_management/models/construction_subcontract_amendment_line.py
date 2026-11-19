"""Construction subcontract amendment line for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError


class ConstructionSubcontractAmendmentLine(models.Model):
    """Construction subcontract amendment line."""

    _name = 'construction.subcontract.amendment.line'
    _description = 'Subcontract Amendment Line'
    _order = 'amendment_id, id'

    amendment_id = fields.Many2one(
        'construction.subcontract.amendment',
        string='Amendment',
        required=True,
        ondelete='cascade',
        index=True,
    )
    contract_id = fields.Many2one(related='amendment_id.contract_id', string='Contract')
    project_id = fields.Many2one(related='amendment_id.project_id', string='Project')
    company_id = fields.Many2one(related='amendment_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='amendment_id.currency_id', string='Currency')
    state = fields.Selection(related='amendment_id.state', string='Status')
    change_type = fields.Selection(
        [
            ('change', 'Change an Assigned Item'),
            ('new', 'Assign a New BOQ Item'),
        ],
        string='Change Type',
        required=True,
        default='change',
    )
    contract_line_id = fields.Many2one(
        'construction.subcontract.line',
        string='Contract Item',
        domain="[('contract_id', '=', contract_id)]",
    )
    boq_item_id = fields.Many2one(
        'construction.boq.item', string='BOQ Item', domain="[('project_id', '=', project_id)]"
    )
    name = fields.Char(string='Work Description')
    current_quantity = fields.Float(related='contract_line_id.quantity', string='Current Quantity')
    current_unit_price = fields.Monetary(
        related='contract_line_id.unit_price', string='Current Unit Price'
    )
    quantity_change = fields.Float(
        string='Quantity Change',
        digits='Product Unit',
        help=(
            "Increase (positive) or decrease (negative) of the assigned quantity. "
            "For a new item: the assigned quantity."
        ),
    )
    new_unit_price = fields.Monetary(
        string='New Unit Price', help="Leave empty to keep the current price of an assigned item."
    )
    previous_quantity = fields.Float(
        string='Quantity Before Approval', digits='Product Unit', readonly=True
    )
    previous_unit_price = fields.Monetary(string='Price Before Approval', readonly=True)
    value_change = fields.Monetary(
        compute='_compute_value_change', store=True, string='Value Change'
    )

    @api.depends(
        'change_type',
        'quantity_change',
        'new_unit_price',
        'contract_line_id.quantity',
        'contract_line_id.unit_price',
        'amendment_id.state',
        'previous_quantity',
        'previous_unit_price',
    )
    def _compute_value_change(self):
        for line in self:
            if line.change_type == 'new':
                line.value_change = line.quantity_change * line.new_unit_price
            elif line.state == 'approved':
                old = line.previous_quantity * line.previous_unit_price
                new = (line.previous_quantity + line.quantity_change) * (
                    line.new_unit_price or line.previous_unit_price
                )
                line.value_change = new - old
            else:
                contract_line = line.contract_line_id
                price = line.new_unit_price or contract_line.unit_price
                line.value_change = (
                    contract_line.quantity + line.quantity_change
                ) * price - contract_line.quantity * contract_line.unit_price

    @api.onchange('boq_item_id')
    def _onchange_boq_item_id(self):
        for line in self:
            if line.boq_item_id and line.change_type == 'new':
                line.name = line.boq_item_id.display_name
                remaining = (
                    line.boq_item_id.total_quantity - line.boq_item_id.subcontracted_quantity
                )
                line.quantity_change = max(remaining, 0.0)

    def write(self, vals):
        """Write."""
        if (
            not self.env.su
            and self.filtered(lambda l: l.amendment_id.state not in ('draft', False))
            and {
                'quantity_change',
                'new_unit_price',
                'contract_line_id',
                'boq_item_id',
                'change_type',
            }.intersection(vals)
        ):
            raise UserError(_('Lines can only be modified on draft amendments.'))
        return super().write(vals)
