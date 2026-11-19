"""Construction equipment res config settings support."""

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Res Config Settings."""

    _inherit = 'res.config.settings'
    construction_equipment_expense_account_id = fields.Many2one(
        related='company_id.construction_equipment_expense_account_id',
        readonly=False,
        domain=(
            "[('account_type', 'not in', ('asset_receivable', "
            "'liability_payable')), ('active', '=', True)]"
        ),
    )
    construction_equipment_income_account_id = fields.Many2one(
        related='company_id.construction_equipment_income_account_id',
        readonly=False,
        domain=(
            "[('account_type', 'not in', ('asset_receivable', "
            "'liability_payable')), ('active', '=', True)]"
        ),
    )
    construction_equipment_cost_account_id = fields.Many2one(
        related='company_id.construction_equipment_cost_account_id',
        readonly=False,
        domain=(
            "[('account_type', 'not in', ('asset_receivable', "
            "'liability_payable')), ('active', '=', True)]"
        ),
    )
    construction_equipment_warehouse_id = fields.Many2one(
        related='company_id.construction_equipment_warehouse_id',
        readonly=False,
        domain="[('company_id', '=', company_id)]",
    )
