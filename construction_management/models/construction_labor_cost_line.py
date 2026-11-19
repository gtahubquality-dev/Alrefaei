"""Construction labor cost line for construction management."""

from odoo import fields
from odoo import models


class ConstructionLaborCostLine(models.Model):
    """Construction labor cost line."""

    _name = 'construction.labor.cost.line'
    _description = 'Project Labor Cost Allocation'
    _order = 'date_to desc, id desc'

    assignment_id = fields.Many2one(
        'construction.project.employee',
        string='Workforce Assignment',
        required=True,
        ondelete='restrict',
        index=True,
    )
    project_id = fields.Many2one(related='assignment_id.project_id', store=True, string='Project')
    company_id = fields.Many2one(related='assignment_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='assignment_id.currency_id', string='Currency')
    date_from = fields.Date(string='From', required=True)
    date_to = fields.Date(string='To', required=True)
    days = fields.Integer(string='Days')
    amount = fields.Monetary(string='Amount')
    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
