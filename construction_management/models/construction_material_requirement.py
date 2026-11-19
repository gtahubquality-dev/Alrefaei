"""Construction material requirement for construction management."""

from collections import defaultdict
from odoo import Command
from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError

from .runtime import model_attribute


class ConstructionMaterialRequirement(models.Model):
    """Construction material requirement."""

    _name = 'construction.material.requirement'
    _description = 'Project Material Requirement'
    _order = 'project_id, product_id'

    project_id = fields.Many2one(
        'construction.project', string='Project', required=True, ondelete='cascade', index=True
    )
    company_id = fields.Many2one(related='project_id.company_id', store=True, string='Company')
    product_id = fields.Many2one('product.product', string='Product', required=True, index=True)
    description = fields.Text(
        related='product_id.description_purchase', string='Technical Description'
    )
    uom_id = fields.Many2one('uom.uom', string='Unit', required=True)
    boq_quantity = fields.Float(
        compute='_compute_quantities', digits='Product Unit', string='BOQ Quantity'
    )
    transferred_quantity = fields.Float(
        compute='_compute_quantities', digits='Product Unit', string='Transferred Quantity'
    )
    purchased_quantity = fields.Float(
        compute='_compute_quantities', digits='Product Unit', string='Purchased Quantity'
    )
    received_quantity = fields.Float(
        compute='_compute_quantities',
        digits='Product Unit',
        string='Received on Site',
        help="Quantity physically received in the project warehouse (net of returns).",
    )
    pending_quantity = fields.Float(
        compute='_compute_quantities', digits='Product Unit', string='Pending Requests'
    )
    remaining_quantity = fields.Float(
        compute='_compute_quantities', digits='Product Unit', string='Remaining Quantity'
    )
    available_quantity = fields.Float(
        compute='_compute_quantities',
        digits='Product Unit',
        string='Available to Request',
        help="Remaining quantity minus quantities of requests not yet processed.",
    )
    request_quantity = fields.Float(
        string='Quantity to Request',
        digits='Product Unit',
        help="Fill this column then use 'Request Materials' to create a material request.",
    )

    _project_product_uniq = models.Constraint(
        'unique(project_id, product_id, uom_id)',
        'This material already exists in the project requirements.',
    )

    @api.model
    def _get_supply_quantities(self, project, products, exclude_order=None):
        """Quantities committed for the project per product, in the product base unit.
        - boq: material quantity of the current BOQ (including approved change orders)
        - transferred: issued from other company warehouses to the project warehouse, net of returns
        - purchased: confirmed purchase orders of the project, plus RFQs created from material
          requests
        - received: quantity physically received in the project warehouse (done moves, net of
          returns)
        - pending: approved / to approve material requests not yet processed
        """
        result = {
            key: defaultdict(float)
            for key in ('boq', 'transferred', 'purchased', 'received', 'pending', 'returned')
        }
        if not project or not products:
            return result
        components = (
            self.env['construction.boq.component']
            .sudo()
            .search(
                [
                    ('project_id', '=', project.id),
                    ('component_type', '=', 'material'),
                    ('product_id', 'in', products.ids),
                ]
            )
        )
        for component in components:
            result['boq'][component.product_id.id] += self._convert(
                component.effective_quantity,
                component.uom_id or component.product_id.uom_id,
                component.product_id,
            )

        warehouse = project.warehouse_id
        if warehouse:
            move_model = self.env['stock.move'].sudo()
            incoming = move_model.search(
                [
                    ('product_id', 'in', products.ids),
                    ('state', '!=', 'cancel'),
                    ('location_dest_id.warehouse_id', '=', warehouse.id),
                    ('location_id.usage', 'in', ('internal', 'supplier', 'transit')),
                ]
            ).filtered(lambda m: m.location_id.warehouse_id != warehouse)
            outgoing = move_model.search(
                [
                    ('product_id', 'in', products.ids),
                    ('state', '!=', 'cancel'),
                    ('location_id.warehouse_id', '=', warehouse.id),
                    ('location_dest_id.usage', 'in', ('internal', 'supplier', 'transit')),
                ]
            ).filtered(lambda m: m.location_dest_id.warehouse_id != warehouse)
            for move in incoming:
                qty = self._convert(move.product_uom_qty, move.product_uom, move.product_id)
                if move.location_id.usage in ('internal', 'transit'):
                    result['transferred'][move.product_id.id] += qty
                if move.state == 'done':
                    result['received'][move.product_id.id] += self._convert(
                        move.quantity, move.product_uom, move.product_id
                    )
            for move in outgoing:
                qty = self._convert(move.product_uom_qty, move.product_uom, move.product_id)
                if (
                    move.location_dest_id.usage in ('internal', 'transit')
                    and not move.purchase_line_id
                    and not move.origin_returned_move_id.purchase_line_id
                ):

                    result['transferred'][move.product_id.id] -= qty
                if move.state == 'done':
                    done_qty = self._convert(move.quantity, move.product_uom, move.product_id)
                    result['received'][move.product_id.id] -= done_qty
                    if move.location_dest_id.usage == 'supplier' and (
                        move.purchase_line_id or move.origin_returned_move_id.purchase_line_id
                    ):

                        result['returned'][move.product_id.id] += done_qty

        domain = [
            ('order_id.construction_project_id', '=', project.id),
            ('product_id', 'in', products.ids),
            ('display_type', '=', False),
            '|',
            ('order_id.state', 'in', ('purchase', 'done')),
            '&',
            ('order_id.construction_material_request_id', '!=', False),
            ('order_id.state', '!=', 'cancel'),
        ]
        if exclude_order:
            domain.append(('order_id', 'not in', exclude_order.ids))
        for po_line in self.env['purchase.order.line'].sudo().search(domain):
            result['purchased'][po_line.product_id.id] += self._convert(
                po_line.product_qty, po_line.product_uom_id, po_line.product_id
            )
        for product_id, returned in result['returned'].items():
            result['purchased'][product_id] -= returned

        request_lines = (
            self.env['construction.material.request.line']
            .sudo()
            .search(
                [
                    ('request_id.project_id', '=', project.id),
                    ('request_id.state', 'in', ('to_approve', 'approved')),
                    ('product_id', 'in', products.ids),
                ]
            )
        )
        for request_line in request_lines:
            result['pending'][request_line.product_id.id] += self._convert(
                request_line.quantity, request_line.uom_id, request_line.product_id
            )
        return result

    def _compute_quantities(self):
        for project in self.project_id:
            requirements = self.filtered(lambda req, site=project: req.project_id == site)
            data = self._get_supply_quantities(project, requirements.product_id)
            for requirement in requirements:
                pid = requirement.product_id.id
                to_uom = requirement.uom_id
                base_uom = requirement.product_id.uom_id

                def conv(qty, base_uom=base_uom, to_uom=to_uom):
                    """Convert a quantity into the requirement unit."""
                    return model_attribute(base_uom, '_compute_quantity')(
                        qty, to_uom, round=False, raise_if_failure=False
                    )

                requirement.boq_quantity = conv(data['boq'][pid])
                requirement.transferred_quantity = conv(data['transferred'][pid])
                requirement.purchased_quantity = conv(data['purchased'][pid])
                requirement.received_quantity = conv(data['received'][pid])
                requirement.pending_quantity = conv(data['pending'][pid])
                requirement.remaining_quantity = (
                    requirement.boq_quantity
                    - requirement.transferred_quantity
                    - requirement.purchased_quantity
                )
                requirement.available_quantity = (
                    requirement.remaining_quantity - requirement.pending_quantity
                )
        for requirement in self.filtered(lambda r: not r.project_id):
            requirement.boq_quantity = requirement.transferred_quantity = (
                requirement.purchased_quantity
            ) = 0.0
            requirement.received_quantity = requirement.pending_quantity = 0.0
            requirement.remaining_quantity = requirement.available_quantity = 0.0

    @api.model
    def _convert(self, quantity, from_uom, product):
        """Convert a quantity to the product base unit."""
        if not quantity:
            return 0.0
        if not from_uom or from_uom == product.uom_id:
            return quantity
        return model_attribute(from_uom, '_compute_quantity')(
            quantity, product.uom_id, round=False, raise_if_failure=False
        )

    def action_create_material_request(self):
        """Create material request."""
        requirements = self.filtered(lambda r: r.request_quantity > 0)
        if not requirements:
            raise UserError(
                _('Please fill the "Quantity to Request" column for the materials you need.')
            )
        if len(requirements.project_id) > 1:
            raise UserError(_('Please select materials of a single project.'))
        project = requirements.project_id
        if project.state not in ('running', 'suspended'):
            raise UserError(_('Material requests can only be created for running projects.'))
        request = self.env['construction.material.request'].create(
            {
                'project_id': project.id,
                'line_ids': [
                    Command.create(
                        {
                            'requirement_id': requirement.id,
                            'quantity': requirement.request_quantity,
                        }
                    )
                    for requirement in requirements
                ],
            }
        )
        requirements.write({'request_quantity': 0.0})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Material Request'),
            'res_model': 'construction.material.request',
            'res_id': request.id,
            'view_mode': 'form',
        }
