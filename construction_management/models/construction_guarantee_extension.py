"""Construction guarantee extension for construction management."""

from odoo import fields
from odoo import models


class ConstructionGuaranteeExtension(models.Model):
    """Construction guarantee extension."""

    _name = 'construction.guarantee.extension'
    _description = 'Guarantee Extension'
    _order = 'create_date desc, id desc'

    guarantee_id = fields.Many2one(
        'construction.guarantee', string='Guarantee', required=True, ondelete='cascade', index=True
    )
    company_id = fields.Many2one(related='guarantee_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='guarantee_id.currency_id', string='Currency')
    old_expiry_date = fields.Date(string='Previous Expiry', readonly=True)
    new_expiry_date = fields.Date(string='New Expiry', readonly=True)
    old_amount = fields.Monetary(string='Previous Amount', readonly=True)
    new_amount = fields.Monetary(string='New Amount', readonly=True)
    user_id = fields.Many2one('res.users', string='Responsible User', readonly=True)
    note = fields.Char(string='Notes', readonly=True)
