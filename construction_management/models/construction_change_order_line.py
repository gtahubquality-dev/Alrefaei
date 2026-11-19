"""Construction change order line for construction management."""

from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare
from odoo.tools import float_is_zero

from .construction_common import check_change_order_editable


class ConstructionChangeOrderLine(models.Model):
    """Construction change order line."""

    _name = 'construction.change.order.line'
    _description = 'BOQ Change Order Line'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one(
        'construction.change.order',
        string='Change Order',
        required=True,
        ondelete='cascade',
        index=True,
    )
    project_id = fields.Many2one(related='order_id.project_id', store=True, string='Project')
    company_id = fields.Many2one(related='order_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='order_id.currency_id', string='Currency')
    state = fields.Selection(related='order_id.state', store=True, string='Status')
    sequence = fields.Integer(default=10)
    change_type = fields.Selection(
        [
            ('quantity', 'Quantity Change on Existing Item'),
            ('new', 'New BOQ Item'),
        ],
        string='Change Type',
        required=True,
        default='quantity',
    )
    boq_item_id = fields.Many2one(
        'construction.boq.item',
        string='BOQ Item',
        index=True,
        domain="[('project_id', '=', project_id)]",
    )
    current_quantity = fields.Float(
        related='boq_item_id.total_quantity', string='Current BOQ Quantity'
    )
    previous_quantity = fields.Float(
        string='Quantity Before Approval', digits='Product Unit', readonly=True, copy=False
    )
    code = fields.Char(string='Item Code')
    name = fields.Char(string='Description')
    description = fields.Text(string='Contractual Description')
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure')
    quantity = fields.Float(
        string='Quantity',
        digits='Product Unit',
        required=True,
        default=0.0,
        help=(
            "For quantity changes: the increase (positive) or decrease (negative). For new items:"
            " the item quantity."
        ),
    )
    unit_price = fields.Monetary(string='Unit Price')
    weight_percent = fields.Float(string='Item Weight (%)', digits=(16, 4))
    value_change = fields.Monetary(
        compute='_compute_value_change', store=True, string='Value Change'
    )
    component_ids = fields.One2many(
        'construction.change.order.component', 'line_id', string='Cost Components', copy=True
    )
    new_boq_item_id = fields.Many2one(
        'construction.boq.item', string='Created BOQ Item', readonly=True, copy=False
    )

    @api.depends('change_type', 'quantity', 'unit_price', 'boq_item_id.unit_price')
    def _compute_value_change(self):
        for line in self:
            price = (
                line.boq_item_id.unit_price if line.change_type == 'quantity' else line.unit_price
            )
            line.value_change = line.quantity * price

    @api.onchange('boq_item_id')
    def _onchange_boq_item_id(self):
        for line in self:
            if line.boq_item_id and line.change_type == 'quantity':
                line.name = line.boq_item_id.display_name
                line.uom_id = line.boq_item_id.uom_id
                line.unit_price = line.boq_item_id.unit_price

    def _check_line_values(self):
        for line in self:
            rounding = 0.0001
            if line.change_type == 'quantity':
                item = line.boq_item_id
                if not item:
                    raise ValidationError(
                        _('Please select the BOQ item for every quantity change line.')
                    )
                if item.project_id != line.order_id.project_id:
                    raise ValidationError(
                        _(
                            'BOQ item %s does not belong to the change order project.',
                            item.display_name,
                        )
                    )
                if float_is_zero(line.quantity, precision_rounding=rounding):
                    raise ValidationError(
                        _('The quantity change of %s cannot be zero.', item.display_name)
                    )
                new_total = item.total_quantity + line.quantity
                if float_compare(new_total, 0.0, precision_rounding=rounding) < 0:
                    raise ValidationError(
                        _('The new quantity of %s cannot be negative.', item.display_name)
                    )
                if (
                    float_compare(new_total, item.invoiced_quantity, precision_rounding=rounding)
                    < 0
                ):
                    raise ValidationError(
                        _(
                            'The new quantity of %(item)s (%(new)s) is lower than the quantity'
                            ' already invoiced (%(inv)s).',
                            item=item.display_name,
                            new=new_total,
                            inv=item.invoiced_quantity,
                        )
                    )
                if (
                    float_compare(
                        new_total, item.subcontracted_quantity, precision_rounding=rounding
                    )
                    < 0
                ):
                    raise ValidationError(
                        _(
                            'The new quantity of %(item)s is lower than the quantity assigned to'
                            ' subcontractors (%(sub)s).',
                            item=item.display_name,
                            sub=item.subcontracted_quantity,
                        )
                    )
            else:
                if not line.name or not line.uom_id:
                    raise ValidationError(
                        _('New BOQ items require a description and a unit of measure.')
                    )
                if float_compare(line.quantity, 0.0, precision_rounding=rounding) <= 0:
                    raise ValidationError(
                        _('The quantity of new item %s must be positive.', line.name)
                    )
                if line.unit_price < 0:
                    raise ValidationError(
                        _('The unit price of new item %s cannot be negative.', line.name)
                    )

    def _check_change_order_editable(self, orders):
        """Lines of a submitted, approved or rejected change order are frozen: an approved change
        order is applied to the BOQ, it is changed by a new change order.
        """
        check_change_order_editable(self, orders)

    @api.model_create_multi
    def create(self, vals_list):
        """Create."""
        records = super().create(vals_list)
        self._check_change_order_editable(records.order_id)
        return records

    def write(self, vals):
        """Write."""
        self._check_change_order_editable(self.order_id)
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_frozen_change_order(self):
        self._check_change_order_editable(self.order_id.filtered(lambda o: o.state != 'cancelled'))

    @api.constrains('weight_percent')
    def _check_weight(self):
        for line in self:
            if not 0.0 <= line.weight_percent <= 100.0:
                raise ValidationError(_('Item weight must be between 0 and 100.'))
