"""Construction change order for construction management."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .runtime import model_attribute

from .construction_common import (
    project_field,
    reference_field,
    requester_field,
    workflow_status_field,
)


class ConstructionChangeOrder(models.Model):
    """Construction change order."""

    _name = 'construction.change.order'
    _description = 'BOQ Change Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = reference_field()
    project_id = project_field()
    company_id = fields.Many2one(related='project_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='project_id.currency_id', string='Currency')
    date = fields.Date(
        string='Date', required=True, default=fields.Date.context_today, tracking=True
    )
    reason = fields.Text(string='Reason / Justification')
    owner_reference = fields.Char(string='Owner / Consultant Reference')
    requested_by_id = requester_field()
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Approval Date', readonly=True, copy=False)
    state = workflow_status_field(
        [
            ('draft', 'Draft'),
            ('submitted', 'Waiting Approval'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('cancelled', 'Cancelled'),
        ]
    )
    line_ids = fields.One2many(
        'construction.change.order.line', 'order_id', string='Changes', copy=True
    )
    amount_total = fields.Monetary(
        compute='_compute_amount_total', string='Value Change', store=True
    )
    history_ids = fields.One2many('construction.boq.history', 'change_order_id', string='History')

    @api.depends('line_ids.value_change')
    def _compute_amount_total(self):
        for order in self:
            order.amount_total = sum(order.line_ids.mapped('value_change'))

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'construction.change.order'
                ) or _('New')
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_change_order(self):
        for order in self:
            if order.state not in ('draft', 'cancelled'):
                raise UserError(_('Only draft or cancelled change orders can be deleted.'))

    def action_submit(self):
        """Submit."""
        for order in self:
            if order.state != 'draft':
                raise UserError(_('Only draft change orders can be submitted.'))
            if not order.line_ids:
                raise UserError(_('Please add at least one change line.'))
            model_attribute(order.line_ids, '_check_line_values')()
        self.write({'state': 'submitted'})

    def action_approve(self):
        """Approve."""
        if not self.env.user.has_group('construction_management.group_construction_manager'):
            raise UserError(_('Only Senior Management can approve change orders.'))
        history_model = self.env['construction.boq.history'].sudo()
        boq_item_model = self.env['construction.boq.item']
        now = fields.Datetime.now()
        for order in self:
            if order.state != 'submitted':
                raise UserError(_('Only submitted change orders can be approved.'))
            if order.project_id.state not in ('running', 'suspended'):
                raise UserError(
                    _('Change orders can only be approved for running or suspended projects.')
                )
            model_attribute(order.line_ids, '_check_line_values')()
            history_vals = []
            for line in order.line_ids:
                if line.change_type == 'quantity':
                    item = line.boq_item_id
                    old_quantity = item.total_quantity
                    line.sudo().previous_quantity = old_quantity
                    history_vals.append(
                        {
                            'project_id': order.project_id.id,
                            'boq_item_id': item.id,
                            'change_order_id': order.id,
                            'change_type': 'quantity',
                            'description': line.name or item.display_name,
                            'old_quantity': old_quantity,
                            'new_quantity': old_quantity + line.quantity,
                            'quantity_change': line.quantity,
                            'unit_price': item.unit_price,
                            'value_change': line.quantity * item.unit_price,
                            'user_id': self.env.user.id,
                            'change_datetime': now,
                        }
                    )
                else:
                    item = boq_item_model.sudo().create(
                        {
                            'project_id': order.project_id.id,
                            'sequence': 1000 + line.sequence,
                            'code': line.code,
                            'name': line.name,
                            'description': line.description,
                            'uom_id': line.uom_id.id,
                            'quantity': line.quantity,
                            'unit_price': line.unit_price,
                            'weight_percent': line.weight_percent,
                            'is_change_order_item': True,
                            'change_order_line_id': line.id,
                            'component_ids': [
                                (
                                    0,
                                    0,
                                    {
                                        'component_type': comp.component_type,
                                        'product_id': comp.product_id.id,
                                        'name': comp.name,
                                        'quantity': comp.quantity,
                                        'uom_id': comp.uom_id.id,
                                        'unit_cost': comp.unit_cost,
                                    },
                                )
                                for comp in line.component_ids
                            ],
                        }
                    )
                    line.sudo().new_boq_item_id = item
                    history_vals.append(
                        {
                            'project_id': order.project_id.id,
                            'boq_item_id': item.id,
                            'change_order_id': order.id,
                            'change_type': 'new',
                            'description': item.display_name,
                            'old_quantity': 0.0,
                            'new_quantity': line.quantity,
                            'quantity_change': line.quantity,
                            'unit_price': line.unit_price,
                            'value_change': line.quantity * line.unit_price,
                            'user_id': self.env.user.id,
                            'change_datetime': now,
                        }
                    )
            order.write(
                {'state': 'approved', 'approved_by_id': self.env.user.id, 'approved_date': now}
            )
            history_model.create(history_vals)
            order.project_id.action_sync_material_requirements()
            order.project_id.message_post(
                body=_('Change order %s approved and applied to the BOQ.', order.name)
            )
        return True

    def action_reject(self):
        """Reject."""
        if not self.env.user.has_group('construction_management.group_construction_manager'):
            raise UserError(_('Only Senior Management can reject change orders.'))
        for order in self:
            if order.state != 'submitted':
                raise UserError(_('Only submitted change orders can be rejected.'))
        self.write({'state': 'rejected'})

    def action_cancel(self):
        """Cancel."""
        for order in self:
            if order.state == 'approved':
                raise UserError(
                    _(
                        'An approved change order cannot be cancelled. Create a new change order'
                        ' instead.'
                    )
                )
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        """Reset draft."""
        for order in self:
            if order.state not in ('rejected', 'cancelled'):
                raise UserError(
                    _('Only rejected or cancelled change orders can be reset to draft.')
                )
        self.write({'state': 'draft'})
