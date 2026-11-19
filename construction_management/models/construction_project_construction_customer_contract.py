"""Construction project construction customer contract for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError

from .runtime import model_attribute


class ConstructionProject(models.Model):
    """Construction project."""

    _inherit = 'construction.project'

    customer_contract_ids = fields.One2many(
        'construction.customer.contract', 'project_id', string='Customer Contracts'
    )
    customer_contract_id = fields.Many2one(
        'construction.customer.contract',
        compute='_compute_customer_contract',
        string='Customer Contract',
    )

    @api.depends('customer_contract_ids.state')
    def _compute_customer_contract(self):
        for project in self:
            project.customer_contract_id = project.customer_contract_ids.filtered(
                lambda c: c.state != 'cancelled'
            ).sorted('id')[-1:]

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        projects = super().create(vals_list)
        for project in projects:
            if project.company_id.construction_auto_customer_contract:

                model_attribute(project.sudo(), '_create_customer_contract')()
        return projects

    def _create_customer_contract(self):
        self.ensure_one()
        return (
            self.env['construction.customer.contract']
            .with_company(self.company_id)
            .create(
                {
                    'project_id': self.id,
                    'date': self.start_date or fields.Date.context_today(self),
                    'terms': self.company_id.construction_customer_contract_terms,
                }
            )
        )

    def action_customer_contract(self):
        """Open the customer contract of the project, created if needed."""
        self.ensure_one()
        contract = self.customer_contract_id
        if not contract:
            if not self.env['construction.customer.contract'].has_access('create'):
                raise UserError(
                    _(
                        'Project %s has no customer contract yet. Ask Senior Management or Finance'
                        ' to create it.',
                        self.display_name,
                    )
                )
            contract = self._create_customer_contract()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Customer Contract'),
            'res_model': 'construction.customer.contract',
            'res_id': contract.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }
