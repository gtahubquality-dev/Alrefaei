"""Construction boq component construction boq consumption for construction management."""

from odoo import fields
from odoo import models


class ConstructionBoqComponentRental(models.Model):
    """Construction boq component rental."""

    _inherit = 'construction.boq.component'

    rental_contract_ids = fields.One2many(
        'construction.equipment.rental', 'boq_component_id', string='Rental Contracts'
    )
