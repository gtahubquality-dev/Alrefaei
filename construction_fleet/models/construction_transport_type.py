"""Construction fleet construction transport type support."""

from odoo import fields, models


class ConstructionTransportType(models.Model):
    """Construction Transport Type."""

    _name = 'construction.transport.type'
    _description = 'Transport Type'
    _order = 'sequence, name'
    name = fields.Char(string='Transported Material / Trip Type', required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure')
