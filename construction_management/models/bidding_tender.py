"""Bidding tender for construction management."""

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class BiddingTender(models.Model):
    """Bidding tender."""

    _inherit = 'bidding.tender'

    construction_project_ids = fields.One2many(
        'construction.project',
        'tender_id',
        string='Construction Projects',
        groups='construction_management.group_construction_user',
    )
    construction_project_id = fields.Many2one(
        'construction.project',
        string='Construction Project',
        compute='_compute_construction_project',
        compute_sudo=True,
        groups='construction_management.group_construction_user',
    )
    has_construction_project = fields.Boolean(
        string='Has Construction Project',
        compute='_compute_construction_project',
        compute_sudo=True,
    )

    @api.depends('construction_project_ids')
    def _compute_construction_project(self):
        for tender in self:
            project = tender.construction_project_ids[:1]
            tender.construction_project_id = project
            tender.has_construction_project = bool(project)

    def _prepare_construction_project_vals(self):
        self.ensure_one()
        items = []
        for item in self.boq_item_ids:
            items.append(
                Command.create(
                    {
                        'sequence': item.sequence,
                        'code': item.code,
                        'name': item.name,
                        'description': item.description,
                        'uom_id': item.uom_id.id,
                        'quantity': item.quantity,
                        'unit_price': item.unit_price,
                        'weight_percent': item.weight_percent,
                        'bid_item_id': item.id,
                        'component_ids': [
                            Command.create(
                                {
                                    'sequence': component.sequence,
                                    'component_type': component.component_type,
                                    'product_id': component.product_id.id,
                                    'name': component.name,
                                    'specifications': component.specifications,
                                    'quantity': component.quantity,
                                    'uom_id': component.uom_id.id,
                                    'unit_cost': component.unit_cost,
                                }
                            )
                            for component in item.component_ids
                        ],
                    }
                )
            )
        return {
            'name': self.name,
            'tender_id': self.id,
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
            'owner_id': self.owner_id.id,
            'consultant_id': self.consultant_id.id,
            'start_date': self.start_date,
            'duration_months': self.duration_months,
            'boq_item_ids': items,
        }

    def action_create_construction_project(self):
        """Create construction project."""
        self.ensure_one()
        if not self.env.user.has_group('construction_management.group_construction_manager'):
            raise UserError(_('Only Senior Management can create construction projects.'))
        if self.state != 'awarded':
            raise UserError(_('A construction project can only be created from an awarded tender.'))
        existing = (
            self.env['construction.project']
            .sudo()
            .with_context(active_test=False)
            .search([('tender_id', '=', self.id)], limit=1)
        )
        if existing:
            raise UserError(
                _(
                    'Construction project %s has already been created from this tender.',
                    existing.display_name,
                )
            )
        if not self.boq_item_ids:
            raise UserError(_('The awarded tender has no BOQ items to transfer.'))
        project = self.env['construction.project'].create(self._prepare_construction_project_vals())
        project.message_post(body=_('Project created from awarded tender %s.', self.display_name))
        self.message_post(body=_('Construction project %s created.', project.display_name))
        return self.action_view_construction_project(project)

    def action_view_construction_project(self, project=None):
        """View construction project."""
        self.ensure_one()
        project = project or self.construction_project_id
        if not project:
            raise UserError(_('No construction project is linked to this tender.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Construction Project'),
            'res_model': 'construction.project',
            'res_id': project.id,
            'view_mode': 'form',
        }
