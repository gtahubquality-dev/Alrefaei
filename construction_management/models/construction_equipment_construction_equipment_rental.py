"""Construction equipment construction equipment rental for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import ValidationError


class ConstructionEquipment(models.Model):
    """Construction equipment."""

    _inherit = 'construction.equipment'

    rental_contract_ids = fields.One2many(
        'construction.equipment.rental', 'equipment_id', string='Rental Contracts'
    )
    rental_contract_count = fields.Integer(
        compute='_compute_rental_contract_count', string='Rentals'
    )
    running_rental_id = fields.Many2one(
        'construction.equipment.rental',
        compute='_compute_rental_contract_count',
        string='Running Rental',
    )

    def _compute_rental_contract_count(self):
        for equipment in self:
            rentals = equipment.sudo().rental_contract_ids
            equipment.rental_contract_count = len(rentals)
            equipment.running_rental_id = rentals.filtered(lambda r: r.state == 'running')[:1]

    @api.constrains('ownership')
    def _check_ownership_rentals(self):
        for equipment in self.filtered(lambda e: e.ownership == 'owned'):
            if equipment.sudo().rental_contract_ids.filtered(
                lambda r: r.state in ('running', 'returned')
            ):
                raise ValidationError(
                    _(
                        '%s has rental contracts: it cannot become company owned.',
                        equipment.display_name,
                    )
                )

    def action_view_rentals(self):
        """View rentals."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rental Contracts'),
            'res_model': 'construction.equipment.rental',
            'view_mode': 'list,form',
            'domain': [('equipment_id', '=', self.id)],
            'context': {
                'default_equipment_id': self.id,
                'default_partner_id': self.rental_vendor_id.id,
            },
        }
