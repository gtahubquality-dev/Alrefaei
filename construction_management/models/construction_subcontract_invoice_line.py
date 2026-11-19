"""Construction subcontract invoice line for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.tools import float_round

from .construction_common import invoice_field


class ConstructionSubcontractInvoiceLine(models.Model):
    """Construction subcontract invoice line."""

    _name = 'construction.subcontract.invoice.line'
    _description = 'Subcontractor Invoice Line'
    _order = 'invoice_id, id'

    invoice_id = invoice_field()
    contract_id = fields.Many2one(related='invoice_id.contract_id', store=True, string='Contract')
    company_id = fields.Many2one(related='invoice_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='invoice_id.currency_id', string='Currency')
    contract_line_id = fields.Many2one(
        'construction.subcontract.line',
        string='Contract Item',
        required=True,
        domain="[('contract_id', '=', contract_id)]",
        ondelete='restrict',
    )
    uom_id = fields.Many2one(related='contract_line_id.uom_id', string='Unit of Measure')
    contract_quantity = fields.Float(
        related='contract_line_id.quantity', string='Contract Quantity'
    )
    unit_price = fields.Monetary(
        compute='_compute_unit_price',
        store=True,
        string='Unit Price',
        help=(
            "Contract unit price when the invoice was approved by the site: an amendment changes"
            " the price of the next invoices, not of the approved ones."
        ),
    )
    previous_quantity = fields.Float(
        string='Previous Quantity', digits='Product Unit', readonly=True
    )
    current_quantity = fields.Float(string='Current Quantity', digits='Product Unit')
    remaining_quantity = fields.Float(
        compute='_compute_amount', store=True, digits='Product Unit', string='Remaining Quantity'
    )
    amount = fields.Monetary(compute='_compute_amount', store=True, string='Amount')

    @api.depends('contract_line_id.unit_price', 'invoice_id.state')
    def _compute_unit_price(self):
        for line in self:
            if line.invoice_id.state in ('draft', 'rejected') or not line.unit_price:
                line.unit_price = line.contract_line_id.unit_price
            else:
                line.unit_price = line.unit_price

    @api.depends('current_quantity', 'previous_quantity', 'unit_price', 'contract_line_id.quantity')
    def _compute_amount(self):
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        for line in self:
            line.amount = line.current_quantity * line.unit_price
            line.remaining_quantity = float_round(
                line.contract_line_id.quantity - line.previous_quantity - line.current_quantity,
                precision_digits=precision,
            )

    def write(self, vals):
        """Write."""
        if {'current_quantity', 'contract_line_id'}.intersection(vals):
            for line in self:
                if line.invoice_id.state not in ('draft', 'rejected'):
                    raise UserError(_('Lines can only be modified on draft invoices.'))
        return super().write(vals)

    _contract_line_uniq = models.Constraint(
        'unique(invoice_id, contract_line_id)',
        'Each contract item can only appear once per invoice.',
    )
