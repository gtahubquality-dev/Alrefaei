"""Construction Management 19.0.1.6.0: company owned equipment is linked to its fixed asset.

When the Assets application of Accounting (account_asset) is installed, the bridge module
construction_equipment_asset is installed in the same upgrade (it is auto-installed on new databases).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("SELECT name, state FROM ir_module_module WHERE name IN ('account_asset', 'construction_equipment_asset')")
    states = dict(cr.fetchall())
    if states.get('account_asset') == 'installed' and states.get('construction_equipment_asset') == 'uninstalled':
        cr.execute("UPDATE ir_module_module SET state = 'to install' WHERE name = 'construction_equipment_asset'")
        _logger.info("Construction Management: construction_equipment_asset will be installed (Assets app found)")
