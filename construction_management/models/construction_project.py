"""Construction project for construction management."""

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero

from .construction_common import analytic_lines_action, company_field, workflow_status_field
from .runtime import model_attribute


class ConstructionProject(models.Model):
    """Construction project."""

    _name = 'construction.project'
    _description = 'Construction Project'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_names_search = ['name', 'code']

    name = fields.Char(string='Project Name', required=True, tracking=True)
    code = fields.Char(
        string='Project Code',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New'),
    )
    tender_id = fields.Many2one(
        'bidding.tender',
        string='Original Tender',
        readonly=True,
        copy=False,
        index=True,
        ondelete='restrict',
    )
    company_id = company_field()
    currency_id = fields.Many2one(
        related='company_id.currency_id', string='Currency', readonly=True
    )
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, tracking=True)
    owner_id = fields.Many2one('res.partner', string='Project Owner', tracking=True)
    consultant_id = fields.Many2one('res.partner', string='Consultant', tracking=True)
    manager_id = fields.Many2one(
        'res.users', string='Project Manager', default=lambda self: self.env.user, tracking=True
    )
    site_engineer_id = fields.Many2one('res.users', string='Site Engineer', tracking=True)
    member_ids = fields.Many2many(
        'res.users',
        'construction_project_member_rel',
        'project_id',
        'user_id',
        string='Project Team',
    )

    start_date = fields.Date(
        string='Project Start Date', tracking=True, help="Actual start date based on site handover."
    )
    duration_months = fields.Integer(string='Duration (Months)', tracking=True)
    end_date = fields.Date(string='Scheduled End Date', compute='_compute_end_date', store=True)
    preliminary_handover_date = fields.Date(
        string='Preliminary Handover Date', tracking=True, copy=False
    )
    final_handover_date = fields.Date(string='Final Handover Date', tracking=True, copy=False)
    suspension_date = fields.Date(string='Suspension Date', tracking=True, copy=False)
    revised_date = fields.Date(string='Revised Date', tracking=True, copy=False)
    state = workflow_status_field(
        [
            ('draft', 'Draft'),
            ('running', 'In Progress'),
            ('suspended', 'Suspended'),
            ('preliminary', 'Preliminary Handover'),
            ('final', 'Final Handover'),
            ('cancelled', 'Cancelled'),
        ]
    )

    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Cost Center',
        readonly=True,
        copy=False,
        ondelete='restrict',
    )
    project_id = fields.Many2one(
        'project.project', string='Odoo Project', readonly=True, copy=False
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Project Warehouse', readonly=True, copy=False
    )

    advance_payment_percent = fields.Float(
        string='Advance Payment (%)',
        tracking=True,
        digits=(16, 4),
        help="Advance payment paid by the customer, as a percentage of the contract value.",
    )
    advance_payment_amount = fields.Monetary(
        string='Agreed Advance Payment',
        compute='_compute_contract_terms',
        store=True,
        readonly=False,
        tracking=True,
        help=(
            "Advance payment agreed in the customer contract. Computed from the percentage and the "
            "current contract value; the advance received cannot exceed it."
        ),
    )
    guarantee_percent = fields.Float(
        string='Work Guarantee (%)',
        tracking=True,
        default=0.0,
        help=(
            "Retention: percentage of each owner invoice gross amount withheld until the handover."
        ),
    )
    advance_deduction_percent = fields.Float(
        string='Advance Deduction (%)',
        tracking=True,
        help=(
            "Percentage of each owner invoice gross amount deducted to recover the advance payment."
        ),
    )
    final_insurance_percent = fields.Float(
        string='Final Insurance (%)',
        tracking=True,
        digits=(16, 4),
        help="Final insurance (performance guarantee) as a percentage of the contract value.",
    )
    final_insurance_amount = fields.Monetary(
        string='Final Insurance Amount',
        compute='_compute_contract_terms',
        store=True,
        readonly=False,
        tracking=True,
    )

    was_started = fields.Boolean(
        string='Started Once',
        readonly=True,
        copy=False,
        help=(
            "The project was started: its BOQ stays locked even if it is cancelled and reset to"
            " draft."
        ),
    )

    boq_item_ids = fields.One2many('construction.boq.item', 'project_id', string='BOQ Items')
    change_order_ids = fields.One2many(
        'construction.change.order', 'project_id', string='Change Orders'
    )
    boq_history_ids = fields.One2many(
        'construction.boq.history', 'project_id', string='BOQ History'
    )
    owner_invoice_ids = fields.One2many(
        'construction.owner.invoice', 'project_id', string='Owner Invoices'
    )
    deduction_ids = fields.One2many(
        'construction.project.deduction', 'project_id', string='Deductions'
    )
    operation_ids = fields.One2many(
        'construction.project.operation', 'project_id', string='Financial Operations'
    )
    material_requirement_ids = fields.One2many(
        'construction.material.requirement', 'project_id', string='Material Requirements'
    )
    material_request_ids = fields.One2many(
        'construction.material.request', 'project_id', string='Material Requests'
    )
    subcontract_ids = fields.One2many(
        'construction.subcontract', 'project_id', string='Subcontracts'
    )
    workforce_ids = fields.One2many(
        'construction.project.employee', 'project_id', string='Project Workforce'
    )
    guarantee_ids = fields.One2many('construction.guarantee', 'project_id', string='Guarantees')
    equipment_request_ids = fields.One2many(
        'construction.equipment.request', 'project_id', string='Equipment Requests'
    )

    original_amount = fields.Monetary(
        compute='_compute_boq_amounts', string='Original Contract Value'
    )
    change_order_amount = fields.Monetary(
        compute='_compute_boq_amounts', string='Change Orders Value'
    )
    contract_amount = fields.Monetary(
        compute='_compute_boq_amounts', string='Current Contract Value'
    )
    estimated_cost = fields.Monetary(compute='_compute_boq_amounts', string='Estimated Cost')
    progress_percent = fields.Float(
        compute='_compute_progress',
        string='Progress (%)',
        help=(
            "Progress of the works: progress of each BOQ item (consumption of its materials,"
            " equipment and subcontracted works) weighted by the item weights."
        ),
    )
    certified_progress_percent = fields.Float(
        compute='_compute_boq_amounts',
        string='Certified Progress (%)',
        help=(
            "Progress certified by the owner: quantities of the approved owner invoices over the"
            " BOQ quantities, weighted by the item weights."
        ),
    )
    invoiced_amount = fields.Monetary(compute='_compute_financials', string='Invoiced to Owner')
    retention_held = fields.Monetary(compute='_compute_financials', string='Retention Held')
    retention_refunded = fields.Monetary(compute='_compute_financials', string='Retention Refunded')
    retention_balance = fields.Monetary(compute='_compute_financials', string='Retention Balance')
    advance_received = fields.Monetary(compute='_compute_financials', string='Advance Received')
    advance_deducted = fields.Monetary(compute='_compute_financials', string='Advance Deducted')
    advance_balance = fields.Monetary(compute='_compute_financials', string='Advance Remaining')
    insurance_paid = fields.Monetary(compute='_compute_financials', string='Insurance Paid')
    insurance_refunded = fields.Monetary(compute='_compute_financials', string='Insurance Refunded')
    deductions_total = fields.Monetary(compute='_compute_financials', string='Variable Deductions')

    boq_item_count = fields.Integer(compute='_compute_counts', string='BOQ Items Count')
    change_order_count = fields.Integer(compute='_compute_counts', string='Change Orders Count')
    owner_invoice_count = fields.Integer(compute='_compute_counts', string='Owner Invoices Count')
    material_request_count = fields.Integer(
        compute='_compute_counts', string='Material Requests Count'
    )
    subcontract_count = fields.Integer(compute='_compute_counts', string='Subcontracts Count')
    equipment_request_count = fields.Integer(
        compute='_compute_counts', string='Equipment Requests Count'
    )
    purchase_count = fields.Integer(compute='_compute_counts', string='Purchase Orders Count')
    picking_count = fields.Integer(compute='_compute_counts', string='Transfers Count')
    move_count = fields.Integer(compute='_compute_counts', string='Journal Entries Count')
    equipment_count = fields.Integer(compute='_compute_counts', string='Equipment on Site')
    workforce_count = fields.Integer(compute='_compute_counts', string='Workforce Count')
    guarantee_count = fields.Integer(compute='_compute_counts', string='Guarantees Count')
    labor_cost_allocated = fields.Monetary(compute='_compute_counts', string='Labor Cost Allocated')

    _code_uniq = models.Constraint('unique(code)', 'The project code must be unique.')
    _tender_uniq = models.Constraint(
        'unique(tender_id)', 'A construction project already exists for this tender.'
    )

    @api.depends('advance_payment_percent', 'final_insurance_percent', 'boq_item_ids.amount_total')
    def _compute_contract_terms(self):
        """Amounts follow the percentage and the current contract value (change orders included).
        Without a percentage the amount stays as entered."""
        for project in self:
            contract_value = sum(project.boq_item_ids.mapped('amount_total'))
            currency = project.currency_id or self.env.company.currency_id
            if project.advance_payment_percent:
                project.advance_payment_amount = currency.round(
                    contract_value * project.advance_payment_percent / 100.0
                )
            else:
                project.advance_payment_amount = project.advance_payment_amount
            if project.final_insurance_percent:
                project.final_insurance_amount = currency.round(
                    contract_value * project.final_insurance_percent / 100.0
                )
            else:
                project.final_insurance_amount = project.final_insurance_amount

    @api.onchange('advance_payment_percent')
    def _onchange_advance_payment_percent(self):
        for project in self:
            if project.advance_payment_percent and not project.advance_deduction_percent:
                project.advance_deduction_percent = project.advance_payment_percent

    @api.depends('start_date', 'duration_months')
    def _compute_end_date(self):
        for project in self:
            if project.start_date and project.duration_months > 0:
                project.end_date = project.start_date + relativedelta(
                    months=project.duration_months, days=-1
                )
            else:
                project.end_date = False

    @api.depends(
        'boq_item_ids.amount_total',
        'boq_item_ids.original_amount',
        'boq_item_ids.estimated_cost',
        'boq_item_ids.weight_percent',
        'boq_item_ids.invoiced_quantity',
        'boq_item_ids.total_quantity',
        'boq_item_ids.owner_invoice_line_ids.current_quantity',
        'boq_item_ids.owner_invoice_line_ids.invoice_state',
    )
    def _compute_boq_amounts(self):
        for project in self:
            items = project.boq_item_ids
            project.original_amount = sum(items.mapped('original_amount'))
            project.contract_amount = sum(items.mapped('amount_total'))
            project.change_order_amount = project.contract_amount - project.original_amount
            project.estimated_cost = sum(items.mapped('estimated_cost'))
            project.certified_progress_percent = model_attribute(
                items, '_get_certified_progress_percent'
            )()

    def _compute_progress(self):
        for project in self:
            project.progress_percent = model_attribute(
                project.boq_item_ids, '_get_progress_percent'
            )()

    def _compute_financials(self):
        for project in self:
            invoices = project.owner_invoice_ids.filtered(
                lambda inv: inv.state == 'invoiced' and inv.sudo().move_id.state == 'posted'
            )
            operations = project.operation_ids.filtered(lambda op: op.state == 'posted')
            project.invoiced_amount = sum(invoices.mapped('gross_amount'))
            project.retention_held = sum(invoices.mapped('retention_amount'))
            project.retention_refunded = sum(
                operations.filtered(lambda op: op.operation_type == 'retention_refund').mapped(
                    'amount'
                )
            )
            project.retention_balance = project.retention_held - project.retention_refunded
            project.advance_received = sum(
                operations.filtered(lambda op: op.operation_type == 'advance_received').mapped(
                    'amount'
                )
            ) + sum(
                invoices.filtered(lambda inv: inv.invoice_type == 'advance').mapped(
                    'advance_amount'
                )
            )
            project.advance_deducted = sum(invoices.mapped('advance_deduction_amount'))
            project.advance_balance = project.advance_received - project.advance_deducted

            project.insurance_paid = sum(
                operations.filtered(lambda op: op.operation_type == 'insurance_payment').mapped(
                    'amount'
                )
            ) + sum(invoices.mapped('insurance_amount'))
            project.insurance_refunded = sum(
                operations.filtered(lambda op: op.operation_type == 'insurance_refund').mapped(
                    'amount'
                )
            )
            project.deductions_total = sum(invoices.mapped('deduction_total'))

    @api.model
    def _financial_fields(self):
        return [
            'invoiced_amount',
            'retention_held',
            'retention_refunded',
            'retention_balance',
            'advance_received',
            'advance_deducted',
            'advance_balance',
            'insurance_paid',
            'insurance_refunded',
            'deductions_total',
        ]

    def _compute_counts(self):
        purchase_model = self.env['purchase.order'].sudo()
        picking_model = self.env['stock.picking'].sudo()
        move_model = self.env['account.move'].sudo()
        equipment_model = self.env['construction.equipment'].sudo()
        for project in self:
            project.boq_item_count = len(project.boq_item_ids)
            project.change_order_count = len(project.change_order_ids)
            project.owner_invoice_count = len(project.owner_invoice_ids)
            project.material_request_count = len(project.material_request_ids)
            project.subcontract_count = len(project.subcontract_ids)
            project.equipment_request_count = len(project.equipment_request_ids)
            project.workforce_count = len(
                project.workforce_ids.filtered(lambda w: w.state == 'active')
            )
            project.guarantee_count = len(project.guarantee_ids)
            project.labor_cost_allocated = sum(project.workforce_ids.cost_line_ids.mapped('amount'))
            if project.id:
                project.purchase_count = purchase_model.search_count(
                    [('construction_project_id', '=', project.id)]
                )
                project.picking_count = picking_model.search_count(
                    [('construction_project_id', '=', project.id)]
                )
                project.move_count = move_model.search_count(
                    [('construction_project_id', '=', project.id)]
                )
                project.equipment_count = equipment_model.search_count(
                    [('current_project_id', '=', project.id)]
                )
            else:
                project.purchase_count = project.picking_count = project.move_count = (
                    project.equipment_count
                ) = 0

    @api.depends('name')
    def _compute_display_name(self):

        for project in self:
            project.display_name = project.name or ''

    @api.constrains(
        'guarantee_percent',
        'advance_deduction_percent',
        'duration_months',
        'final_insurance_amount',
        'advance_payment_percent',
        'final_insurance_percent',
        'advance_payment_amount',
    )
    def _check_financial_values(self):
        for project in self:
            if not 0.0 <= project.advance_payment_percent <= 100.0:
                raise ValidationError(
                    _('The advance payment percentage must be between 0 and 100.')
                )
            if not 0.0 <= project.final_insurance_percent <= 100.0:
                raise ValidationError(
                    _('The final insurance percentage must be between 0 and 100.')
                )
            if project.advance_payment_amount < 0:
                raise ValidationError(_('The agreed advance payment cannot be negative.'))
            if not 0.0 <= project.guarantee_percent <= 100.0:
                raise ValidationError(_('The work guarantee percentage must be between 0 and 100.'))
            if not 0.0 <= project.advance_deduction_percent <= 100.0:
                raise ValidationError(
                    _('The advance deduction percentage must be between 0 and 100.')
                )
            if project.duration_months < 0:
                raise ValidationError(_('The project duration cannot be negative.'))
            if project.final_insurance_amount < 0:
                raise ValidationError(_('The final insurance amount cannot be negative.'))

    @api.constrains('tender_id')
    def _check_tender_awarded(self):
        for project in self:
            if project.tender_id and project.tender_id.state != 'awarded':
                raise ValidationError(
                    _('A construction project can only be created from an awarded tender.')
                )

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('construction.project') or _(
                    'New'
                )
        projects = super().create(vals_list)
        model_attribute(projects, '_create_project_resources')()
        return projects

    CONTRACT_TERM_FIELDS = (
        'advance_payment_percent',
        'advance_payment_amount',
        'guarantee_percent',
        'advance_deduction_percent',
        'final_insurance_percent',
        'final_insurance_amount',
    )

    def _is_boq_locked(self):
        """The BOQ is approved once the project is started, and stays locked even if the project is
        cancelled and reset to draft: it changes only through change orders.
        """
        self.ensure_one()
        return self.state != 'draft' or self.was_started

    def _check_construction_manager(self):
        """Project lifecycle (start, suspend, handovers, cancel...) is decided by Senior
        Management."""
        if not self.env.su and not self.env.user.has_group(
            'construction_management.group_construction_manager'
        ):
            raise UserError(_('Only Senior Management can change the status of a project.'))

    def write(self, vals):
        """Write."""
        if (
            self.CONTRACT_TERM_FIELDS
            and set(self.CONTRACT_TERM_FIELDS).intersection(vals)
            and not self.env.su
            and any(project.state != 'draft' for project in self)
            and not (
                self.env.user.has_group('construction_management.group_construction_manager')
                or self.env.user.has_group('construction_management.group_construction_finance')
            )
        ):
            raise UserError(
                _(
                    'The financial terms of a started project can only be changed by Senior'
                    ' Management or Finance.'
                )
            )
        res = super().write(vals)
        if 'name' in vals:
            for project in self:
                if project.analytic_account_id:
                    project.analytic_account_id.sudo().name = project.name
                if project.project_id:
                    project.project_id.sudo().name = project.name
                if project.warehouse_id:
                    project.warehouse_id.sudo().name = model_attribute(
                        project, '_get_warehouse_name'
                    )(project.warehouse_id)
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_project(self):
        for project in self:
            if (
                project.state != 'draft'
                or project.owner_invoice_ids
                or project.material_request_ids
            ):
                raise UserError(
                    _(
                        'Only draft projects without transactions can be deleted. Cancel project %s'
                        ' instead.',
                        project.display_name,
                    )
                )

    def _get_analytic_plan(self):
        plan = self.env.ref(
            'construction_management.analytic_plan_construction_projects', raise_if_not_found=False
        )
        if not plan:
            plan = (
                self.env['account.analytic.plan']
                .sudo()
                .create({'name': _('Construction Projects')})
            )
        return plan

    def _get_unique_warehouse_code(self):
        self.ensure_one()
        warehouse_model = self.env['stock.warehouse'].sudo().with_context(active_test=False)
        base_number = self.id % 10000
        for offset in range(10000):
            code = f'C{(base_number + offset) % 10000:04d}'
            if not warehouse_model.search_count(
                [('code', '=', code), ('company_id', '=', self.company_id.id)]
            ):
                return code
        raise UserError(
            _('Unable to generate a unique warehouse short name for project %s.', self.display_name)
        )

    def _get_warehouse_name(self, warehouse=False):
        """Name of the project warehouse: the project name (with the project code only when another
        warehouse of the company already has this name, warehouse names being unique per
        company).
        """
        self.ensure_one()
        name = (self.name or '')[:100]
        taken = (
            self.env['stock.warehouse']
            .sudo()
            .with_context(active_test=False)
            .search_count(
                [
                    ('name', '=', name),
                    ('company_id', '=', self.company_id.id),
                    ('id', '!=', warehouse.id if warehouse else False),
                ]
            )
        )
        return f'{name[:80]} ({self.code})' if taken else name

    def _create_project_resources(self):
        for project in self:
            label = project.name
            company = project.company_id
            if not project.analytic_account_id:

                analytic = (
                    self.env['account.analytic.account']
                    .sudo()
                    .with_company(company)
                    .create(
                        {
                            'name': label,
                            'plan_id': model_attribute(project, '_get_analytic_plan')().id,
                            'company_id': company.id,
                        }
                    )
                )
                project.analytic_account_id = analytic
            if not project.project_id:
                odoo_project = (
                    self.env['project.project']
                    .sudo()
                    .with_company(company)
                    .create(
                        {
                            'name': label,
                            'partner_id': project.partner_id.id,
                            'company_id': company.id,
                            'account_id': project.analytic_account_id.id,
                            'user_id': project.manager_id.id,
                            'date_start': project.start_date,
                            'date': project.end_date,
                        }
                    )
                )
                project.project_id = odoo_project
            if not project.warehouse_id:
                warehouse = (
                    self.env['stock.warehouse']
                    .sudo()
                    .with_company(company)
                    .create(
                        {
                            'name': model_attribute(project, '_get_warehouse_name')(),
                            'code': model_attribute(project, '_get_unique_warehouse_code')(),
                            'company_id': company.id,
                            'partner_id': project.partner_id.id,
                        }
                    )
                )
                project.warehouse_id = warehouse

    def _get_analytic_distribution(self):
        self.ensure_one()
        if not self.analytic_account_id:
            return False
        return {str(self.analytic_account_id.id): 100.0}

    def _get_company_account(self, field_name):
        """Return the configured company account or raise a clear error."""
        self.ensure_one()
        account = self.company_id[field_name]
        if not account:
            label = self.company_id._fields[field_name].string
            raise UserError(
                _(
                    'Please configure "%(account)s" in Construction settings for company'
                    ' %(company)s.',
                    account=label,
                    company=self.company_id.name,
                )
            )
        return account

    @api.model
    def _check_invoice_line_account(self, account, label):
        if account.account_type in ('asset_receivable', 'liability_payable'):
            raise UserError(
                _(
                    'Account %(account)s used for "%(label)s" is a receivable/payable account and'
                    ' cannot be used on invoice lines. Please use a current asset or liability'
                    ' account.',
                    account=account.display_name,
                    label=label,
                )
            )
        return account

    def _get_misc_journal(self):
        self.ensure_one()
        journal = self.company_id.construction_journal_id
        if not journal:
            journal = self.env['account.journal'].search(
                [('type', '=', 'general'), ('company_id', '=', self.company_id.id)], limit=1
            )
        if not journal:
            raise UserError(_('Please configure a miscellaneous journal in Construction settings.'))
        return journal

    def action_start(self):
        """Start."""
        self._check_construction_manager()
        for project in self:
            if project.state != 'draft':
                raise UserError(_('Only draft projects can be started.'))
            if not project.start_date:
                raise UserError(
                    _('Please set the project start date (site handover date) before starting.')
                )
            model_attribute(project, '_create_project_resources')()
        self.write({'state': 'running', 'was_started': True})
        self.action_sync_material_requirements()

    def action_suspend(self):
        """Suspend."""
        self._check_construction_manager()
        for project in self:
            if project.state != 'running':
                raise UserError(_('Only running projects can be suspended.'))
            project.write(
                {
                    'state': 'suspended',
                    'suspension_date': project.suspension_date or fields.Date.context_today(self),
                }
            )

    def action_resume(self):
        """Resume."""
        self._check_construction_manager()
        for project in self:
            if project.state != 'suspended':
                raise UserError(_('Only suspended projects can be resumed.'))
        self.write({'state': 'running'})

    def action_preliminary_handover(self):
        """Preliminary handover."""
        self._check_construction_manager()
        for project in self:
            if project.state != 'running':
                raise UserError(_('Preliminary handover is only possible for running projects.'))
            pending = project.owner_invoice_ids.filtered(
                lambda inv: inv.state in ('to_approve', 'to_approve_exceptional', 'approved')
                or (inv.state == 'invoiced' and inv.sudo().move_id.state == 'draft')
            )
            if pending:
                raise UserError(
                    _(
                        'Please process or cancel the pending owner invoices and post their'
                        ' customer invoices before the preliminary handover: %s',
                        ', '.join(pending.mapped('name')),
                    )
                )
            project.write(
                {
                    'state': 'preliminary',
                    'preliminary_handover_date': (
                        project.preliminary_handover_date or fields.Date.context_today(self)
                    ),
                }
            )
            model_attribute(project, '_refund_retention')()
            released_types = ['retention']
            project.invalidate_recordset(self._financial_fields())
            if project.advance_balance <= 0:
                released_types.append('advance')
            model_attribute(project.guarantee_ids.sudo(), '_auto_release')(
                released_types, project.preliminary_handover_date
            )

    def _get_open_operations(self, for_cancel=False):
        """Operations still running on the project, returned as a list of human readable labels."""
        self.ensure_one()
        labels = []
        subcontracts = self.subcontract_ids.filtered(lambda c: c.state in ('to_approve', 'active'))
        if subcontracts:
            labels.append(_('subcontracts %s (close them)', ', '.join(subcontracts.mapped('name'))))
        sub_invoices = (
            self.env['construction.subcontract.invoice']
            .sudo()
            .search(
                [
                    ('project_id', '=', self.id),
                    ('state', 'in', ('draft', 'site_approved', 'mgmt_approved')),
                ]
            )
        )
        if sub_invoices:
            labels.append(_('subcontractor invoices %s', ', '.join(sub_invoices.mapped('name'))))
        requests = self.material_request_ids.filtered(
            lambda r: r.state in ('to_approve', 'approved')
        )
        if requests:
            labels.append(_('material requests %s', ', '.join(requests.mapped('name'))))
        equipment = self._get_site_equipment()
        if equipment:
            labels.append(
                _(
                    'equipment still on site or in transit: %s',
                    ', '.join(equipment.mapped('display_name')),
                )
            )
        if for_cancel:
            orders = (
                self.env['purchase.order']
                .sudo()
                .search(
                    [
                        ('construction_project_id', '=', self.id),
                        ('state', 'not in', ('cancel', 'done')),
                    ]
                )
            )
            orders = orders.filtered(
                lambda o: o.state != 'purchase'
                or any(
                    l.qty_received < l.product_qty
                    for l in o.order_line
                    if not l.display_type and l.product_id.type != 'service'
                )
            )
            if orders:
                labels.append(_('purchase orders %s', ', '.join(orders.mapped('name'))))
            rentals = self.equipment_request_ids.filtered(
                lambda r: r.state in ('assigned', 'rental')
            )
            if rentals:
                labels.append(_('equipment requests %s', ', '.join(rentals.mapped('name'))))
        return labels

    def _get_site_equipment(self):
        """Equipment still linked to the project site (extended with the equipment in transit)."""
        self.ensure_one()
        return (
            self.env['construction.equipment'].sudo().search([('current_project_id', '=', self.id)])
        )

    def action_final_handover(self):
        """Final handover."""
        self._check_construction_manager()
        for project in self:
            if project.state != 'preliminary':
                raise UserError(
                    _('Final handover is only possible after the preliminary handover.')
                )
            open_operations = model_attribute(project, '_get_open_operations')()
            if open_operations:
                raise UserError(
                    _(
                        'Project %(project)s still has open operations: %(ops)s.',
                        project=project.display_name,
                        ops='; '.join(open_operations),
                    )
                )
            project.write(
                {
                    'state': 'final',
                    'final_handover_date': (
                        project.final_handover_date or fields.Date.context_today(self)
                    ),
                }
            )
            model_attribute(project, '_refund_insurance')()
            model_attribute(project.guarantee_ids.sudo(), '_auto_release')(
                ['final', 'retention', 'advance'], project.final_handover_date
            )

    def action_cancel(self):
        """Cancel."""
        self._check_construction_manager()
        for project in self:
            if project.owner_invoice_ids.filtered(lambda inv: inv.state == 'invoiced'):
                raise UserError(
                    _(
                        'Project %s has owner invoices and cannot be cancelled.',
                        project.display_name,
                    )
                )
            open_operations = model_attribute(project, '_get_open_operations')(for_cancel=True)
            if open_operations:
                raise UserError(
                    _(
                        'Project %(project)s still has open operations: %(ops)s.',
                        project=project.display_name,
                        ops='; '.join(open_operations),
                    )
                )
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        """Reset draft."""
        self._check_construction_manager()
        for project in self:
            if project.state != 'cancelled':
                raise UserError(_('Only cancelled projects can be reset to draft.'))
        self.write({'state': 'draft'})

    def _refund_retention(self):
        operation_model = self.env['construction.project.operation']
        self.invalidate_recordset(self._financial_fields())
        for project in self:
            amount = project.retention_balance
            if float_is_zero(amount, precision_rounding=project.currency_id.rounding) or amount < 0:
                continue
            operation = operation_model.create(
                {
                    'project_id': project.id,
                    'operation_type': 'retention_refund',
                    'amount': amount,
                    'date': project.preliminary_handover_date or fields.Date.context_today(self),
                    'name': _('Work guarantee refund - preliminary handover'),
                }
            )
            operation.action_post()

    def _refund_insurance(self):
        operation_model = self.env['construction.project.operation']
        self.invalidate_recordset(self._financial_fields())
        for project in self:
            amount = project.insurance_paid - project.insurance_refunded
            if float_is_zero(amount, precision_rounding=project.currency_id.rounding) or amount < 0:
                continue
            operation = operation_model.create(
                {
                    'project_id': project.id,
                    'operation_type': 'insurance_refund',
                    'amount': amount,
                    'date': project.final_handover_date or fields.Date.context_today(self),
                    'name': _('Final insurance refund - final handover'),
                }
            )
            operation.action_post()

    def action_sync_material_requirements(self):
        """Sync material requirements."""
        requirement_model = self.env['construction.material.requirement']
        for project in self:
            components = project.boq_item_ids.component_ids.filtered(
                lambda c: c.component_type == 'material' and c.product_id
            )

            existing = set(project.material_requirement_ids.product_id.ids)
            to_create = []
            for component in components:
                uom = component.uom_id or component.product_id.uom_id
                key = component.product_id.id
                if key not in existing:
                    existing.add(key)
                    to_create.append(
                        {
                            'project_id': project.id,
                            'product_id': component.product_id.id,
                            'uom_id': uom.id,
                        }
                    )
            if to_create:
                requirement_model.create(to_create)
        return True

    def _action_open(self, model, name, domain, context=None, views='list,form'):
        self.ensure_one()
        ctx = {'default_project_id': self.id}
        ctx.update(context or {})
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': views,
            'domain': domain,
            'context': ctx,
        }

    def action_view_boq(self):
        """View boq."""
        return self._action_open('construction.boq.item', _('BOQ'), [('project_id', '=', self.id)])

    def action_view_change_orders(self):
        """View change orders."""
        return self._action_open(
            'construction.change.order', _('Change Orders'), [('project_id', '=', self.id)]
        )

    def action_view_owner_invoices(self):
        """View owner invoices."""
        return self._action_open(
            'construction.owner.invoice', _('Owner Invoices'), [('project_id', '=', self.id)]
        )

    def action_view_material_requirements(self):
        """View material requirements."""
        self.action_sync_material_requirements()
        return self._action_open(
            'construction.material.requirement',
            _('Material Requirements'),
            [('project_id', '=', self.id)],
            views='list',
        )

    def action_view_material_requests(self):
        """View material requests."""
        return self._action_open(
            'construction.material.request', _('Material Requests'), [('project_id', '=', self.id)]
        )

    def action_view_subcontracts(self):
        """View subcontracts."""
        return self._action_open(
            'construction.subcontract', _('Subcontracts'), [('project_id', '=', self.id)]
        )

    def action_view_equipment_requests(self):
        """View equipment requests."""
        return self._action_open(
            'construction.equipment.request',
            _('Equipment Requests'),
            [('project_id', '=', self.id)],
        )

    def action_view_equipment(self):
        """View equipment."""
        return self._action_open(
            'construction.equipment',
            _('Equipment on Site'),
            [('current_project_id', '=', self.id)],
            context={'default_project_id': False},
        )

    def action_view_purchases(self):
        """View purchases."""
        return self._action_open(
            'purchase.order',
            _('Purchase Orders'),
            [('construction_project_id', '=', self.id)],
            context={'default_construction_project_id': self.id, 'default_project_id': False},
        )

    def action_view_pickings(self):
        """View pickings."""
        return self._action_open(
            'stock.picking',
            _('Transfers'),
            [('construction_project_id', '=', self.id)],
            context={'default_construction_project_id': self.id, 'default_project_id': False},
        )

    def action_view_moves(self):
        """View moves."""
        return self._action_open(
            'account.move',
            _('Journal Entries'),
            [('construction_project_id', '=', self.id)],
            context={'default_construction_project_id': self.id, 'default_project_id': False},
        )

    def action_view_workforce(self):
        """View workforce."""
        return self._action_open(
            'construction.project.employee', _('Project Workforce'), [('project_id', '=', self.id)]
        )

    def action_view_guarantees(self):
        """View guarantees."""
        return self._action_open(
            'construction.guarantee', _('Guarantees'), [('project_id', '=', self.id)]
        )

    def action_open_labor_cost_wizard(self):
        """Open labor cost wizard."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Allocate Labor Cost'),
            'res_model': 'construction.labor.cost.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_project_id': self.id},
        }

    def action_view_odoo_project(self):
        """View odoo project."""
        self.ensure_one()
        if not self.project_id:
            raise UserError(_('No Odoo project is linked to this construction project.'))
        return {
            'type': 'ir.actions.act_window',
            'name': self.project_id.name,
            'res_model': 'project.project',
            'res_id': self.project_id.id,
            'view_mode': 'form',
        }

    def action_view_analytic_lines(self):
        """View analytic lines."""
        self.ensure_one()
        if not self.analytic_account_id:
            raise UserError(_('No cost center is linked to this project.'))
        return analytic_lines_action(self.analytic_account_id, _('Cost Center Items'))
