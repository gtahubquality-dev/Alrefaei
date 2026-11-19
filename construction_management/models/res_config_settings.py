"""Res config settings for construction management."""

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Res config settings."""

    _inherit = 'res.config.settings'

    construction_journal_id = fields.Many2one(
        related='company_id.construction_journal_id',
        readonly=False,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
    )
    construction_revenue_account_id = fields.Many2one(
        related='company_id.construction_revenue_account_id',
        readonly=False,
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
    )
    construction_owner_tax_ids = fields.Many2many(
        related='company_id.construction_owner_tax_ids',
        readonly=False,
        domain="[('type_tax_use', '=', 'sale'), ('company_id', 'parent_of', company_id)]",
    )
    construction_sub_tax_ids = fields.Many2many(
        related='company_id.construction_sub_tax_ids',
        readonly=False,
        domain="[('type_tax_use', '=', 'purchase'), ('company_id', 'parent_of', company_id)]",
    )
    construction_retention_account_id = fields.Many2one(
        related='company_id.construction_retention_account_id',
        readonly=False,
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
    )
    construction_advance_account_id = fields.Many2one(
        related='company_id.construction_advance_account_id',
        readonly=False,
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
    )
    construction_insurance_account_id = fields.Many2one(
        related='company_id.construction_insurance_account_id',
        readonly=False,
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
    )
    construction_sub_expense_account_id = fields.Many2one(
        related='company_id.construction_sub_expense_account_id',
        readonly=False,
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
    )
    construction_sub_retention_account_id = fields.Many2one(
        related='company_id.construction_sub_retention_account_id',
        readonly=False,
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
    )
    construction_sub_advance_account_id = fields.Many2one(
        related='company_id.construction_sub_advance_account_id',
        readonly=False,
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
    )
    construction_labor_expense_account_id = fields.Many2one(
        related='company_id.construction_labor_expense_account_id',
        readonly=False,
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
    )
    construction_labor_accrual_account_id = fields.Many2one(
        related='company_id.construction_labor_accrual_account_id',
        readonly=False,
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
    )
