"""Construction subcontract line for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError

from .construction_common import contract_field


class ConstructionSubcontractLine(models.Model):
    """Construction subcontract line."""

    _name = 'construction.subcontract.line'
    _description = 'Subcontract Assigned BOQ Item'
    _order = 'contract_id, sequence, id'

    contract_id = contract_field()
    contract_state = fields.Selection(
        related='contract_id.state', store=True, string='Contract Status'
    )
    project_id = fields.Many2one(related='contract_id.project_id', store=True, string='Project')
    company_id = fields.Many2one(related='contract_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='contract_id.currency_id', string='Currency')
    sequence = fields.Integer(default=10)
    boq_item_id = fields.Many2one(
        'construction.boq.item',
        string='BOQ Item',
        required=True,
        index=True,
        domain="[('project_id', '=', project_id)]",
        ondelete='restrict',
    )
    name = fields.Char(string='Work Description')
    uom_id = fields.Many2one(related='boq_item_id.uom_id', string='Unit of Measure')
    boq_quantity = fields.Float(related='boq_item_id.total_quantity', string='BOQ Quantity')
    quantity = fields.Float(
        string='Assigned Quantity', digits='Product Unit', required=True, default=1.0
    )
    unit_price = fields.Monetary(string='Subcontract Unit Price')
    amount = fields.Monetary(compute='_compute_amount', store=True, string='Amount')
    invoice_line_ids = fields.One2many(
        'construction.subcontract.invoice.line', 'contract_line_id', string='Invoice Lines'
    )
    invoiced_quantity = fields.Float(
        compute='_compute_invoiced_quantity', digits='Product Unit', string='Invoiced Quantity'
    )

    @api.depends('quantity', 'unit_price')
    def _compute_amount(self):
        for line in self:
            line.amount = line.quantity * line.unit_price

    def _compute_invoiced_quantity(self):
        for line in self:
            lines = line.invoice_line_ids.filtered(
                lambda l: l.invoice_id.state == 'finance_approved'
            )
            line.invoiced_quantity = sum(lines.mapped('current_quantity'))

    @api.onchange('boq_item_id')
    def _onchange_boq_item_id(self):
        for line in self:
            if line.boq_item_id:
                line.name = line.boq_item_id.display_name
                remaining = (
                    line.boq_item_id.total_quantity - line.boq_item_id.subcontracted_quantity
                )
                line.quantity = max(remaining, 0.0)
                total = line.boq_item_id.total_quantity
                line.unit_price = line.boq_item_id.subcontract_cost / total if total else 0.0

    @api.constrains('unit_price')
    def _check_price(self):
        for line in self:
            if line.unit_price < 0:
                raise ValidationError(_('Unit price cannot be negative.'))

    def write(self, vals):
        """Write."""
        if {'quantity', 'unit_price', 'boq_item_id', 'boq_component_id'}.intersection(
            vals
        ) and not self.env.su:
            for line in self:
                if line.contract_state not in ('draft', False):
                    raise UserError(
                        _(
                            'Assigned items of an approved contract are changed through a contract '
                            'amendment.'
                        )
                    )
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        lines = super().create(vals_list)
        if not self.env.su:
            for line in lines:
                if line.contract_state not in ('draft', False):
                    raise UserError(
                        _(
                            'Items cannot be added to an approved contract directly. Use a contract'
                            ' amendment.'
                        )
                    )
        return lines

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_subcontract_line(self):
        for line in self:
            if line.contract_state not in ('draft', False):
                raise UserError(
                    _(
                        'Items of an approved contract cannot be removed. Use a contract amendment'
                        ' to reduce their quantity.'
                    )
                )
