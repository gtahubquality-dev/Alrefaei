"""Construction bidding bidding boq component support."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import ValidationError
from .bidding_boq import COMPONENT_TYPES


class BiddingBoqComponent(models.Model):
    """Bidding Boq Component."""

    _name = 'bidding.boq.component'
    _description = 'Bidding BOQ Cost Component'
    _order = 'item_id, component_type, sequence, id'

    item_id = fields.Many2one(
        'bidding.boq.item', string='BOQ Item', required=True, ondelete='cascade', index=True)
    tender_id = fields.Many2one(
        related='item_id.tender_id', store=True, string='Tender', index=True)
    company_id = fields.Many2one(related='item_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='item_id.currency_id', string='Currency')
    sequence = fields.Integer(default=10)
    component_type = fields.Selection(
        COMPONENT_TYPES, string='Component Type', required=True, default='material')
    product_id = fields.Many2one('product.product', string='Product / Material')
    name = fields.Char(string='Description', required=True)
    specifications = fields.Text(string='Specifications')
    quantity = fields.Float(string='Quantity / Hours', digits='Product Unit', default=1.0)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure')
    unit_cost = fields.Monetary(string='Estimated Unit Cost')
    total_cost = fields.Monetary(
        string='Total Estimated Cost', compute='_compute_total_cost', store=True)

    @api.depends('quantity', 'unit_cost')
    def _compute_total_cost(self):
        for component in self:
            component.total_cost = component.quantity * component.unit_cost

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for component in self:
            if component.product_id:
                component.name = component.product_id.display_name
                component.uom_id = component.product_id.uom_id
                if not component.unit_cost:
                    component.unit_cost = component.product_id.standard_price

    @api.constrains('quantity', 'unit_cost')
    def _check_values(self):
        for component in self:
            if component.quantity < 0 or component.unit_cost < 0:
                raise ValidationError(_(
                    'Quantity and cost of component %s cannot be negative.', component.name))

    @api.constrains('component_type', 'product_id')
    def _check_material_product(self):
        for component in self:
            if component.component_type == 'material' and not component.product_id:
                raise ValidationError(_('A product is required for material component %s.',
                    component.name))
