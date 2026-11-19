"""Construction subcontract line construction boq consumption for construction management."""

from odoo import api
from odoo import fields
from odoo import models
from odoo.tools import float_compare
from .boq_consumption_common import boq_component_field
from .construction_boq_consumption import SUBCONTRACT_EXECUTED_STATES

from .runtime import model_attribute


class ConstructionSubcontractLine(models.Model):
    """Construction subcontract line."""

    _inherit = 'construction.subcontract.line'

    boq_component_id = boq_component_field(
        'BOQ Subcontracted Work',
        domain="[('item_id', '=', boq_item_id), ('component_type', '=', 'subcontract')]",
        help_text=(
            "Subcontracted work of the BOQ item covered by this line (filled automatically when the"
            " item has a single subcontracted work)."
        ),
    )
    boq_unit_cost = fields.Monetary(
        compute='_compute_boq_check',
        string='BOQ Unit Cost',
        help=(
            "Estimated subcontract cost per unit in the BOQ (of the subcontracted work when set,"
            " otherwise of all the subcontracted works of the item)."
        ),
    )
    available_quantity = fields.Float(
        compute='_compute_boq_check',
        digits='Product Unit',
        string='Available Quantity',
        help="BOQ quantity of the item not yet assigned to other subcontracts.",
    )
    exceeds_quantity = fields.Boolean(compute='_compute_boq_check', string='Quantity Exceeds BOQ')
    exceeds_price = fields.Boolean(compute='_compute_boq_check', string='Price Exceeds BOQ')
    executed_quantity = fields.Float(
        compute='_compute_executed_quantity',
        digits='Product Unit',
        string='Executed Quantity',
        help="Quantity of the subcontractor invoices approved by the site (and later stages).",
    )

    @api.depends('boq_item_id')
    def _compute_boq_component_id(self):
        for line in self:
            if line.boq_component_id and line.boq_component_id.item_id == line.boq_item_id:
                line.boq_component_id = line.boq_component_id
                continue
            components = line.boq_item_id.component_ids.filtered(
                lambda c: c.component_type == 'subcontract'
            )
            line.boq_component_id = components if len(components) == 1 else False

    @api.model
    def _get_boq_unit_cost(self, item, component):
        """Estimated subcontract cost per unit of a BOQ item (of one of its subcontracted works when
        given), in the unit of the BOQ item.
        """
        if not item.total_quantity:
            return 0.0

        return (
            component.effective_cost if component else item.subcontract_cost
        ) / item.total_quantity

    @api.depends(
        'boq_item_id',
        'boq_component_id',
        'quantity',
        'unit_price',
        'contract_id.line_ids.quantity',
        'contract_id.line_ids.boq_item_id',
    )
    def _compute_boq_check(self):
        for line in self:
            item = line.boq_item_id
            contract = model_attribute(line.contract_id, '_origin')
            if not item:
                line.update(
                    {
                        'boq_unit_cost': 0.0,
                        'available_quantity': 0.0,
                        'exceeds_quantity': False,
                        'exceeds_price': False,
                    }
                )
                continue
            unit_cost = self._get_boq_unit_cost(item, line.boq_component_id)
            other = item.sudo().subcontract_line_ids.filtered(
                lambda l, c=contract: l.contract_id != c
                and l.contract_state in ('to_approve', 'active', 'closed')
            )
            available = item.total_quantity - sum(other.mapped('quantity'))
            assigned = sum(
                line.contract_id.line_ids.filtered(lambda l, i=item: l.boq_item_id == i).mapped(
                    'quantity'
                )
            )
            line.boq_unit_cost = unit_cost
            line.available_quantity = available
            line.exceeds_quantity = float_compare(assigned, available, precision_digits=4) > 0
            line.exceeds_price = (
                bool(unit_cost) and line.currency_id.compare_amounts(line.unit_price, unit_cost) > 0
                if line.currency_id
                else line.unit_price > unit_cost > 0
            )

    @api.onchange('boq_component_id')
    def _onchange_boq_component_id(self):
        for line in self:
            if line.boq_component_id:
                line.unit_price = self._get_boq_unit_cost(line.boq_item_id, line.boq_component_id)

    def _compute_executed_quantity(self):
        for line in self:
            lines = line.invoice_line_ids.filtered(
                lambda l: l.invoice_id.state in SUBCONTRACT_EXECUTED_STATES
            )
            line.executed_quantity = sum(lines.mapped('current_quantity'))
