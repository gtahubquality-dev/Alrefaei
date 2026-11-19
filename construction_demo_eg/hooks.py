"""Egyptian construction demo hooks workflows."""

import random
from odoo import fields
from . import company, equipment, fleet, partners, projects
from .demo_data import PROJECTS
from .demo_logging import LOGGER
from .state import (
    ContextState,
    AccountingState,
    PartnersState,
    EquipmentState,
    FleetState,
    ProjectSpec,
)


def post_init_hook(env):
    """Install the demo company. On a database that already has data (projects or
    accounting), the company, its chart of accounts, its currency and its settings are
    kept: the demo only adds its own records next to them and completes the settings
    that are still empty."""
    existing = bool(env['construction.project'].search_count([]))
    if existing:
        LOGGER.warning(
            (
                'Construction demo (Egypt): the database already has projects: the demo '
                'data is added next to them, the existing data and settings are kept.'
            )
        )
    DemoBuilder(env, keep_existing=existing).build()


class DemoBuilder:
    """Coordinate reproducible Egyptian construction demo workflows."""

    def __init__(self, env, keep_existing=False):
        self.context = ContextState()
        self.accounting = AccountingState()
        self.partners = PartnersState()
        self.equipment = EquipmentState()
        self.fleet = FleetState()
        self.context.rng = random.Random(2026)
        self.context.today = fields.Date.context_today(env['res.partner'])
        self.context.admin = env.ref('base.user_admin')
        self.context.root_env = env
        self.context.env = env(
            user=self.context.admin,
            context=dict(
                env.context,
                tracking_disable=True,
                mail_create_nolog=True,
                mail_notrack=True,
                mail_auto_subscribe_no_notify=True,
                lang='ar_001',
            ),
        )
        self.context.company = self.context.env.company
        self.context.keep = keep_existing or env.company.sudo()._existing_accounting()
        self.equipment.machines_free = []
        self.equipment.machine_available = {}
        self.demo_projects = env['construction.project']

    def setup(self):
        """Prepare company settings, reference records, equipment, and fleet."""
        LOGGER.info('Construction demo (Egypt): company and settings')
        company.setup_company(self)
        partners.setup_partners_products(self)
        partners.setup_users(self)
        equipment.setup_equipment(self)
        fleet.setup_fleet(self)
        projects.tenders_lost(self)

    def build(self):
        """Populate the demo through the existing business workflows."""
        self.setup()
        order = sorted(
            range(len(PROJECTS)), key=lambda i: (PROJECTS[i][3] == 'draft', -PROJECTS[i][4])
        )
        for count, index in enumerate(order, start=1):
            spec = PROJECTS[index]
            LOGGER.info(
                'Construction demo (Egypt): project %s/%s %s', count, len(PROJECTS), spec[0]
            )
            self.demo_projects |= projects.build_project(self, index, ProjectSpec(*spec))
        fleet.fleet_operations(self)
        LOGGER.info('Construction demo (Egypt): done')
