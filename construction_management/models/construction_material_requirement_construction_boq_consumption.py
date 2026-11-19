"""Construction material requirement construction boq consumption for construction management."""

from odoo import _
from odoo import api
from odoo import models


class ConstructionMaterialRequirement(models.Model):
    """Construction material requirement."""

    _inherit = 'construction.material.requirement'
    _rec_names_search = ['product_id.name', 'product_id.default_code']

    @api.depends('product_id', 'uom_id')
    def _compute_display_name(self):
        for requirement in self:
            requirement.display_name = requirement.product_id.display_name or _('New')
