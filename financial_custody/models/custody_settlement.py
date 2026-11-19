"""Custody settlement for financial custody."""

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

from .custody_common import create_custody_entry, custody_move_action, custody_status_field
from .runtime import model_attribute


class CustodySettlement(models.Model):
    """Custody settlement."""

    _name = 'custody.settlement'
    _description = 'Custody Settlement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New')
    )
    custody_id = fields.Many2one(
        'custody.request',
        string='Custody',
        required=True,
        index=True,
        tracking=True,
        domain="[('state', '=', 'paid')]",
        ondelete='restrict',
    )
    employee_id = fields.Many2one(related='custody_id.employee_id', store=True, string='Employee')
    company_id = fields.Many2one(related='custody_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='custody_id.currency_id', string='Currency')
    custody_amount = fields.Monetary(related='custody_id.amount', string='Custody Amount')
    custody_balance = fields.Monetary(related='custody_id.balance', string='Custody Balance')
    date = fields.Date(
        string='Settlement Date', required=True, default=fields.Date.context_today, tracking=True
    )
    note = fields.Text(string='Notes')
    state = custody_status_field(
        [
            ('draft', 'Draft'),
            ('submitted', 'Waiting Review'),
            ('posted', 'Posted'),
            ('cancelled', 'Cancelled'),
        ],
    )
    line_ids = fields.One2many(
        'custody.settlement.line', 'settlement_id', string='Expenses', copy=True
    )
    return_line_ids = fields.One2many(
        'custody.settlement.return', 'settlement_id', string='Returned Items', copy=True
    )
    cash_returned = fields.Monetary(
        string='Cash Returned', tracking=True, help="Unused cash given back by the employee."
    )
    cash_journal_id = fields.Many2one(
        'account.journal',
        string='Cash Return Journal',
        groups='financial_custody.group_custody_manager',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
    )
    total_expenses = fields.Monetary(compute='_compute_totals', store=True, string='Total Expenses')
    total_settled = fields.Monetary(compute='_compute_totals', store=True, string='Total Settled')
    move_id = fields.Many2one(
        'account.move',
        string='Settlement Entry',
        readonly=True,
        copy=False,
        groups='financial_custody.group_custody_manager',
    )
    picking_ids = fields.One2many(
        'stock.picking', 'custody_settlement_id', string='Returns', groups='stock.group_stock_user'
    )
    submitted_by_id = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False)
    posted_by_id = fields.Many2one('res.users', string='Validated By', readonly=True, copy=False)

    @api.depends('line_ids.amount', 'cash_returned')
    def _compute_totals(self):
        for settlement in self:
            settlement.total_expenses = sum(settlement.line_ids.mapped('amount'))
            settlement.total_settled = settlement.total_expenses + settlement.cash_returned

    @api.constrains('cash_returned')
    def _check_cash(self):
        for settlement in self:
            if settlement.cash_returned < 0:
                raise ValidationError(_('The cash returned cannot be negative.'))

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('custody.settlement') or _(
                    'New'
                )
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_custody_settlement(self):
        for settlement in self:
            if settlement.state not in ('draft', 'cancelled'):
                raise UserError(_('Only draft or cancelled settlements can be deleted.'))

    def _check_before_validation(self):
        for settlement in self:
            custody = settlement.custody_id
            if custody.state != 'paid':
                raise UserError(_('Custody %s is not open for settlement.', custody.name))
            if not settlement.line_ids and float_is_zero(
                settlement.cash_returned, precision_rounding=settlement.currency_id.rounding
            ):
                raise UserError(_('Please enter the expenses or the cash returned.'))
            for line in settlement.line_ids:
                if float_compare(line.amount, 0.0, precision_digits=6) <= 0:
                    raise ValidationError(_('Expense amounts must be positive (%s).', line.name))
                if not line.invoice_ref and not line.attachment:
                    raise ValidationError(
                        _(
                            'Please enter the invoice number or attach the invoice for expense'
                            ' "%s".',
                            line.name,
                        )
                    )
            for item in settlement.return_line_ids:
                if float_compare(item.quantity, 0.0, precision_digits=6) <= 0:
                    raise ValidationError(
                        _(
                            'Returned quantities must be positive (%s).',
                            item.product_id.display_name,
                        )
                    )
            others = custody.settlement_ids.filtered(
                lambda other, current=settlement: (
                    other.state in ('submitted', 'posted') and other != current
                )
            )
            available = custody.amount - sum(others.mapped('total_settled'))
            if (
                float_compare(
                    settlement.total_settled,
                    available,
                    precision_rounding=settlement.currency_id.rounding,
                )
                > 0
            ):
                raise UserError(
                    _(
                        'The settlement total (%(total)s) exceeds the remaining custody balance'
                        ' (%(available)s).',
                        total=settlement.total_settled,
                        available=available,
                    )
                )

    def action_submit(self):
        """Submit."""
        for settlement in self:
            if settlement.state != 'draft':
                raise UserError(_('Only draft settlements can be submitted.'))
        self._check_before_validation()
        self.write({'state': 'submitted', 'submitted_by_id': self.env.user.id})
        return True

    def action_post(self):
        """Post."""
        if not self.env.user.has_group('financial_custody.group_custody_manager'):
            raise UserError(_('Only the custody manager can validate settlements.'))
        for settlement in self:
            if settlement.state != 'submitted':
                raise UserError(_('Only submitted settlements can be validated.'))
            model_attribute(settlement, '_check_before_validation')()
            model_attribute(settlement, '_create_move')()
            model_attribute(settlement, '_create_returns')()
            settlement.write({'state': 'posted', 'posted_by_id': self.env.user.id})
            model_attribute(settlement.custody_id, '_update_closed_state')()
        return True

    def action_reset_draft(self):
        """Reset draft."""
        for settlement in self:
            if settlement.state not in ('submitted', 'cancelled'):
                raise UserError(_('Only submitted or cancelled settlements can be reset to draft.'))
        self.write({'state': 'draft'})
        return True

    def action_cancel(self):
        """Cancel."""
        for settlement in self:
            if settlement.state == 'posted':
                raise UserError(
                    _(
                        'Posted settlements cannot be cancelled. Reverse the journal entry from'
                        ' Accounting.'
                    )
                )
        self.write({'state': 'cancelled'})
        return True

    def _create_move(self):
        self.ensure_one()
        custody = self.custody_id
        partner = model_attribute(custody, '_get_partner')()
        custody_account = model_attribute(custody, '_get_custody_account')()
        rounding = self.currency_id.rounding
        lines = []
        for line in self.line_ids:
            label = line.name
            if line.invoice_ref:
                label = f'{label} ({line.invoice_ref})'
            lines.append(
                Command.create(
                    {
                        'name': label,
                        'account_id': model_attribute(line, '_get_account')().id,
                        'partner_id': (line.vendor_id or partner).id,
                        'debit': line.amount,
                        'credit': 0.0,
                        'analytic_distribution': line.analytic_distribution,
                    }
                )
            )
        if not float_is_zero(self.cash_returned, precision_rounding=rounding):
            journal = self.cash_journal_id or custody.journal_id
            if not journal or not journal.default_account_id:
                raise UserError(_('Please select the journal receiving the cash returned.'))
            lines.append(
                Command.create(
                    {
                        'name': _('Cash returned - %s', custody.name),
                        'account_id': journal.default_account_id.id,
                        'partner_id': partner.id,
                        'debit': self.cash_returned,
                        'credit': 0.0,
                    }
                )
            )
        lines.append(
            Command.create(
                {
                    'name': _(
                        'Settlement %(ref)s of custody %(custody)s',
                        ref=self.name,
                        custody=custody.name,
                    ),
                    'account_id': custody_account.id,
                    'partner_id': partner.id,
                    'debit': 0.0,
                    'credit': self.total_settled,
                }
            )
        )
        journal = custody.company_id.custody_settlement_journal_id or self.env[
            'account.journal'
        ].search([('type', '=', 'general'), ('company_id', '=', custody.company_id.id)], limit=1)
        if not journal:
            raise UserError(_('Please configure the custody settlement journal.'))
        move = create_custody_entry(
            self.env,
            custody.company_id,
            {
                'journal_id': journal.id,
                'date': self.date,
                'ref': _('Custody settlement %s', self.name),
                'partner_id': partner.id,
                'line_ids': lines,
            },
        )
        move.action_post()
        self.move_id = move

    def _create_returns(self):
        self.ensure_one()
        picking_model = self.env['stock.picking'].sudo()
        by_warehouse = {}
        for item in self.return_line_ids:
            by_warehouse.setdefault(item.warehouse_id, self.env['custody.settlement.return'])
            by_warehouse[item.warehouse_id] |= item
        for warehouse, items in by_warehouse.items():
            picking_type = warehouse.in_type_id
            dest = warehouse.lot_stock_id
            moves = []
            for item in items:
                source = item.product_id.with_company(self.company_id).property_stock_inventory
                if not source:
                    raise UserError(
                        _(
                            'Product %s has no inventory adjustment location.',
                            item.product_id.display_name,
                        )
                    )
                moves.append(
                    Command.create(
                        {
                            'product_id': item.product_id.id,
                            'product_uom_qty': item.quantity,
                            'product_uom': (item.uom_id or item.product_id.uom_id).id,
                            'location_id': source.id,
                            'location_dest_id': dest.id,
                            'company_id': self.company_id.id,
                        }
                    )
                )
            source_location = (
                items[0].product_id.with_company(self.company_id).property_stock_inventory
            )
            picking = picking_model.with_company(self.company_id).create(
                {
                    'picking_type_id': picking_type.id,
                    'location_id': source_location.id,
                    'location_dest_id': dest.id,
                    'origin': self.name,
                    'custody_settlement_id': self.id,
                    'company_id': self.company_id.id,
                    'move_ids': moves,
                }
            )
            picking.action_confirm()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            model_attribute(picking, '_action_done')()

    def action_view_move(self):
        """View move."""
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('The settlement has not been posted yet.'))
        return custody_move_action(self.move_id)
