"""Construction boq item construction boq for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError

from .runtime import model_attribute


class ConstructionBoqItem(models.Model):
    """Construction boq item."""

    _name = 'construction.boq.item'
    _description = 'Construction Approved BOQ Item'
    _order = 'project_id, sequence, id'

    project_id = fields.Many2one(
        'construction.project', string='Project', required=True, ondelete='cascade', index=True
    )
    project_state = fields.Selection(related='project_id.state', string='Project Status')
    company_id = fields.Many2one(related='project_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='project_id.currency_id', string='Currency')
    sequence = fields.Integer(default=10)
    code = fields.Char(string='Item Code')
    name = fields.Char(string='Item', required=True)
    description = fields.Text(string='Contractual Description')
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', required=True)
    bid_item_id = fields.Many2one(
        'bidding.boq.item', string='Tender BOQ Item', readonly=True, copy=False
    )
    is_change_order_item = fields.Boolean(string='Added by Change Order', readonly=True, copy=False)
    change_order_line_id = fields.Many2one(
        'construction.change.order.line',
        string='Origin Change Order Line',
        readonly=True,
        copy=False,
    )

    quantity = fields.Float(string='Original Quantity', digits='Product Unit', default=1.0)
    change_line_ids = fields.One2many(
        'construction.change.order.line', 'boq_item_id', string='Change Order Lines'
    )
    change_quantity = fields.Float(
        string='Change Orders Quantity',
        digits='Product Unit',
        compute='_compute_quantities',
        store=True,
    )
    total_quantity = fields.Float(
        string='BOQ Quantity',
        digits='Product Unit',
        compute='_compute_quantities',
        store=True,
        help="Approved contractual quantity including approved change orders.",
    )
    unit_price = fields.Monetary(string='Unit Price')
    original_amount = fields.Monetary(
        compute='_compute_amounts', store=True, string='Original Value'
    )
    amount_total = fields.Monetary(compute='_compute_amounts', store=True, string='Current Value')

    owner_invoice_line_ids = fields.One2many(
        'construction.owner.invoice.line', 'boq_item_id', string='Owner Invoice Lines'
    )
    invoiced_quantity = fields.Float(
        string='Invoiced Quantity', digits='Product Unit', compute='_compute_invoiced', store=True
    )
    remaining_quantity = fields.Float(
        string='Remaining Quantity', digits='Product Unit', compute='_compute_invoiced', store=True
    )
    subcontract_line_ids = fields.One2many(
        'construction.subcontract.line', 'boq_item_id', string='Subcontract Lines'
    )
    subcontracted_quantity = fields.Float(
        string='Subcontracted Quantity', digits='Product Unit', compute='_compute_subcontracted'
    )

    component_ids = fields.One2many(
        'construction.boq.component', 'item_id', string='Cost Components'
    )
    material_ids = fields.One2many(
        'construction.boq.component',
        'item_id',
        string='Materials',
        domain=[('component_type', '=', 'material')],
    )
    equipment_ids = fields.One2many(
        'construction.boq.component',
        'item_id',
        string='Equipment',
        domain=[('component_type', '=', 'equipment')],
    )
    subcontract_ids = fields.One2many(
        'construction.boq.component',
        'item_id',
        string='Subcontractors',
        domain=[('component_type', '=', 'subcontract')],
    )
    labor_ids = fields.One2many(
        'construction.boq.component',
        'item_id',
        string='External Labor',
        domain=[('component_type', '=', 'labor')],
    )

    material_cost = fields.Monetary(compute='_compute_costs', store=True, string='Materials Cost')
    equipment_cost = fields.Monetary(compute='_compute_costs', store=True, string='Equipment Cost')
    subcontract_cost = fields.Monetary(
        compute='_compute_costs', store=True, string='Subcontractors Cost'
    )
    labor_cost = fields.Monetary(compute='_compute_costs', store=True, string='External Labor Cost')
    estimated_cost = fields.Monetary(compute='_compute_costs', store=True, string='Estimated Cost')

    weight_percent = fields.Float(
        string='Item Weight (%)',
        digits=(16, 4),
        compute='_compute_cost_percent',
        store=True,
        help=(
            "Weight of the item in the project progress: estimated cost of the item over the total"
            " estimated cost of the BOQ (computed automatically)."
        ),
    )
    cost_percent = fields.Float(
        string='Cost Share (%)',
        digits=(16, 4),
        compute='_compute_cost_percent',
        store=True,
        help="Share of the item in the total estimated cost of the BOQ (= the item weight).",
    )
    cost_ratio_percent = fields.Float(
        string='Cost Ratio (%)',
        digits=(16, 2),
        compute='_compute_cost_ratio_percent',
        store=True,
        help=(
            "Estimated cost of the item over its contract value: below 100% the item is profitable,"
            " above 100% it costs more than it is sold."
        ),
    )
    history_ids = fields.One2many('construction.boq.history', 'boq_item_id', string='History')

    @api.depends(
        'quantity',
        'change_line_ids.quantity',
        'change_line_ids.state',
        'change_line_ids.change_type',
    )
    def _compute_quantities(self):
        for item in self:
            approved = item.change_line_ids.filtered(
                lambda line: line.state == 'approved' and line.change_type == 'quantity'
            )
            item.change_quantity = sum(approved.mapped('quantity'))
            item.total_quantity = item.quantity + item.change_quantity

    @api.depends('quantity', 'total_quantity', 'unit_price')
    def _compute_amounts(self):
        for item in self:
            item.original_amount = item.quantity * item.unit_price
            item.amount_total = item.total_quantity * item.unit_price

    @api.depends(
        'owner_invoice_line_ids.current_quantity',
        'owner_invoice_line_ids.invoice_state',
        'total_quantity',
    )
    def _compute_invoiced(self):
        for item in self:
            lines = item.owner_invoice_line_ids.filtered(
                lambda line: line.invoice_state == 'invoiced'
            )
            item.invoiced_quantity = sum(lines.mapped('current_quantity'))
            item.remaining_quantity = item.total_quantity - item.invoiced_quantity

    @api.depends('subcontract_line_ids.quantity', 'subcontract_line_ids.contract_state')
    def _compute_subcontracted(self):
        for item in self:
            lines = item.subcontract_line_ids.filtered(
                lambda line: line.contract_state in ('to_approve', 'active', 'closed')
            )
            item.subcontracted_quantity = sum(lines.mapped('quantity'))

    @api.depends('estimated_cost', 'amount_total')
    def _compute_cost_ratio_percent(self):
        for item in self:
            item.cost_ratio_percent = (
                item.estimated_cost / item.amount_total * 100.0 if item.amount_total else 0.0
            )

    @api.depends('estimated_cost', 'project_id.boq_item_ids.estimated_cost')
    def _compute_cost_percent(self):
        totals = {}
        for item in self:
            project = item.project_id
            if project.id not in totals:
                totals[project.id] = sum(project.boq_item_ids.mapped('estimated_cost'))
            total = totals[project.id]
            item.cost_percent = item.estimated_cost / total * 100.0 if total else 0.0
            item.weight_percent = item.cost_percent

    @api.depends('component_ids.effective_cost', 'component_ids.component_type')
    def _compute_costs(self):
        for item in self:
            totals = dict.fromkeys(('material', 'equipment', 'subcontract', 'labor'), 0.0)
            for component in item.component_ids:
                if component.component_type in totals:
                    totals[component.component_type] += component.effective_cost
            item.material_cost = totals['material']
            item.equipment_cost = totals['equipment']
            item.subcontract_cost = totals['subcontract']
            item.labor_cost = totals['labor']
            item.estimated_cost = sum(totals.values())

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for item in self:
            item.display_name = (
                f'[{item.code}] {item.name or ""}' if item.code else (item.name or '')
            )

    @api.constrains('quantity', 'unit_price', 'weight_percent', 'cost_percent')
    def _check_values(self):
        for item in self:
            if item.quantity < 0 or item.unit_price < 0:
                raise ValidationError(
                    _('Quantity and unit price of BOQ item %s cannot be negative.', item.name)
                )
            if not 0.0 <= item.weight_percent <= 100.0 or not 0.0 <= item.cost_percent <= 100.0:
                raise ValidationError(
                    _('Weight and cost percentages of %s must be between 0 and 100.', item.name)
                )

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        for vals in vals_list:
            vals.pop('weight_percent', None)
        items = super().create(vals_list)
        if not self.env.su:
            for item in items:
                if model_attribute(item.project_id, '_is_boq_locked')():
                    raise UserError(
                        _(
                            'The approved BOQ of project %s is locked. Use a change order to add'
                            ' items.',
                            item.project_id.display_name,
                        )
                    )
        return items

    def write(self, vals):
        """Write."""
        if 'weight_percent' in vals:
            vals = {key: value for key, value in vals.items() if key != 'weight_percent'}
            if not vals:
                self.check_access('write')
                return True
        protected = {'quantity', 'unit_price', 'project_id', 'uom_id', 'code'}
        if protected.intersection(vals) and not self.env.su:
            for item in self:
                if model_attribute(item.project_id, '_is_boq_locked')():
                    raise UserError(
                        _(
                            'The approved BOQ of project %s is locked. Use a change order to modify'
                            ' quantities or add items.',
                            item.project_id.display_name,
                        )
                    )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_construction_boq_item(self):
        for item in self:
            if model_attribute(item.project_id, '_is_boq_locked')():
                raise UserError(_('You cannot delete BOQ items of a started project.'))
            if item.owner_invoice_line_ids or item.subcontract_line_ids:
                raise UserError(
                    _(
                        'BOQ item %s is used in invoices or subcontracts and cannot be deleted.',
                        item.name,
                    )
                )
