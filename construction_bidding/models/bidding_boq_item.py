"""Construction bidding bidding boq item support."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import ValidationError


class BiddingBoqItem(models.Model):
    """Bidding Boq Item."""

    _name = 'bidding.boq.item'
    _description = 'Bidding Estimated BOQ Item'
    _order = 'tender_id, sequence, id'

    tender_id = fields.Many2one(
        'bidding.tender', string='Tender', required=True, ondelete='cascade', index=True)
    tender_state = fields.Selection(related='tender_id.state', string='Tender Status')
    company_id = fields.Many2one(related='tender_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='tender_id.currency_id', string='Currency')
    sequence = fields.Integer(default=10)
    code = fields.Char(string='Item Code')
    name = fields.Char(string='Item Name', required=True)
    description = fields.Text(string='Description')
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', required=True)
    quantity = fields.Float(string='Estimated Quantity', digits='Product Unit', default=1.0)
    unit_price = fields.Monetary(string='Estimated Unit Price')
    amount_total = fields.Monetary(
        string='Estimated Total Price', compute='_compute_amounts', store=True)

    component_ids = fields.One2many(
        'bidding.boq.component', 'item_id', string='Cost Components', copy=True)
    material_ids = fields.One2many(
        'bidding.boq.component', 'item_id', string='Materials',
        domain=[('component_type', '=', 'material')])
    equipment_ids = fields.One2many(
        'bidding.boq.component', 'item_id', string='Equipment',
        domain=[('component_type', '=', 'equipment')])
    subcontract_ids = fields.One2many(
        'bidding.boq.component', 'item_id', string='Subcontractors',
        domain=[('component_type', '=', 'subcontract')])
    labor_ids = fields.One2many(
        'bidding.boq.component', 'item_id', string='External Labor',
        domain=[('component_type', '=', 'labor')])

    material_cost = fields.Monetary(compute='_compute_costs', store=True, string='Materials Cost')
    equipment_cost = fields.Monetary(compute='_compute_costs', store=True, string='Equipment Cost')
    subcontract_cost = fields.Monetary(compute='_compute_costs', store=True,
        string='Subcontractors Cost')
    labor_cost = fields.Monetary(compute='_compute_costs', store=True, string='External Labor Cost')
    estimated_cost = fields.Monetary(
        compute='_compute_costs', store=True, string='Estimated Total Cost')
    unit_cost = fields.Monetary(compute='_compute_costs', store=True, string='Estimated Unit Cost')
    profit_amount = fields.Monetary(compute='_compute_amounts', store=True,
        string='Expected Profit')

    weight_percent = fields.Float(
        string='Item Weight (%)', digits=(16, 4),
        help="Contribution of this item to the overall project execution progress.")
    cost_percent = fields.Float(
        string='Cost Percentage (%)', digits=(16, 4), compute='_compute_cost_percent', store=True,
        help="Item estimated cost compared to the total estimated BOQ cost.")

    @api.depends('component_ids.total_cost', 'component_ids.component_type', 'quantity')
    def _compute_costs(self):
        for item in self:
            totals = dict.fromkeys(('material', 'equipment', 'subcontract', 'labor'), 0.0)
            for component in item.component_ids:
                if component.component_type in totals:
                    totals[component.component_type] += component.total_cost
            item.material_cost = totals['material']
            item.equipment_cost = totals['equipment']
            item.subcontract_cost = totals['subcontract']
            item.labor_cost = totals['labor']
            item.estimated_cost = sum(totals.values())
            item.unit_cost = item.estimated_cost / item.quantity if item.quantity else 0.0

    @api.depends('quantity', 'unit_price', 'estimated_cost')
    def _compute_amounts(self):
        for item in self:
            item.amount_total = item.quantity * item.unit_price
            item.profit_amount = item.amount_total - item.estimated_cost

    @api.depends('estimated_cost', 'tender_id.total_cost')
    def _compute_cost_percent(self):
        for item in self:
            total = item.tender_id.total_cost
            item.cost_percent = item.estimated_cost / total * 100.0 if total else 0.0

    @api.constrains('quantity', 'unit_price', 'weight_percent')
    def _check_values(self):
        for item in self:
            if item.quantity < 0 or item.unit_price < 0:
                raise ValidationError(_(
                    'Quantity and unit price of BOQ item %s cannot be negative.', item.name))
            if item.weight_percent < 0 or item.weight_percent > 100:
                raise ValidationError(_('Item weight of %s must be between 0 and 100.', item.name))

    @api.model_create_multi
    def create(self, vals_list):
        """Create records and validate their BOQ weights."""
        items = super().create(vals_list)
        if not self.env.context.get('bidding_skip_weight_check'):
            items.tender_id.check_total_weight()
        return items

    def write(self, vals):
        """Update records and validate affected BOQ weights."""
        tenders = self.tender_id
        res = super().write(vals)
        if not self.env.context.get('bidding_skip_weight_check') and (
                'weight_percent' in vals or 'tender_id' in vals):
            (tenders | self.tender_id).check_total_weight()
        return res

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for item in self:
            item.display_name = (
                f'[{item.code}] {item.name or ""}' if item.code else (item.name or '')
            )
