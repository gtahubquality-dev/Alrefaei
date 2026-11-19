"""Purchase order for construction management."""

from collections import defaultdict
from odoo import _
from odoo import api
from odoo import fields
from odoo import models
from odoo.exceptions import UserError
from odoo.tools import float_compare

from .runtime import model_attribute

from .construction_common import construction_project_field


class PurchaseOrder(models.Model):
    """Purchase order."""

    _inherit = 'purchase.order'

    construction_project_id = construction_project_field()
    construction_material_request_id = fields.Many2one(
        'construction.material.request', string='Material Request', readonly=True, copy=False
    )
    construction_equipment_request_id = fields.Many2one(
        'construction.equipment.request', string='Equipment Request', readonly=True, copy=False
    )
    construction_equipment_rental_id = fields.Many2one(
        'construction.equipment.rental',
        string='Rental Contract',
        readonly=True,
        copy=False,
        index=True,
    )

    @api.onchange('construction_project_id')
    def _onchange_construction_project_id(self):
        for order in self:
            project = order.construction_project_id
            if project and project.warehouse_id.in_type_id:
                order.picking_type_id = project.warehouse_id.in_type_id
            distribution = (
                model_attribute(project, '_get_analytic_distribution')() if project else False
            )
            if distribution:
                for line in order.order_line.filtered(lambda l: not l.display_type):
                    line.analytic_distribution = distribution

    def _prepare_picking(self):
        values = super()._prepare_picking()
        if self.construction_project_id:
            values['construction_project_id'] = self.construction_project_id.id
        return values

    def _prepare_invoice(self):
        values = super()._prepare_invoice()
        if self.construction_project_id:
            values['construction_project_id'] = self.construction_project_id.id
        return values

    def _check_construction_boq_limits(self):
        """Project purchase orders cannot exceed the BOQ, whatever the way they are created or
        modified:
        - orders created from a material request cannot order more (or other BOQ materials) than
          requested;
        - other project orders cannot exceed the BOQ quantity still available. Senior Management can
          bypass the check.
        """
        if self.env.su or self.env.user.has_group(
            'construction_management.group_construction_manager'
        ):
            return
        requirement_model = self.env['construction.material.requirement']
        for order in self.filtered(lambda o: o.construction_project_id and o.state != 'cancel'):
            project = order.construction_project_id.sudo()
            lines = order.order_line.filtered(lambda l: not l.display_type and l.product_id)
            ordered = defaultdict(float)
            for line in lines:
                ordered[line.product_id] += model_attribute(requirement_model, '_convert')(
                    line.product_qty, line.product_uom_id, line.product_id
                )
            boq_products = project.material_requirement_ids.product_id
            request = order.construction_material_request_id.sudo()
            requested = defaultdict(float)
            for request_line in request.line_ids:
                requested[request_line.product_id] += model_attribute(
                    requirement_model, '_convert'
                )(request_line.quantity, request_line.uom_id, request_line.product_id)
            direct_products = self.env['product.product']
            for product, qty in ordered.items():
                if product not in boq_products:
                    continue
                if request and product in requested:
                    if (
                        float_compare(
                            qty, requested[product], precision_rounding=product.uom_id.rounding
                        )
                        > 0
                    ):
                        raise UserError(
                            _(
                                'Purchase order %(order)s orders %(qty)s %(uom)s of %(product)s'
                                ' while material request %(request)s only requested %(requested)s.'
                                ' Create a new material request for the additional quantity or ask'
                                ' Senior Management.',
                                order=order.display_name,
                                qty=qty,
                                uom=product.uom_id.name,
                                product=product.display_name,
                                request=request.name,
                                requested=requested[product],
                            )
                        )
                else:
                    direct_products |= product
            if not direct_products:
                continue
            data = model_attribute(requirement_model, '_get_supply_quantities')(
                project, direct_products, exclude_order=order
            )
            for product in direct_products:
                pid = product.id
                committed = data['transferred'][pid] + data['purchased'][pid] + data['pending'][pid]
                if (
                    float_compare(
                        committed + ordered[product],
                        data['boq'][pid],
                        precision_rounding=product.uom_id.rounding,
                    )
                    > 0
                ):
                    available = max(data['boq'][pid] - committed, 0.0)
                    raise UserError(
                        _(
                            'Purchase order %(order)s exceeds the BOQ of project %(project)s for'
                            ' %(product)s: ordered %(qty)s, still available %(available)s %(uom)s.'
                            ' Use a material request (official approval) or ask Senior Management.',
                            order=order.display_name,
                            project=project.display_name,
                            product=product.display_name,
                            qty=ordered[product],
                            available=available,
                            uom=product.uom_id.name,
                        )
                    )

    def button_confirm(self):
        """Button confirm."""
        self._check_construction_boq_limits()
        return super().button_confirm()

    def write(self, vals):
        """Write."""
        res = super().write(vals)
        if 'construction_project_id' in vals:
            model_attribute(
                self.filtered(lambda o: o.state in ('purchase', 'done')),
                '_check_construction_boq_limits',
            )()
        return res

    def button_cancel(self):
        """Button cancel."""
        res = super().button_cancel()
        cancelled = self.filtered(lambda o: o.state == 'cancel').sudo()
        for order in cancelled:
            model_attribute(
                order.construction_material_request_id, '_reopen_after_document_cancel'
            )(_('Purchase order %s', order.name))
            model_attribute(order.construction_equipment_request_id, '_reopen_after_rental_cancel')(
                order
            )
            model_attribute(order.construction_equipment_rental_id, '_cancel_from_purchase')(order)
        return res
