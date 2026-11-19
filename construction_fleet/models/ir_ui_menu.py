"""Construction fleet ir ui menu support."""

from odoo import api, models


class IrUiMenu(models.Model):
    """Ir Ui Menu."""

    _inherit = 'ir.ui.menu'

    @api.model
    def _visible_menu_ids(self, debug=False):
        """The rental contracts are managed in the Machines & Equipment app (machines) and
        its Fleet menu (vehicles), no longer in the Construction app."""
        visible = super()._visible_menu_ids(debug=debug)
        menu = self.env.ref(
            'construction_management.menu_construction_equipment_rentals', raise_if_not_found=False
        )
        if menu and menu.id in visible:
            visible = set(visible) - {menu.id}
        return visible
