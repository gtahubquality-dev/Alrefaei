"""Construction bidding construction auto repair support."""

import logging
import threading
import time
from collections import defaultdict
from operator import attrgetter, methodcaller

import psycopg2

from odoo import SUPERUSER_ID, api, models, tools
from odoo.exceptions import UserError
from odoo.modules import module as odoo_module
from odoo.modules.registry import Registry
from odoo.tools.parse_version import parse_version

_logger = logging.getLogger(__name__)


CONSTRUCTION_MODULES = (
    'construction_bidding', 'construction_management', 'financial_custody',
        'construction_equipment',
    'construction_fleet', 'construction_equipment_asset',
)

AUTO_UPGRADE_LOCK_KEY = 741930011
AUTO_UPGRADE_PARAM = 'construction.auto_upgrade'
AUTO_UPGRADE_START_DELAY = 3
AUTO_UPGRADE_RETRY_DELAY = 30
AUTO_UPGRADE_MAX_ATTEMPTS = 10

MODEL_IS_ABSTRACT = attrgetter('_abstract')
MODEL_IS_AUTOMATIC = attrgetter('_auto')
MODEL_TABLE_QUERY = attrgetter('_table_query')
MODEL_TABLE = attrgetter('_table')
DEFINITION_MODULE = attrgetter('_module')
INITIALIZE_MODEL_TABLE = methodcaller('_auto_init')


_auto_upgrade_scheduled = set()
_auto_upgrade_guard = threading.Lock()


def _get_pending_modules(cr):
    """ Return the construction modules whose code on disk is newer than the database.

    A module is pending when it is left 'to install' / 'to upgrade' (interrupted
    upgrade), when its installed version is older than its manifest version, or
    when a required construction dependency is not installed yet.
    """
    cr.execute(
        "SELECT name, state, latest_version FROM ir_module_module WHERE name IN %s",
        [CONSTRUCTION_MODULES],
    )
    rows = {name: (state, version) for name, state, version in cr.fetchall()}
    pending = set()
    for name, (state, version) in rows.items():
        if state in ('to install', 'to upgrade'):
            pending.add(name)
        elif state == 'installed':
            try:
                manifest = odoo_module.get_manifest(name)
            except (OSError, ValueError, SyntaxError):
                _logger.warning("Construction auto-repair: cannot read the manifest of %s",
                    name, exc_info=True)
                continue
            if manifest and manifest.get('version') and (
                not version or parse_version(manifest['version']) > parse_version(version)
            ):
                pending.add(name)
    management_state = rows.get('construction_management', (None, None))[0]
    custody_state = rows.get('financial_custody', (None, None))[0]
    if (management_state in ('installed', 'to upgrade') and custody_state not in ('installed',
        'to upgrade', 'to install')):
        pending.add('construction_management')
    for split_module in ('construction_equipment', 'construction_fleet'):
        if rows.get(split_module, (None, None))[0] == 'uninstalled':

            cr.execute("SELECT 1 FROM ir_model_data WHERE module = %s LIMIT 1", [split_module])
            if cr.fetchone():
                pending.add(split_module)
    return pending


