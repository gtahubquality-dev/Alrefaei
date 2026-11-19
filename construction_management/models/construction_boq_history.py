"""Construction boq history for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError


class ConstructionBoqHistory(models.Model):
    """Construction boq history."""

    _name = 'construction.boq.history'
    _description = 'BOQ Change History'
    _order = 'change_datetime desc, id desc'

    project_id = fields.Many2one(
        'construction.project',
        string='Project',
        required=True,
        ondelete='cascade',
        index=True,
        readonly=True,
    )
    company_id = fields.Many2one(related='project_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='project_id.currency_id', string='Currency')
    boq_item_id = fields.Many2one(
        'construction.boq.item', string='BOQ Item', readonly=True, ondelete='cascade'
    )
    change_order_id = fields.Many2one(
        'construction.change.order', string='Change Order', readonly=True, ondelete='set null'
    )
    change_type = fields.Selection(
        [
            ('new', 'New Item'),
            ('quantity', 'Quantity Change'),
        ],
        string='Change Type',
        required=True,
        readonly=True,
    )
    description = fields.Char(string='Description', readonly=True)
    old_quantity = fields.Float(string='Old Quantity', digits='Product Unit', readonly=True)
    new_quantity = fields.Float(string='New Quantity', digits='Product Unit', readonly=True)
    quantity_change = fields.Float(string='Quantity Change', digits='Product Unit', readonly=True)
    unit_price = fields.Monetary(string='Unit Price', readonly=True)
    value_change = fields.Monetary(string='Value Change', readonly=True)
    user_id = fields.Many2one('res.users', string='Responsible User', readonly=True)
    change_datetime = fields.Datetime(string='Date & Time', readonly=True)

    def write(self, vals):
        """Write."""
        if not (self.env.su and self.env.context.get('construction_history_cleanup')):
            raise UserError(_('BOQ history records cannot be modified.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_boq_history(self):
        if not (self.env.su and self.env.context.get('construction_history_cleanup')):
            raise UserError(_('BOQ history records cannot be deleted.'))
