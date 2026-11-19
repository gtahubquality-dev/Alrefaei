"""Construction boq component construction boq for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError

from .construction_boq import COMPONENT_TYPES
from .construction_common import apply_component_product
from .runtime import model_attribute


class ConstructionBoqComponent(models.Model):
    """Construction boq component."""

    _name = 'construction.boq.component'
    _description = 'Construction BOQ Cost Component'
    _order = 'item_id, component_type, sequence, id'

    item_id = fields.Many2one(
        'construction.boq.item', string='BOQ Item', required=True, ondelete='cascade', index=True
    )
    project_id = fields.Many2one(
        related='item_id.project_id', store=True, index=True, string='Project'
    )
    company_id = fields.Many2one(related='item_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='item_id.currency_id', string='Currency')
    sequence = fields.Integer(default=10)
    component_type = fields.Selection(
        COMPONENT_TYPES, string='Component Type', required=True, default='material'
    )
    product_id = fields.Many2one('product.product', string='Product / Material')
    name = fields.Char(string='Description', required=True)
    specifications = fields.Text(string='Specifications')
    quantity = fields.Float(
        string='Approved Quantity',
        digits='Product Unit',
        default=1.0,
        help="Quantity required for the original item quantity.",
    )
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure')
    unit_cost = fields.Monetary(string='Unit Cost')
    total_cost = fields.Monetary(
        compute='_compute_effective', store=True, string='Approved Total Cost'
    )
    effective_quantity = fields.Float(
        string='Current Quantity',
        digits='Product Unit',
        compute='_compute_effective',
        store=True,
        help=(
            "Quantity adjusted to the current BOQ item quantity (including approved change orders)."
        ),
    )
    effective_cost = fields.Monetary(
        compute='_compute_effective', store=True, string='Current Total Cost'
    )

    @api.depends('quantity', 'unit_cost', 'item_id.quantity', 'item_id.total_quantity')
    def _compute_effective(self):
        for component in self:
            item = component.item_id
            ratio = item.total_quantity / item.quantity if item.quantity else 1.0
            component.total_cost = component.quantity * component.unit_cost
            component.effective_quantity = component.quantity * ratio
            component.effective_cost = component.effective_quantity * component.unit_cost

    @api.depends('name', 'item_id.code', 'item_id.name')
    def _compute_display_name(self):
        for component in self:
            item = component.item_id
            prefix = (item.code or item.name) if item else ''
            component.display_name = (
                f'{prefix} / {component.name or ""}' if prefix else (component.name or '')
            )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        apply_component_product(self)

    @api.constrains('quantity', 'unit_cost')
    def _check_values(self):
        for component in self:
            if component.quantity < 0 or component.unit_cost < 0:
                raise ValidationError(
                    _('Quantity and cost of component %s cannot be negative.', component.name)
                )

    @api.constrains('component_type', 'product_id')
    def _check_material_product(self):
        for component in self:
            if component.component_type == 'material' and not component.product_id:
                raise ValidationError(
                    _('A product is required for material component %s.', component.name)
                )

    LOCKED_FIELDS = {'quantity', 'product_id', 'uom_id', 'unit_cost', 'component_type', 'item_id'}

    def _check_boq_unlocked(self):
        if self.env.su:
            return
        for component in self:
            if model_attribute(component.item_id.project_id, '_is_boq_locked')():
                raise UserError(
                    _(
                        'Approved BOQ components of project %s are locked: change them with a'
                        ' change order.',
                        component.item_id.project_id.display_name,
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        components = super().create(vals_list)
        model_attribute(components, '_check_boq_unlocked')()
        return components

    def write(self, vals):
        """Write."""
        if self.LOCKED_FIELDS.intersection(vals):
            self._check_boq_unlocked()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_locked_boq(self):
        self._check_boq_unlocked()
