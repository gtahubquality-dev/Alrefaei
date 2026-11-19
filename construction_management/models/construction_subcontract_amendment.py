"""Construction subcontract amendment for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError
from odoo.tools import formatLang
from odoo.tools import float_compare

from .construction_common import (
    active_contract_field,
    contract_related_field,
    reference_field,
    requester_field,
    workflow_status_field,
)
from .runtime import model_attribute


class ConstructionSubcontractAmendment(models.Model):
    """Construction subcontract amendment."""

    _name = 'construction.subcontract.amendment'
    _description = 'Subcontract Amendment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = reference_field()
    contract_id = active_contract_field()
    project_id = contract_related_field('project_id', 'Project')
    partner_id = contract_related_field('partner_id', 'Subcontractor')
    company_id = contract_related_field('company_id', 'Company')
    currency_id = contract_related_field('currency_id', 'Currency', store=False)
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    reason = fields.Text(string='Reason')
    state = workflow_status_field(
        [
            ('draft', 'Draft'),
            ('submitted', 'Waiting Management'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('cancelled', 'Cancelled'),
        ]
    )
    line_ids = fields.One2many(
        'construction.subcontract.amendment.line', 'amendment_id', string='Changes', copy=True
    )
    exceeds_boq = fields.Boolean(string='Exceeds BOQ', readonly=True, copy=False)
    boq_exceed_note = fields.Text(string='BOQ Excess', readonly=True, copy=False)
    amount_change = fields.Monetary(
        compute='_compute_amount_change', store=True, string='Value Change'
    )
    requested_by_id = requester_field()
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Approval Date', readonly=True, copy=False)

    @api.depends('line_ids.value_change')
    def _compute_amount_change(self):
        for amendment in self:
            amendment.amount_change = sum(amendment.line_ids.mapped('value_change'))

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'construction.subcontract.amendment'
                ) or _('New')
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_subcontract_amendment(self):
        for amendment in self:
            if amendment.state not in ('draft', 'cancelled', 'rejected'):
                raise UserError(_('Only draft, rejected or cancelled amendments can be deleted.'))

    def _check_lines(self):
        """Validate the changes and return the description of the quantities exceeding the BOQ
        (allowed only with the approval of Senior Management)."""
        excess = []
        for amendment in self:
            contract = amendment.contract_id
            if contract.state != 'active':
                raise UserError(_('Contract %s is not active.', contract.name))
            if not amendment.line_ids:
                raise UserError(_('Please add the changes of the amendment.'))
            new_totals = {}
            prices = []
            for line in amendment.line_ids:
                if line.change_type == 'change':
                    contract_line = line.contract_line_id
                    if not contract_line or contract_line.contract_id != contract:
                        raise ValidationError(
                            _('Please select an item of contract %s.', contract.name)
                        )
                    new_qty = contract_line.quantity + line.quantity_change
                    if float_compare(new_qty, 0.0, precision_digits=4) < 0:
                        raise ValidationError(
                            _(
                                'The new quantity of %s cannot be negative.',
                                contract_line.boq_item_id.display_name,
                            )
                        )
                    contract_line.invalidate_recordset(['invoiced_quantity'])
                    pending = sum(
                        contract_line.invoice_line_ids.filtered(
                            lambda l: l.invoice_id.state
                            in (
                                'site_approved',
                                'mgmt_approved',
                                'finance_approved',
                            )
                        ).mapped('current_quantity')
                    )
                    if float_compare(new_qty, pending, precision_digits=4) < 0:
                        raise ValidationError(
                            _(
                                'The new quantity of %(item)s (%(new)s) is lower than the quantity'
                                ' already invoiced or in approval (%(done)s).',
                                item=contract_line.boq_item_id.display_name,
                                new=new_qty,
                                done=pending,
                            )
                        )
                    if line.new_unit_price < 0:
                        raise ValidationError(_('The unit price cannot be negative.'))
                    item = contract_line.boq_item_id
                    new_totals[item] = new_totals.get(item, 0.0) + line.quantity_change
                    if line.new_unit_price:
                        price_check = (contract_line.boq_component_id, item, line.new_unit_price)
                        prices.append(price_check)
                else:
                    item = line.boq_item_id
                    if not item or item.project_id != contract.project_id:
                        raise ValidationError(
                            _(
                                'Please select a BOQ item of project %s.',
                                contract.project_id.display_name,
                            )
                        )
                    if float_compare(line.quantity_change, 0.0, precision_digits=4) <= 0:
                        raise ValidationError(
                            _(
                                'The quantity of the new item %s must be positive.',
                                item.display_name,
                            )
                        )
                    if line.new_unit_price < 0:
                        raise ValidationError(_('The unit price cannot be negative.'))
                    new_totals[item] = new_totals.get(item, 0.0) + line.quantity_change
                    prices.append(
                        (self.env['construction.boq.component'], item, line.new_unit_price)
                    )
            for component, item, price in prices:
                cost = model_attribute(contract.line_ids, '_get_boq_unit_cost')(item, component)
                if cost and contract.currency_id.compare_amounts(price, cost) > 0:
                    excess.append(
                        _(
                            'Unit price of %(item)s (%(price)s) exceeds its BOQ subcontract unit'
                            ' cost (%(cost)s).',
                            item=item.display_name,
                            price=formatLang(self.env, price, currency_obj=contract.currency_id),
                            cost=formatLang(self.env, cost, currency_obj=contract.currency_id),
                        )
                    )
            for item, delta in new_totals.items():
                assigned = sum(
                    item.subcontract_line_ids.filtered(
                        lambda l: l.contract_state in ('to_approve', 'active', 'closed')
                    ).mapped('quantity')
                )
                if float_compare(assigned + delta, item.total_quantity, precision_digits=4) > 0:
                    excess.append(
                        _(
                            'Total subcontracted quantity of %(item)s (%(qty)s) would exceed its'
                            ' BOQ quantity (%(boq)s).',
                            item=item.display_name,
                            qty=assigned + delta,
                            boq=item.total_quantity,
                        )
                    )
        return excess

    def action_submit(self):
        """Submit."""
        for amendment in self:
            if amendment.state != 'draft':
                raise UserError(_('Only draft amendments can be submitted.'))
            excess = model_attribute(amendment, '_check_lines')()
            amendment.write(
                {
                    'state': 'submitted',
                    'exceeds_boq': bool(excess),
                    'boq_exceed_note': '\n'.join(excess) or False,
                }
            )
            if excess:
                amendment.message_post(
                    body=_(
                        'The amendment exceeds the BOQ, Senior Management approval is required: %s',
                        ' '.join(excess),
                    )
                )
        return True

    def action_approve(self):
        """Approve."""
        if not self.env.user.has_group('construction_management.group_construction_manager'):
            raise UserError(_('Only Senior Management can approve contract amendments.'))
        line_model = self.env['construction.subcontract.line'].sudo()
        for amendment in self:
            if amendment.state != 'submitted':
                raise UserError(_('Only submitted amendments can be approved.'))
            excess = model_attribute(amendment, '_check_lines')()
            amendment.write(
                {'exceeds_boq': bool(excess), 'boq_exceed_note': '\n'.join(excess) or False}
            )
            if excess:
                amendment.message_post(
                    body=_(
                        'Quantities exceeding the BOQ approved by %(user)s: %(excess)s',
                        user=self.env.user.name,
                        excess=' '.join(excess),
                    )
                )
            for line in amendment.sudo().line_ids:
                if line.change_type == 'change':
                    contract_line = line.contract_line_id
                    line.write(
                        {
                            'previous_quantity': contract_line.quantity,
                            'previous_unit_price': contract_line.unit_price,
                        }
                    )
                    vals = {'quantity': contract_line.quantity + line.quantity_change}
                    if line.new_unit_price:
                        vals['unit_price'] = line.new_unit_price
                    contract_line.write(vals)
                else:
                    created = line_model.create(
                        {
                            'contract_id': amendment.contract_id.id,
                            'boq_item_id': line.boq_item_id.id,
                            'name': line.name or line.boq_item_id.display_name,
                            'quantity': line.quantity_change,
                            'unit_price': line.new_unit_price,
                        }
                    )
                    line.contract_line_id = created
            amendment.write(
                {
                    'state': 'approved',
                    'approved_by_id': self.env.user.id,
                    'approved_date': fields.Datetime.now(),
                }
            )
            amendment.contract_id.message_post(
                body=_(
                    'Amendment %(ref)s approved (value change: %(amount)s).',
                    ref=amendment.name,
                    amount=amendment.amount_change,
                )
            )
        return True

    def action_reject(self):
        """Reject."""
        if not self.env.user.has_group('construction_management.group_construction_manager'):
            raise UserError(_('Only Senior Management can reject contract amendments.'))
        for amendment in self:
            if amendment.state != 'submitted':
                raise UserError(_('Only submitted amendments can be rejected.'))
        self.write({'state': 'rejected'})
        return True

    def action_cancel(self):
        """Cancel."""
        for amendment in self:
            if amendment.state == 'approved':
                raise UserError(
                    _('An approved amendment cannot be cancelled. Create a new amendment instead.')
                )
        self.write({'state': 'cancelled'})
        return True

    def action_reset_draft(self):
        """Reset draft."""
        for amendment in self:
            if amendment.state not in ('rejected', 'cancelled'):
                raise UserError(_('Only rejected or cancelled amendments can be reset to draft.'))
        self.write({'state': 'draft'})
        return True
