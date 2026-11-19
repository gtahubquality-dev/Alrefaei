"""Custody settlement lock mixin for financial custody."""

from odoo import _
from odoo import api
from odoo import models
from odoo.exceptions import UserError

from .runtime import model_attribute


class CustodySettlementLockMixin(models.AbstractModel):
    """Lock posted lines and restrict submitted lines to custody managers."""

    _name = 'custody.settlement.lock.mixin'
    _description = 'Custody Settlement Lines Lock'

    def _check_settlement_editable(self):
        if self.env.su:
            return
        states = set(self.settlement_id.mapped('state'))
        if 'posted' in states:
            raise UserError(_('The lines of a posted settlement cannot be changed.'))
        if states - {'draft'} and not self.env.user.has_group(
            'financial_custody.group_custody_manager'
        ):
            raise UserError(
                _('The lines of a submitted settlement can only be changed by the custody manager.')
            )

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        records = super().create(vals_list)
        model_attribute(records, '_check_settlement_editable')()
        return records

    @api.ondelete(at_uninstall=False)
    def _unlink_except_locked_settlement(self):
        self._check_settlement_editable()
