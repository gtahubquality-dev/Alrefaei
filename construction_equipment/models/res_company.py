"""Construction equipment res company support."""

from odoo import fields, models


class ResCompany(models.Model):
    """Res Company."""

    _inherit = 'res.company'
    construction_equipment_expense_account_id = fields.Many2one(
        'account.account',
        string='Equipment Usage Expense Account',
        help='Expense charged to projects for equipment operating hours.',
    )
    construction_equipment_income_account_id = fields.Many2one(
        'account.account',
        string='Equipment Allocation Income Account',
        help=(
            'Income recognized by the equipment cost center when '
            'its cost is allocated to projects.'
        ),
    )
    construction_equipment_cost_account_id = fields.Many2one(
        'account.account',
        domain=(
            "[('account_type', 'not in', ('asset_receivable', "
            "'liability_payable')), ('active', '=', True)]"
        ),
        string='Equipment Maintenance / Rental Expense Account',
        help=(
            'Expense account used on vendor bills for equipment '
            'maintenance, repair, rental and fuel.'
        ),
    )
    construction_equipment_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Equipment Main Yard Warehouse',
        help=('Warehouse where company equipment is kept when it is not on a project site.'),
    )
