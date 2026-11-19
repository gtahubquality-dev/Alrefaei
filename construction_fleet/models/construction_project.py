"""Construction fleet construction project support."""

from odoo import models


class ConstructionProject(models.Model):
    """Construction Project."""

    _inherit = 'construction.project'

    def _get_cost_type_accounts(self):
        """Vehicle transport costs (driver custody sheets) are equipment costs of the project."""
        mapping = super()._get_cost_type_accounts()
        account = self.company_id.construction_transport_expense_account_id
        if account:
            mapping[account.id] = 'equipment'
        return mapping
