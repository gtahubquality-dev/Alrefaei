"""Variation order models for construction bidding."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .boq_common import form_action


class VariationOrder(models.Model):
    """Variation order that changes a BOQ through traceable lines."""

    _name = "construction.variation.order"
    _description = "Variation Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "change_date desc, id desc"

    name = fields.Char(required=True, default=lambda self: _("New"), tracking=True)
    project_id = fields.Many2one("project.project", required=True, tracking=True)
    boq_id = fields.Many2one(
        "construction.boq",
        required=True,
        tracking=True,
        domain="[('project_id', '=', project_id)]",
    )
    change_date = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    changed_by_id = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
    line_ids = fields.One2many(
        "construction.variation.order.line",
        "variation_order_id",
        string="Lines",
        copy=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("applied", "Applied")],
        default="draft",
        required=True,
        tracking=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Assign the VO sequence."""
        sequence = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = sequence.next_by_code("construction.variation.order") or _("New")
        return super().create(vals_list)

    @api.onchange("boq_id")
    def _onchange_boq_id(self):
        for order in self:
            if order.boq_id:
                order.project_id = order.boq_id.project_id

    def action_apply(self):
        """Apply VO lines to the linked BOQ."""
        for order in self:
            if order.state == "applied":
                continue
            if not order.line_ids:
                raise UserError(_("Please add at least one variation order line."))
            for line in order.line_ids:
                line.apply_to_boq()
            order.write({
                "state": "applied",
                "change_date": fields.Datetime.now(),
                "changed_by_id": self.env.user.id,
            })
        return True

    def action_view_boq(self):
        """Open the BOQ linked to this VO."""
        self.ensure_one()
        return form_action("BOQ", "construction.boq", self.boq_id.id)
