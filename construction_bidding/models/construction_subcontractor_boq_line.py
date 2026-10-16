"""Track planned and distributed subcontractor quantities."""

from odoo import api, fields, models


class ConstructionSubcontractorBOQLine(models.Model):
    """Subcontractor BOQ Line."""

    _name = "construction.subcontractor.boq.line"
    _description = "Subcontractor BOQ Line"
    _rec_name = "description"

    subcontractor_boq_id = fields.Many2one(
        "construction.subcontractor.boq", required=True, ondelete="cascade",
    )
    boq_line_id = fields.Many2one("construction.boq.line", ondelete="set null")
    product_id = fields.Many2one("product.product", domain=[("type", "=", "service")])
    finished_product_id = fields.Many2one(
        "product.product", domain=[("type", "=", "service")],
    )
    description = fields.Text()
    quantity = fields.Float(string="Planned Quantity")
    uom_id = fields.Many2one("uom.uom", string="UoM")
    unit_cost = fields.Float(string="Unit Price")
    contract_line_ids = fields.One2many(
        "construction.subcontractor.contract.line", "source_line_id",
    )
    distributed_quantity = fields.Float(compute="_compute_quantities")
    available_quantity = fields.Float(compute="_compute_quantities")

    @api.depends("quantity", "contract_line_ids.quantity")
    def _compute_quantities(self):
        for line in self:
            line.distributed_quantity = sum(line.contract_line_ids.mapped("quantity"))
            line.available_quantity = line.quantity - line.distributed_quantity
