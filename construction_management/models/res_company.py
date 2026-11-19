"""Res company for construction management."""

from odoo import fields, models


class ResCompany(models.Model):
    """Res company."""

    _inherit = 'res.company'

    construction_owner_tax_ids = fields.Many2many(
        'account.tax',
        'construction_company_owner_tax_rel',
        'company_id',
        'tax_id',
        string='Owner Invoice Taxes',
        domain="[('type_tax_use', '=', 'sale'), ('company_id', 'parent_of', id)]",
        help=(
            "Taxes (e.g. VAT) applied to the works of the owner invoices: credited on the customer"
            " invoice."
        ),
    )
    construction_sub_tax_ids = fields.Many2many(
        'account.tax',
        'construction_company_sub_tax_rel',
        'company_id',
        'tax_id',
        string='Subcontractor Invoice Taxes',
        domain="[('type_tax_use', '=', 'purchase'), ('company_id', 'parent_of', id)]",
        help=(
            "Taxes (e.g. VAT) applied to the works of the subcontractor invoices: debited on the"
            " vendor bill."
        ),
    )

    construction_journal_id = fields.Many2one(
        'account.journal',
        string='Construction Miscellaneous Journal',
        domain="[('type', '=', 'general'), ('company_id', '=', id)]",
        help=(
            "Journal used for retention, insurance, suspense refunds and equipment cost allocation"
            " entries."
        ),
    )
    construction_revenue_account_id = fields.Many2one(
        'account.account',
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
        string='Owner Invoice Revenue Account',
        help=(
            "Income account used on owner invoice lines. Leave empty to use the sales journal"
            " default account."
        ),
    )
    construction_retention_account_id = fields.Many2one(
        'account.account',
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
        string='Owner Retention Account',
        help=(
            "Current asset account holding the work guarantee retained by the owner (not a"
            " receivable account)."
        ),
    )
    construction_advance_account_id = fields.Many2one(
        'account.account',
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
        string='Owner Advance Payment Account',
        help="Liability account for advance payments received from the owner.",
    )
    construction_insurance_account_id = fields.Many2one(
        'account.account',
        string='Final Insurance Account',
        help="Asset account holding the final insurance paid to the owner.",
    )
    construction_sub_expense_account_id = fields.Many2one(
        'account.account',
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
        string='Subcontractor Works Expense Account',
    )
    construction_sub_retention_account_id = fields.Many2one(
        'account.account',
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
        string='Subcontractor Retention Account',
        help="Liability account holding the work guarantee retained from subcontractors.",
    )
    construction_sub_advance_account_id = fields.Many2one(
        'account.account',
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
        string='Subcontractor Advance Account',
        help="Asset account for advance payments paid to subcontractors.",
    )
    construction_labor_expense_account_id = fields.Many2one(
        'account.account',
        domain=(
            "[('account_type', 'not in', ('asset_receivable', 'liability_payable')), ('active',"
            " '=', True)]"
        ),
        string='Project Labor Cost Account',
        help="Expense account charged with the cost of employees and workers assigned to projects.",
    )
    construction_labor_accrual_account_id = fields.Many2one(
        'account.account',
        string='Accrued Salaries Account',
        help="Liability account credited when project labor costs are allocated.",
    )
