"""Construction Management 19.0.1.7.0: customer contracts.

Existing projects get their draft customer contract (companies where the option is enabled, default yes).
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    projects = env['construction.project'].with_context(active_test=False).search([
        ('customer_contract_ids', '=', False),
        ('company_id.construction_auto_customer_contract', '=', True),
    ])
    for project in projects:
        project._create_customer_contract()
    if projects:
        _logger.info("Construction Management: %s customer contracts created for existing projects", len(projects))
