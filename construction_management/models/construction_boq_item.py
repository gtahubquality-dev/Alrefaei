"""Construction boq item for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from .construction_boq_consumption import CERTIFIED_STATES

from .runtime import model_attribute


class ConstructionBoqItem(models.Model):
    """Construction boq item."""

    _inherit = 'construction.boq.item'

    executed_percent = fields.Float(
        compute='_compute_consumption_summary',
        string='Certified (%)',
        help=(
            "Quantity certified on the owner invoices (approved or invoiced) over the BOQ quantity"
            " of the item (change orders included)."
        ),
    )
    actual_cost = fields.Monetary(
        compute='_compute_consumption_summary',
        string='Actual Cost',
        help=(
            "Operational actual cost of the item: materials billed (posted vendor bills) or"
            " transferred, equipment hours, subcontracted works approved by the site and labor"
            " posted. Work approved but not billed yet is included; the Cost & Revenue report shows"
            " the posted accounting entries only."
        ),
    )
    cost_consumed_percent = fields.Float(
        compute='_compute_consumption_summary',
        string='Cost Consumed (%)',
        help="Actual cost over the estimated cost of the item.",
    )

    progress_percent = fields.Float(
        compute='_compute_progress_percent',
        string='Progress (%)',
        help=(
            "Progress of the item: consumption of its materials, equipment and subcontracted works"
            " (each counted up to 100%), weighted by their estimated cost."
        ),
    )
    certified_quantity = fields.Float(
        compute='_compute_consumption_summary',
        digits='Product Unit',
        string='Certified Quantity',
        help=(
            "Quantity of the owner invoices approved (by the consultant / Senior Management) or"
            " invoiced."
        ),
    )

    @api.depends(
        'component_ids.consumption_percent',
        'component_ids.component_type',
        'component_ids.effective_quantity',
    )
    def _compute_progress_percent(self):
        """Progress of the item: consumption of its materials, equipment and subcontracted works
        (each up to 100%), weighted by their estimated cost (equally when they have no cost).
        """
        for item in self:
            components = item.component_ids.filtered(
                lambda c: c.component_type in ('material', 'equipment', 'subcontract')
                and c.effective_quantity > 0
            )
            total_cost = sum(max(c.effective_cost, 0.0) for c in components)
            progress = 0.0
            for component in components:
                weight = (
                    max(component.effective_cost, 0.0) / total_cost
                    if total_cost
                    else 1.0 / len(components)
                )
                progress += weight * min(max(component.consumption_percent, 0.0), 100.0)
            item.progress_percent = progress

    def _get_certified_quantity(self):
        self.ensure_one()
        lines = self.owner_invoice_line_ids.filtered(lambda l: l.invoice_state in CERTIFIED_STATES)
        return sum(lines.mapped('current_quantity'))

    def _get_item_weights(self):
        """{item id: weight}: the item weights (estimated cost share), or the item values when no
        item has a cost, or equal weights.
        """
        weights = {item.id: max(item.weight_percent, 0.0) for item in self}
        if sum(weights.values()) <= 0:
            weights = {item.id: max(item.amount_total, 0.0) for item in self}
        if sum(weights.values()) <= 0:
            weights = dict.fromkeys(self.ids, 1.0)
        return weights

    def _get_progress_percent(self):
        """Progress of the project: progress of each item (consumption of its works) x its
        weight."""
        items = self.filtered(lambda i: i.total_quantity > 0)
        if not items:
            return 0.0
        weights = model_attribute(items, '_get_item_weights')()
        total_weight = sum(weights.values())
        return sum(weights[item.id] * item.progress_percent for item in items) / total_weight

    def _get_certified_progress_percent(self):
        """Progress certified by the owner: certified quantity / BOQ quantity of each item x its
        weight."""
        items = self.filtered(lambda i: i.total_quantity > 0)
        if not items:
            return 0.0
        weights = model_attribute(items, '_get_item_weights')()
        total_weight = sum(weights.values())
        progress = 0.0
        for item in items:
            ratio = min(
                max(model_attribute(item, '_get_certified_quantity')() / item.total_quantity, 0.0),
                1.0,
            )
            progress += weights[item.id] * ratio
        return progress / total_weight * 100.0

    @api.depends(
        'owner_invoice_line_ids.current_quantity',
        'owner_invoice_line_ids.invoice_state',
        'total_quantity',
        'estimated_cost',
    )
    def _compute_consumption_summary(self):
        for item in self:
            item.certified_quantity = model_attribute(item, '_get_certified_quantity')()
            item.executed_percent = (
                item.certified_quantity / item.total_quantity * 100.0
                if item.total_quantity
                else 0.0
            )
            item.actual_cost = sum(item.component_ids.mapped('actual_cost'))
            item.cost_consumed_percent = (
                item.actual_cost / item.estimated_cost * 100.0 if item.estimated_cost else 0.0
            )

    def action_view_consumption(self):
        """View consumption."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Consumption of %s', self.display_name),
            'res_model': 'construction.boq.component',
            'view_mode': 'list',
            'views': [
                (
                    self.env.ref(
                        'construction_management.view_construction_boq_component_consumption_list'
                    ).id,
                    'list',
                )
            ],
            'domain': [('item_id', '=', self.id)],
            'context': {'create': False},
        }
