"""Construction guarantee extend wizard for construction management."""

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

from ..models.runtime import model_attribute


class ConstructionGuaranteeExtendWizard(models.TransientModel):
    """Construction guarantee extend wizard."""

    _name = 'construction.guarantee.extend.wizard'
    _description = 'Extend Guarantee'

    guarantee_id = fields.Many2one('construction.guarantee', string='Guarantee', required=True)
    currency_id = fields.Many2one(related='guarantee_id.currency_id', string='Currency')
    current_expiry_date = fields.Date(related='guarantee_id.expiry_date', string='Current Expiry')
    new_expiry_date = fields.Date(string='New Expiry Date', required=True)
    new_amount = fields.Monetary(string='New Amount', required=True)
    note = fields.Char(string='Notes')

    def action_extend(self):
        """Extend."""
        self.ensure_one()
        guarantee = self.guarantee_id
        model_attribute(guarantee, '_check_manager')()
        if guarantee.state not in ('active', 'expired'):
            raise UserError(_('Only active or expired guarantees can be extended.'))
        if guarantee.expiry_date and self.new_expiry_date <= guarantee.expiry_date:
            raise UserError(_('The new expiry date must be after the current expiry date.'))
        if float_compare(self.new_amount, 0.0, precision_digits=6) <= 0:
            raise UserError(_('The guarantee amount must be positive.'))
        self.env['construction.guarantee.extension'].sudo().create(
            {
                'guarantee_id': guarantee.id,
                'old_expiry_date': guarantee.expiry_date,
                'new_expiry_date': self.new_expiry_date,
                'old_amount': guarantee.amount,
                'new_amount': self.new_amount,
                'user_id': self.env.user.id,
                'note': self.note,
            }
        )
        guarantee.write(
            {
                'expiry_date': self.new_expiry_date,
                'amount': self.new_amount,
                'state': 'active',
                'expiry_alert_sent': False,
            }
        )
        return {'type': 'ir.actions.act_window_close'}
