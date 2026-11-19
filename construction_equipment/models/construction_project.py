"""Construction equipment construction project support."""

from odoo import models


class ConstructionProject(models.Model):
    """Construction Project."""

    _inherit = 'construction.project'

    def _get_cost_type_accounts(self):
        mapping = super()._get_cost_type_accounts()
        company = self.company_id
        for account in (
            company.construction_equipment_expense_account_id,
            company.construction_equipment_cost_account_id,
        ):
            if account:
                mapping[account.id] = 'equipment'
        return mapping

    def _get_site_equipment(self):
        equipment = super()._get_site_equipment()
        in_transit = (
            self.env['construction.equipment.movement']
            .sudo()
            .search(
                [
                    ('state', '=', 'in_transit'),
                    '|',
                    ('to_project_id', '=', self.id),
                    ('from_project_id', '=', self.id),
                ]
            )
        )
        return equipment | in_transit.equipment_id
