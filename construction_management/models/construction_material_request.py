"""Construction material request for construction management."""

from odoo import Command
from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

from .runtime import model_attribute

from .construction_common import (
    reset_cancelled_requests,
    project_field,
    reference_field,
    requester_field,
    workflow_status_field,
)


class ConstructionMaterialRequest(models.Model):
    """Construction material request."""

    _name = 'construction.material.request'
    _description = 'Material Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    date = fields.Date(string='Request Date', required=True, default=fields.Date.context_today)
    name = reference_field()
    project_id = project_field()
    company_id = fields.Many2one(related='project_id.company_id', store=True, string='Company')
    warehouse_id = fields.Many2one(related='project_id.warehouse_id', string='Project Warehouse')
    date_required = fields.Date(string='Required Date')
    request_type = fields.Selection(
        [
            ('transfer', 'Issue from Warehouse'),
            ('purchase', 'Direct Purchase'),
        ],
        string='Supply Method',
        required=True,
        default='transfer',
        tracking=True,
    )
    source_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Source Warehouse',
        domain="[('company_id', '=', company_id), ('id', '!=', warehouse_id)]",
    )
    vendor_id = fields.Many2one('res.partner', string='Vendor')
    requested_by_id = requester_field()
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Approval Date', readonly=True, copy=False)
    exceeds_boq = fields.Boolean(string='Exceeds BOQ Limit', readonly=True, copy=False)
    state = workflow_status_field(
        [
            ('draft', 'Draft'),
            ('to_approve', 'Waiting Approval'),
            ('approved', 'Approved'),
            ('done', 'Processed'),
            ('cancelled', 'Cancelled'),
        ]
    )
    line_ids = fields.One2many(
        'construction.material.request.line', 'request_id', string='Materials', copy=True
    )
    picking_id = fields.Many2one('stock.picking', string='Transfer', readonly=True, copy=False)
    purchase_order_id = fields.Many2one(
        'purchase.order', string='Purchase Order', readonly=True, copy=False
    )
    note = fields.Text(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'construction.material.request'
                ) or _('New')
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_material_request(self):
        for request in self:
            if request.state not in ('draft', 'cancelled'):
                raise UserError(_('Only draft or cancelled material requests can be deleted.'))

    def _check_lines(self):
        for request in self:
            if not request.line_ids:
                raise UserError(_('Please add the requested materials.'))
            for line in request.line_ids:
                if float_compare(line.quantity, 0.0, precision_digits=6) <= 0:
                    raise ValidationError(
                        _(
                            'Requested quantity of %s must be positive.',
                            line.product_id.display_name,
                        )
                    )
                if line.requirement_id.project_id != request.project_id:
                    raise ValidationError(
                        _(
                            'Material %s does not belong to the request project.',
                            line.product_id.display_name,
                        )
                    )

    def _exceeds_boq(self):
        """True when the requested quantities (summed per material) exceed what is still available
        in the BOQ."""
        self.ensure_one()
        self.line_ids.requirement_id.invalidate_recordset()
        for requirement in self.line_ids.requirement_id:
            lines = self.line_ids.filtered(
                lambda line, req=requirement: line.requirement_id == req
            )
            requested = sum(lines.mapped('quantity'))
            available = requirement.available_quantity
            if self.state in ('to_approve', 'approved'):
                available += requested
            if float_compare(requested, available, precision_digits=4) > 0:
                return True
        return False

    def action_submit(self):
        """Submit."""
        for request in self:
            if request.state != 'draft':
                raise UserError(_('Only draft requests can be submitted.'))
            model_attribute(request, '_check_lines')()
            exceeds = model_attribute(request, '_exceeds_boq')()
            request.write(
                {'state': 'to_approve' if exceeds else 'approved', 'exceeds_boq': exceeds}
            )
            if exceeds:
                request.message_post(
                    body=_(
                        'Requested quantities exceed the remaining BOQ quantities. Official'
                        ' approval is required.'
                    )
                )
        return True

    def action_approve(self):
        """Approve."""
        if not self.env.user.has_group('construction_management.group_construction_manager'):
            raise UserError(
                _('Only Senior Management can approve material requests exceeding the BOQ.')
            )
        for request in self:
            if request.state != 'to_approve':
                raise UserError(_('Only requests waiting approval can be approved.'))
        self.write(
            {
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_date': fields.Datetime.now(),
            }
        )
        return True

    def action_reject(self):
        """Reject."""
        if not self.env.user.has_group('construction_management.group_construction_manager'):
            raise UserError(_('Only Senior Management can reject material requests.'))
        for request in self:
            if request.state != 'to_approve':
                raise UserError(_('Only requests waiting approval can be rejected.'))
            request.message_post(body=_('Request rejected by %s.', self.env.user.name))
        self.write({'state': 'cancelled'})
        return True

    def _check_can_process(self):
        """Purchases are made by the purchasing department, transfers by the warehouse (or Senior
        Management)."""
        user = self.env.user
        if self.env.su or user.has_group('construction_management.group_construction_manager'):
            return
        for request in self:
            group = (
                'purchase.group_purchase_user'
                if request.request_type == 'purchase'
                else 'stock.group_stock_user'
            )
            if not user.has_group(group):
                raise UserError(
                    _(
                        'Material request %s is processed by the purchasing department (purchases)'
                        ' or the warehouse (transfers).',
                        request.name,
                    )
                )

    def action_process(self):
        """Process."""
        self._check_can_process()
        for request in self:
            if request.state != 'approved':
                raise UserError(_('Only approved requests can be processed.'))
            if not request.project_id.warehouse_id:
                raise UserError(_('Project %s has no warehouse.', request.project_id.display_name))
            if not request.approved_by_id and model_attribute(request, '_exceeds_boq')():

                request.write({'state': 'to_approve', 'exceeds_boq': True})
                request.message_post(
                    body=_(
                        'The remaining BOQ quantities changed since submission: the request now'
                        ' exceeds the BOQ and requires official approval.'
                    )
                )
                continue
            if request.request_type == 'transfer':
                model_attribute(request, '_create_transfer')()
            else:
                model_attribute(request, '_create_purchase_order')()
            request.state = 'done'
        if len(self) == 1 and self.state == 'done':
            return self.action_view_document()
        return True

    def _reopen_after_document_cancel(self, document_label):
        """The transfer / purchase order of a processed request was cancelled: the request becomes
        approved again so that it can be supplied another way (its quantities are pending again)."""
        for request in self.filtered(lambda r: r.state == 'done'):
            request.write({'state': 'approved', 'picking_id': False, 'purchase_order_id': False})
            request.message_post(
                body=_(
                    '%s was cancelled: the request is approved again and can be processed again.',
                    document_label,
                )
            )

    def _create_transfer(self):
        self.ensure_one()
        source = self.source_warehouse_id
        if not source:
            raise UserError(_('Please select the source warehouse.'))
        if source == self.project_id.warehouse_id:
            raise UserError(_('The source warehouse must be different from the project warehouse.'))
        if not source.int_type_id:
            raise UserError(_('Warehouse %s has no internal transfer operation type.', source.name))
        location = source.lot_stock_id
        location_dest = self.project_id.warehouse_id.lot_stock_id
        picking = (
            self.env['stock.picking']
            .sudo()
            .with_company(self.company_id)
            .create(
                {
                    'picking_type_id': source.int_type_id.id,
                    'location_id': location.id,
                    'location_dest_id': location_dest.id,
                    'origin': f'{self.project_id.code} / {self.name}',
                    'construction_project_id': self.project_id.id,
                    'construction_material_request_id': self.id,
                    'company_id': self.company_id.id,
                    'move_ids': [
                        Command.create(
                            {
                                'product_id': line.product_id.id,
                                'product_uom_qty': line.quantity,
                                'product_uom': line.uom_id.id,
                                'location_id': location.id,
                                'location_dest_id': location_dest.id,
                                'company_id': self.company_id.id,
                                'construction_material_line_id': line.id,
                            }
                        )
                        for line in self.line_ids
                    ],
                }
            )
        )
        picking.action_confirm()
        self.picking_id = picking

    def _create_purchase_order(self):
        self.ensure_one()
        if not self.vendor_id:
            raise UserError(_('Please select the vendor for direct purchase.'))
        distribution = model_attribute(self.project_id, '_get_analytic_distribution')()
        order = (
            self.env['purchase.order']
            .sudo()
            .with_company(self.company_id)
            .create(
                {
                    'partner_id': self.vendor_id.id,
                    'company_id': self.company_id.id,
                    'picking_type_id': self.project_id.warehouse_id.in_type_id.id,
                    'origin': f'{self.project_id.code} / {self.name}',
                    'construction_project_id': self.project_id.id,
                    'construction_material_request_id': self.id,
                    'order_line': [
                        Command.create(
                            {
                                'product_id': line.product_id.id,
                                'product_qty': line.quantity,
                                'product_uom_id': line.uom_id.id,
                                'analytic_distribution': distribution,
                                'construction_material_line_id': line.id,
                            }
                        )
                        for line in self.line_ids
                    ],
                }
            )
        )
        self.purchase_order_id = order

    def action_cancel(self):
        """Cancel."""
        for request in self:
            if request.state == 'done':
                raise UserError(
                    _(
                        'Processed requests cannot be cancelled. Cancel the transfer or purchase'
                        ' order instead.'
                    )
                )
        self.write({'state': 'cancelled'})
        return True

    def action_reset_draft(self):
        """Reset draft."""
        return reset_cancelled_requests(
            self,
            approved_by_id=False,
            approved_date=False,
            exceeds_boq=False,
        )

    def action_view_document(self):
        """View document."""
        self.ensure_one()
        if self.picking_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking',
                'res_id': self.picking_id.id,
                'view_mode': 'form',
            }
        if self.purchase_order_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order',
                'res_id': self.purchase_order_id.id,
                'view_mode': 'form',
            }
        raise UserError(_('No transfer or purchase order is linked to this request.'))
