"""Construction owner invoice line for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError
from odoo.tools import float_round

from .construction_common import owner_invoice_field


class ConstructionOwnerInvoiceLine(models.Model):
    """Construction owner invoice line."""

    _name = 'construction.owner.invoice.line'
    _description = 'Owner Invoice Line'
    _order = 'invoice_id, sequence, id'

    invoice_id = owner_invoice_field()
    invoice_state = fields.Selection(
        related='invoice_id.state', store=True, string='Invoice Status'
    )
    project_id = fields.Many2one(related='invoice_id.project_id', store=True, string='Project')
    company_id = fields.Many2one(related='invoice_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='invoice_id.currency_id', string='Currency')
    sequence = fields.Integer(default=10)
    boq_item_id = fields.Many2one(
        'construction.boq.item',
        string='Item',
        required=True,
        index=True,
        domain="[('project_id', '=', project_id)]",
        ondelete='restrict',
    )
    description = fields.Text(related='boq_item_id.description', string='Contractual Description')
    uom_id = fields.Many2one(related='boq_item_id.uom_id', string='Unit of Measure')
    boq_quantity = fields.Float(string='BOQ Quantity', digits='Product Unit', readonly=True)
    contract_price = fields.Monetary(string='Contract Unit Price', readonly=True)
    unit_price = fields.Monetary(string='Unit Price')
    previous_quantity = fields.Float(
        string='Previous Quantity', digits='Product Unit', readonly=True
    )
    previous_amount = fields.Monetary(string='Previous Amount', readonly=True)
    current_quantity = fields.Float(string='Current Quantity', digits='Product Unit')
    cumulative_quantity = fields.Float(
        compute='_compute_line', store=True, digits='Product Unit', string='Cumulative Quantity'
    )
    remaining_quantity = fields.Float(
        compute='_compute_line', store=True, digits='Product Unit', string='Remaining Quantity'
    )
    amount_current = fields.Monetary(compute='_compute_line', store=True, string='Current Amount')
    amount_cumulative = fields.Monetary(
        compute='_compute_line', store=True, string='Cumulative Amount'
    )
    price_increase_percent = fields.Float(
        compute='_compute_line', store=True, string='Price Increase (%)'
    )

    @api.depends(
        'boq_quantity',
        'previous_quantity',
        'current_quantity',
        'unit_price',
        'contract_price',
        'previous_amount',
    )
    def _compute_line(self):
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        for line in self:
            line.cumulative_quantity = line.previous_quantity + line.current_quantity

            line.remaining_quantity = float_round(
                line.boq_quantity - line.cumulative_quantity, precision_digits=precision
            )
            line.amount_current = line.current_quantity * line.unit_price
            line.amount_cumulative = line.previous_amount + line.amount_current
            if line.contract_price > 0:
                line.price_increase_percent = (
                    (line.unit_price - line.contract_price) / line.contract_price * 100.0
                )
            elif line.unit_price > 0:
                line.price_increase_percent = 100.0
            else:
                line.price_increase_percent = 0.0

    @api.onchange('boq_item_id')
    def _onchange_boq_item_id(self):
        for line in self:
            if line.boq_item_id:
                line.boq_quantity = line.boq_item_id.total_quantity
                line.contract_price = line.boq_item_id.unit_price
                line.unit_price = line.boq_item_id.unit_price

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        item_model = self.env['construction.boq.item']
        for vals in vals_list:
            item = item_model.browse(vals.get('boq_item_id'))
            if item.exists():
                vals['boq_quantity'] = item.total_quantity
                vals['contract_price'] = item.unit_price
                if 'unit_price' not in vals:
                    vals['unit_price'] = item.unit_price
        lines = super().create(vals_list)
        for line in lines:
            if line.boq_item_id.project_id != line.invoice_id.project_id:
                raise ValidationError(
                    _(
                        'BOQ item %s does not belong to the invoice project.',
                        line.boq_item_id.display_name,
                    )
                )
        return lines

    def write(self, vals):
        """Write."""
        if {'current_quantity', 'unit_price', 'boq_item_id'}.intersection(vals):
            for line in self:
                if line.invoice_state != 'draft':
                    raise UserError(
                        _(
                            'Lines of owner invoice %s can only be modified in draft.',
                            line.invoice_id.name,
                        )
                    )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_owner_invoice_line(self):
        for line in self:
            if line.invoice_state not in ('draft', 'cancelled', False):
                raise UserError(_('Lines can only be removed from draft owner invoices.'))

    _boq_item_uniq = models.Constraint(
        'unique(invoice_id, boq_item_id)', 'Each BOQ item can only appear once per owner invoice.'
    )
