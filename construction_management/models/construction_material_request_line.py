"""Construction material request line for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.tools import float_compare

from .runtime import model_attribute


class ConstructionMaterialRequestLine(models.Model):
    """Construction material request line."""

    _name = 'construction.material.request.line'
    _description = 'Material Request Line'
    _order = 'request_id, id'

    request_id = fields.Many2one(
        'construction.material.request',
        string='Request',
        required=True,
        ondelete='cascade',
        index=True,
    )
    project_id = fields.Many2one(related='request_id.project_id', store=True, string='Project')
    company_id = fields.Many2one(related='request_id.company_id', store=True, string='Company')
    requirement_id = fields.Many2one(
        'construction.material.requirement',
        string='BOQ Material',
        required=True,
        domain="[('project_id', '=', project_id)]",
        ondelete='restrict',
    )
    product_id = fields.Many2one(
        related='requirement_id.product_id', store=True, string='Product', index=True
    )
    uom_id = fields.Many2one(related='requirement_id.uom_id', store=True, string='Unit')
    boq_quantity = fields.Float(related='requirement_id.boq_quantity', string='BOQ Quantity')
    remaining_quantity = fields.Float(
        related='requirement_id.remaining_quantity', string='Remaining BOQ Quantity'
    )
    available_quantity = fields.Float(
        compute='_compute_available', digits='Product Unit', string='Available Quantity'
    )
    quantity = fields.Float(
        string='Requested Quantity', digits='Product Unit', required=True, default=1.0
    )
    exceeds_boq = fields.Boolean(compute='_compute_available', string='Exceeds BOQ')

    @api.depends('quantity', 'requirement_id', 'request_id.state')
    def _compute_available(self):
        for line in self:
            requirement = line.requirement_id
            available = requirement.available_quantity
            if (
                line.request_id.state in ('to_approve', 'approved')
                and model_attribute(line, '_origin').id
            ):
                available += line.quantity
            line.available_quantity = available
            line.exceeds_boq = float_compare(line.quantity, available, precision_digits=4) > 0

    def write(self, vals):
        """Write."""
        if {'quantity', 'requirement_id'}.intersection(vals):
            for line in self:
                if line.request_id.state != 'draft':
                    raise UserError(_('Lines can only be modified on draft requests.'))
        return super().write(vals)
