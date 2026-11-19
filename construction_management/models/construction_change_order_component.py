"""Construction change order component for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import ValidationError

from .construction_boq import COMPONENT_TYPES
from .construction_common import apply_component_product, check_change_order_editable


class ConstructionChangeOrderComponent(models.Model):
    """Construction change order component."""

    _name = 'construction.change.order.component'
    _description = 'Change Order New Item Component'
    _order = 'line_id, component_type, id'

    line_id = fields.Many2one(
        'construction.change.order.line',
        string='Change Line',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(related='line_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='line_id.currency_id', string='Currency')
    component_type = fields.Selection(
        COMPONENT_TYPES, string='Component Type', required=True, default='material'
    )
    product_id = fields.Many2one('product.product', string='Product / Material')
    name = fields.Char(string='Description', required=True)
    quantity = fields.Float(string='Quantity', digits='Product Unit', default=1.0)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure')
    unit_cost = fields.Monetary(string='Unit Cost')
    total_cost = fields.Monetary(compute='_compute_total_cost', store=True, string='Total Cost')

    @api.depends('quantity', 'unit_cost')
    def _compute_total_cost(self):
        for component in self:
            component.total_cost = component.quantity * component.unit_cost

    @api.onchange('product_id')
    def _onchange_product_id(self):
        apply_component_product(self)

    def _check_change_order_editable(self, orders):
        """Lines of a submitted, approved or rejected change order are frozen: an approved change
        order is applied to the BOQ, it is changed by a new change order.
        """
        check_change_order_editable(self, orders)

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        records = super().create(vals_list)
        self._check_change_order_editable(records.line_id.order_id)
        return records

    def write(self, vals):
        """Write."""
        self._check_change_order_editable(self.line_id.order_id)
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_frozen_change_order(self):
        self._check_change_order_editable(
            self.line_id.order_id.filtered(lambda o: o.state != 'cancelled')
        )

    @api.constrains('component_type', 'product_id', 'quantity', 'unit_cost')
    def _check_values(self):
        for component in self:
            if component.component_type == 'material' and not component.product_id:
                raise ValidationError(
                    _('A product is required for material component %s.', component.name)
                )
            if component.quantity < 0 or component.unit_cost < 0:
                raise ValidationError(
                    _('Quantity and cost of component %s cannot be negative.', component.name)
                )
