"""Construction bidding bidding tender support."""

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class BiddingTender(models.Model):
    """Bidding Tender."""

    _name = 'bidding.tender'
    _description = 'Tender / Bidding'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'submission_date desc, id desc'

    name = fields.Char(string='Tender / Project Name', required=True, tracking=True)
    reference = fields.Char(
        string='Bidding Reference', required=True, copy=False, readonly=True,
        default=lambda self: _('New'), index=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency',
        readonly=True)
    user_id = fields.Many2one(
        'res.users', string='Responsible', default=lambda self: self.env.user, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, tracking=True)
    owner_id = fields.Many2one('res.partner', string='Project Owner', tracking=True)
    consultant_id = fields.Many2one('res.partner', string='Consultant', tracking=True)
    submission_date = fields.Date(string='Tender Submission Date', tracking=True)
    start_date = fields.Date(string='Expected Start Date', tracking=True)
    duration_months = fields.Integer(string='Expected Duration (Months)', tracking=True)
    end_date = fields.Date(
        string='Expected End Date', compute='_compute_end_date', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'Under Study'),
        ('submitted', 'Submitted'),
        ('awarded', 'Awarded'),
        ('lost', 'Lost'),
        ('cancelled', 'Cancelled'),
    ], string='Tender Status', default='draft', required=True, tracking=True, copy=False)
    notes = fields.Html(string='Notes')

    boq_item_ids = fields.One2many('bidding.boq.item', 'tender_id', string='BOQ Items', copy=True)
    boq_item_count = fields.Integer(compute='_compute_totals', string='BOQ Items Count', store=True)

    material_cost = fields.Monetary(compute='_compute_totals', store=True, string='Materials Cost')
    equipment_cost = fields.Monetary(compute='_compute_totals', store=True, string='Equipment Cost')
    subcontract_cost = fields.Monetary(compute='_compute_totals', store=True,
        string='Subcontractors Cost')
    labor_cost = fields.Monetary(compute='_compute_totals', store=True,
        string='External Labor Cost')
    total_cost = fields.Monetary(compute='_compute_totals', store=True,
        string='Total Estimated Cost')
    offer_amount = fields.Monetary(compute='_compute_totals', store=True, string='Offer Amount')
    profit_amount = fields.Monetary(compute='_compute_totals', store=True, string='Expected Profit')
    profit_percent = fields.Float(compute='_compute_totals', store=True, string='Profit Margin (%)')
    total_weight = fields.Float(compute='_compute_totals', store=True, string='Total Weight (%)')

    _reference_company_uniq = models.Constraint(
        'unique(reference, company_id)',
        'The bidding reference must be unique per company.',
    )

    @api.depends('start_date', 'duration_months')
    def _compute_end_date(self):
        for tender in self:
            if tender.start_date and tender.duration_months > 0:
                tender.end_date = (
                    tender.start_date + relativedelta(months=tender.duration_months, days=-1)
                )
            else:
                tender.end_date = False

    @api.depends(
        'boq_item_ids.material_cost', 'boq_item_ids.equipment_cost',
        'boq_item_ids.subcontract_cost', 'boq_item_ids.labor_cost',
        'boq_item_ids.estimated_cost', 'boq_item_ids.amount_total',
        'boq_item_ids.weight_percent')
    def _compute_totals(self):
        for tender in self:
            items = tender.boq_item_ids
            tender.boq_item_count = len(items)
            tender.material_cost = sum(items.mapped('material_cost'))
            tender.equipment_cost = sum(items.mapped('equipment_cost'))
            tender.subcontract_cost = sum(items.mapped('subcontract_cost'))
            tender.labor_cost = sum(items.mapped('labor_cost'))
            tender.total_cost = sum(items.mapped('estimated_cost'))
            tender.offer_amount = sum(items.mapped('amount_total'))
            tender.profit_amount = tender.offer_amount - tender.total_cost
            tender.profit_percent = (
                tender.profit_amount / tender.offer_amount * 100.0 if tender.offer_amount else 0.0)
            tender.total_weight = sum(items.mapped('weight_percent'))

    @api.constrains('duration_months')
    def _check_duration(self):
        for tender in self:
            if tender.duration_months < 0:
                raise ValidationError(_('The expected duration cannot be negative.'))

    @api.private
    def check_total_weight(self):
        """Validate BOQ weights through the internal validation hook."""
        self._check_total_weight()

    def _check_total_weight(self):
        for tender in self:
            weight = sum(tender.boq_item_ids.mapped('weight_percent'))
            if float_compare(weight, 100.0, precision_digits=2) > 0:
                raise ValidationError(_(
                    'The total weight of BOQ items in tender %(tender)s cannot exceed '
                        '100%% (current: %(weight)s%%).',
                    tender=tender.display_name, weight=round(weight, 2)))

    @api.model_create_multi
    def create(self, vals_list):
        """Create records and validate their BOQ weights."""
        for vals in vals_list:
            if not vals.get('reference') or vals.get('reference') == _('New'):
                vals['reference'] = (
                    self.env['ir.sequence'].next_by_code('bidding.tender') or _('New')
                )
        tenders = super(BiddingTender,
            self.with_context(bidding_skip_weight_check=True)).create(vals_list)
        tenders.check_total_weight()
        return tenders.with_env(self.env)

    def write(self, vals):
        """Update records and validate affected BOQ weights."""
        res = super(BiddingTender, self.with_context(bidding_skip_weight_check=True)).write(vals)
        if 'boq_item_ids' in vals:
            self._check_total_weight()
        return res

    @api.depends('name', 'reference')
    def _compute_display_name(self):
        for tender in self:
            if tender.reference and tender.reference != _('New'):
                tender.display_name = f'[{tender.reference}] {tender.name or ""}'
            else:
                tender.display_name = tender.name or ''

    def copy_data(self, default=None):
        """Prepare a duplicate tender with a distinct display name."""
        vals_list = super().copy_data(default=default)
        for tender, vals in zip(self, vals_list):
            vals['name'] = _('%s (copy)', tender.name)
        return vals_list

    def action_start_study(self):
        """Move draft tenders into study."""
        for tender in self:
            if tender.state != 'draft':
                raise UserError(_('Only draft tenders can be moved to study.'))
        self.write({'state': 'in_progress'})

    def action_submit(self):
        """Submit eligible tenders with BOQ items."""
        for tender in self:
            if tender.state not in ('draft', 'in_progress'):
                raise UserError(_('Only draft or under-study tenders can be submitted.'))
            if not tender.boq_item_ids:
                raise UserError(_('You cannot submit tender %s without BOQ items.',
                    tender.display_name))
        self.write({'state': 'submitted', 'submission_date': fields.Date.context_today(self)})

    def action_award(self):
        """Mark submitted tenders as awarded."""
        for tender in self:
            if tender.state != 'submitted':
                raise UserError(_('Only submitted tenders can be awarded.'))
        self.write({'state': 'awarded'})

    def action_mark_lost(self):
        """Mark submitted tenders as lost."""
        for tender in self:
            if tender.state != 'submitted':
                raise UserError(_('Only submitted tenders can be marked as lost.'))
        self.write({'state': 'lost'})

    def action_cancel(self):
        """Cancel tenders that have not been awarded."""
        for tender in self:
            if tender.state == 'awarded':
                raise UserError(_('An awarded tender cannot be cancelled.'))
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        """Return eligible tenders to draft."""
        for tender in self:
            if tender.state not in ('lost', 'cancelled', 'in_progress'):
                raise UserError(_('Only lost, cancelled or under-study tenders can be reset to '
                    'draft.'))
        self.write({'state': 'draft'})

    def action_view_boq_items(self):
        """Open the BOQ items belonging to this tender."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('BOQ Items'),
            'res_model': 'bidding.boq.item',
            'view_mode': 'list,form',
            'domain': [('tender_id', '=', self.id)],
            'context': {'default_tender_id': self.id},
        }

    def action_view_components(self):
        """Open cost components belonging to this tender."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cost Components'),
            'res_model': 'bidding.boq.component',
            'view_mode': 'list,pivot',
            'domain': [('tender_id', '=', self.id)],
            'context': {'group_by': ['component_type']},
        }
