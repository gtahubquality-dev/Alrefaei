"""Construction equipment assets construction equipment support."""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


def _asset_value(asset, *names):
    """First existing field value of the asset (field names differ between versions of
    the Assets app)."""
    for name in names:
        if name in asset._fields:
            return asset[name]
    return False


class ConstructionEquipment(models.Model):
    """Construction Equipment."""

    _inherit = 'construction.equipment'
    asset_id = fields.Many2one(
        'account.asset',
        string='Fixed Asset',
        tracking=True,
        copy=False,
        index=True,
        ondelete='restrict',
        domain="[('company_id', '=', company_id), ('state', '!=', 'model')]",
        help=(
            'Fixed asset of the company owned equipment in Accounting. '
            'Rented equipment has no asset.'
        ),
    )
    asset_book_value = fields.Monetary(compute='_compute_asset_values', string='Book Value')
    asset_original_value = fields.Monetary(compute='_compute_asset_values', string='Asset Value')
    _asset_uniq = models.Constraint(
        'UNIQUE(asset_id)', 'This fixed asset is already linked to another equipment.'
    )

    @api.depends('asset_id')
    def _compute_asset_values(self):
        for equipment in self:
            asset = equipment.asset_id.sudo()
            equipment.asset_original_value = (
                _asset_value(asset, 'original_value') or 0.0 if asset else 0.0
            )
            equipment.asset_book_value = (
                _asset_value(asset, 'book_value', 'value_residual') or 0.0 if asset else 0.0
            )

    @api.onchange('asset_id')
    def _onchange_asset_id(self):
        for equipment in self.filtered('asset_id'):
            equipment.ownership = 'owned'
            equipment.fill_from_asset()

    def _fill_from_asset(self):
        for equipment in self:
            asset = equipment.asset_id.sudo()
            value = _asset_value(asset, 'original_value')
            date = _asset_value(asset, 'acquisition_date')
            if value:
                equipment.purchase_value = value
            if date:
                equipment.acquisition_date = date

    @api.model_create_multi
    def create(self, vals_list):
        """Create records using the existing defaults and sequence values."""
        for vals in vals_list:
            if vals.get('asset_id'):
                vals['ownership'] = 'owned'
        equipment = super().create(vals_list)
        for record in equipment.filtered('asset_id'):
            record.sync_from_asset()
        return equipment

    def write(self, vals):
        """Update records while preserving the existing workflow checks."""
        if vals.get('asset_id'):
            vals = dict(vals, ownership='owned')
        res = super().write(vals)
        if vals.get('asset_id') and (not self.env.context.get('construction_asset_sync')):
            self._sync_from_asset()
        return res

    def _sync_from_asset(self):
        for equipment in self:
            asset = equipment.asset_id.sudo()
            vals = {}
            value = _asset_value(asset, 'original_value')
            date = _asset_value(asset, 'acquisition_date')
            if value and value != equipment.purchase_value:
                vals['purchase_value'] = value
            if date and date != equipment.acquisition_date:
                vals['acquisition_date'] = date
            if vals:
                equipment.with_context(construction_asset_sync=True).write(vals)

    @api.constrains('ownership', 'asset_id', 'active')
    def _check_asset(self):
        for equipment in self:
            if equipment.ownership == 'rented' and equipment.asset_id:
                raise ValidationError(
                    _('%s is linked to a fixed asset: it cannot be rented.', equipment.display_name)
                )
            if equipment.ownership == 'owned' and equipment.active and (not equipment.asset_id):
                raise ValidationError(
                    _(
                        (
                            'Company owned equipment must be linked to its fixed asset '
                            '(%s). Rented equipment is registered with a rental contract.'
                        ),
                        equipment.display_name,
                    )
                )
            if equipment.asset_id and equipment.asset_id.company_id != equipment.company_id:
                raise ValidationError(
                    _('The fixed asset of %s belongs to another company.', equipment.display_name)
                )

    def action_open_asset(self):
        """Action open asset."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Fixed Asset'),
            'res_model': 'account.asset',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'res_id': self.asset_id.id,
        }

    @api.private
    def fill_from_asset(self):
        """Apply asset values through the existing internal onchange hook."""
        return self._fill_from_asset()

    @api.private
    def sync_from_asset(self):
        """Synchronize equipment through the existing internal asset hook."""
        return self._sync_from_asset()