def _auto_upgrade_enabled(cr):
    """The automatic upgrade is opt-in: system parameter ``construction.auto_upgrade`` = (
        ``True``. By default
    )
    the modules are upgraded manually (Apps > Upgrade, or ``odoo-bin -u``), after a backup."""
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", [AUTO_UPGRADE_PARAM])
    row = cr.fetchone()
    return bool(row) and (row[0] or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _run_auto_upgrade(dbname):
    """ Finish an interrupted / missing upgrade of the construction modules.

    Runs in a background thread once the registry is loaded, exactly like the
    "Upgrade" button: modules are marked, the transaction is committed and the
    registry is reloaded with ``update_module=True``. HTTP requests on this
    database wait for the new registry while it is being loaded.
    """
    threading.current_thread().dbname = dbname
    time.sleep(AUTO_UPGRADE_START_DELAY)
    for attempt in range(1, AUTO_UPGRADE_MAX_ATTEMPTS + 1):
        try:
            registry = Registry(dbname)
            with registry.cursor() as lock_cr:
                lock_cr.execute("SELECT pg_try_advisory_xact_lock(%s)", [AUTO_UPGRADE_LOCK_KEY])
                if not lock_cr.fetchone()[0]:
                    _logger.info("Construction auto-upgrade: already running in another process")
                    return
                with registry.cursor() as cr:
                    pending = _get_pending_modules(cr)
                    if not pending or not _auto_upgrade_enabled(cr):
                        return
                    cr.execute(
                        "SELECT name FROM ir_module_module WHERE state IN ('to install', "
                            "'to upgrade', 'to remove')"
                        " AND name NOT IN %s",
                        [CONSTRUCTION_MODULES],
                    )
                    others = [row[0] for row in cr.fetchall()]
                    if others:

                        _logger.warning(
                            'Construction auto-upgrade: cancelled, other module operations '
                                'are pending (%s). '
                            "Upgrade the modules manually.", ', '.join(sorted(others)))
                        return
                    try:
                        cr.execute("LOCK ir_module_module IN EXCLUSIVE MODE NOWAIT")
                        cr.execute("SELECT FROM ir_cron FOR UPDATE NOWAIT")
                    except psycopg2.OperationalError:
                        cr.rollback()
                        _logger.info(
                            'Construction auto-upgrade: a module operation or scheduled '
                                'action is running, '
                            "retry %s/%s in %ss", attempt, AUTO_UPGRADE_MAX_ATTEMPTS,
                                AUTO_UPGRADE_RETRY_DELAY)
                        lock_cr.rollback()
                        time.sleep(AUTO_UPGRADE_RETRY_DELAY)
                        continue
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    module_model = env['ir.module.module']
                    module_model.update_list()
                    to_upgrade = module_model.search([
                        ('name', 'in', sorted(pending)),
                        ('state', 'in', ('installed', 'to upgrade')),
                    ])
                    to_upgrade.button_upgrade()
                    module_model.search([('name', 'in', sorted(pending)), ('state', '=',
                        'uninstalled')]).button_install()
                    _logger.info(
                        'Construction auto-upgrade: database schema/data older than the '
                            'code, upgrading %s',
                        ', '.join(sorted(pending)))

                    cr.commit()
                Registry.new(dbname, update_module=True)
                _logger.info("Construction auto-upgrade: modules upgraded successfully")
            return
        except (psycopg2.Error, OSError, ValueError, SyntaxError, ImportError, UserError):
            _logger.exception(
                "Construction auto-upgrade failed. Upgrade the modules %s manually "
                "(Apps > Upgrade, or odoo-bin -u %s).",
                ', '.join(CONSTRUCTION_MODULES), ','.join(CONSTRUCTION_MODULES))
            return


class ConstructionAutoRepair(models.AbstractModel):
    """ Self-healing of the construction suite after an interrupted upgrade.

    When new code is deployed but the database was not (completely) upgraded,
    stored fields of these modules have no column yet and every request that
    reads them (e.g. the company at login) fails with "Internal Server Error".
    At registry load:

    Opt-in (system parameter ``construction.auto_upgrade`` = ``True``):

    1. missing tables / columns of the suite's stored fields are created
       immediately, so the server answers again;
    2. if the modules are older in the database than on disk and the system
       parameter ``construction.auto_upgrade`` is ``True`` (opt-in, off by
       default), the upgrade is finished in the background; otherwise a warning
       asks for the manual upgrade.
    """
    _name = 'construction.auto.repair'
    _description = 'Construction Suite Auto Repair'

    def _register_hook(self):
        super()._register_hook()
        if not _auto_upgrade_enabled(self.env.cr):


            try:
                self._construction_schedule_auto_upgrade()
            except (psycopg2.Error, OSError, ValueError, SyntaxError, RuntimeError):
                _logger.exception("Construction auto-repair: cannot check the module versions")
            return
        try:
            with self.env.cr.savepoint():
                self._construction_repair_schema()
        except (psycopg2.Error, UserError, ValueError):
            _logger.exception("Construction auto-repair: schema repair failed")
        try:
            self._construction_schedule_auto_upgrade()
        except (psycopg2.Error, OSError, ValueError, SyntaxError, RuntimeError):
            _logger.exception("Construction auto-repair: cannot schedule the automatic upgrade")

    def _construction_missing_schema(self):
        """ Return {module: set(model names)} of models whose table, column or
        many2many table required by a construction field is missing. """
        cr = self.env.cr
        cr.execute("""
            SELECT table_name, column_name FROM information_schema.columns
             WHERE table_schema = current_schema()
        """)
        columns = defaultdict(set)
        for table, column in cr.fetchall():
            columns[table].add(column)
        missing = defaultdict(set)
        registry = self.env.registry
        for model_name in list(registry):
            model_cls = registry[model_name]

            if (MODEL_IS_ABSTRACT(model_cls) or model_cls.is_transient()
                or not MODEL_IS_AUTOMATIC(model_cls) or MODEL_TABLE_QUERY(model_cls)):
                continue
            table = MODEL_TABLE(model_cls)
            if DEFINITION_MODULE(model_cls) in CONSTRUCTION_MODULES and table not in columns:
                missing[DEFINITION_MODULE(model_cls)].add(model_name)
                continue
            for field in model_cls._fields.values():
                if (DEFINITION_MODULE(field) not in CONSTRUCTION_MODULES
                    or not field.store or field.manual):
                    continue
                if field.type == 'many2many':
                    if (field.relation and field.relation not in columns
                        and not MODEL_TABLE_QUERY(registry[field.comodel_name])):
                        missing[DEFINITION_MODULE(field)].add(model_name)
                elif field.column_type and field.name not in columns.get(table, ()):
                    missing[DEFINITION_MODULE(field)].add(model_name)
        return missing

    def _construction_repair_schema(self):
        missing = self._construction_missing_schema()
        if not missing:
            return
        registry = self.env.registry
        for module in CONSTRUCTION_MODULES:
            model_names = sorted(missing.get(module, ()))
            if not model_names:
                continue
            _logger.warning(
                'Construction auto-repair: database tables/columns missing for %s '
                    '(module %s), creating them',
                ', '.join(model_names), module)
            try:
                with self.env.cr.savepoint():
                    registry.init_models(self.env.cr, model_names, {'module': module},
                        install=False)
            except (psycopg2.Error, UserError, ValueError):
                _logger.info('Construction auto-repair: full initialization not possible yet, '
                    'creating the '
                             "missing columns only (the upgrade completes the rest)", exc_info=True)
                for model_name in model_names:
                    with self.env.cr.savepoint():
                        INITIALIZE_MODEL_TABLE(self.env[model_name].sudo())

    def _construction_schedule_auto_upgrade(self):
        config = tools.config
        if (
            odoo_module.current_test
            or config.get('test_enable')
            or config.get('stop_after_init')
            or config.get('init')
            or config.get('update')
        ):
            return
        cr = self.env.cr
        dbname = cr.dbname
        with _auto_upgrade_guard:
            if dbname in _auto_upgrade_scheduled:
                return
            pending = _get_pending_modules(cr)
            if not pending:
                return
            if not _auto_upgrade_enabled(cr):
                _auto_upgrade_scheduled.add(dbname)
                _logger.warning(
                    'Construction: the modules %s are older in database %s than their '
                        'code. Upgrade them '
                    "(Apps > Upgrade, or odoo-bin -u %s) after a backup.",
                    ', '.join(sorted(pending)), dbname, ','.join(sorted(pending)))
                return
            _auto_upgrade_scheduled.add(dbname)
        _logger.warning(
            "Construction auto-repair: modules are not up to date in database %s, "
            "the upgrade will be completed automatically", dbname)
        thread = threading.Thread(
            target=_run_auto_upgrade, args=(dbname,), name='construction-auto-upgrade', daemon=True)
        thread.start()
