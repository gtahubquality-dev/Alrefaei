import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """The cost center, the Odoo project and the warehouse of a construction project are named after the project
    only (no more "CODE - Name"): rename the ones still carrying the automatic name, and drop the project code
    and the customer from its cost center (shown as "[code] name - customer")."""
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False})
    renamed = 0
    for project in env['construction.project'].search([]):
        if not project.code or not project.name:
            continue
        old_label = f'{project.code} - {project.name}'
        analytic = project.analytic_account_id
        if analytic:
            vals = {}
            if analytic.name == old_label:
                vals['name'] = project.name
            if analytic.code == project.code:
                vals['code'] = False
            if analytic.partner_id and analytic.partner_id == project.partner_id:
                vals['partner_id'] = False
            if vals:
                analytic.write(vals)
                renamed += 1
        if project.project_id and project.project_id.name == old_label:
            project.project_id.name = project.name
        warehouse = project.warehouse_id
        if warehouse and warehouse.name == old_label[:100]:
            warehouse.name = project._get_warehouse_name(warehouse)
    _logger.info('Construction Management: resources of %s projects renamed after the project name', renamed)
