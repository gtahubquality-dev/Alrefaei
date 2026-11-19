"""Egyptian construction demo utils workflows."""

from datetime import timedelta
from odoo import Command, fields


def free(builder, model, field, value):
    """Unique value (equipment code, license number) next to the data already in the database."""
    model_model = builder.context.env[model].sudo().with_context(active_test=False)
    candidate, number = (value, 1)
    while model_model.search_count(
        [(field, '=', candidate), ('company_id', '=', builder.context.company.id)]
    ):
        number += 1
        candidate = f'{value!s}-D{number!s}'
    return candidate


def ensure_account(builder, code: str, name: str, account_type: str):
    """Account."""
    account_model = builder.context.env['account.account'].sudo()
    domain = [('company_ids', 'in', builder.context.company.id)]
    account = account_model.search(domain + [('code', '=', code)], limit=1)
    if account and (account.account_type == account_type or not builder.context.keep):
        return account
    if builder.context.keep:
        account = account_model.search(
            domain + [('name', '=', name), ('account_type', '=', account_type)], limit=1
        )
        if account:
            return account
        base = code
        for extra in ('9', '99', '999', '9999'):
            if not account_model.search_count(domain + [('code', '=', code)]):
                break
            code = base + extra
    return account_model.create(
        {
            'code': code,
            'name': name,
            'account_type': account_type,
            'company_ids': [Command.link(builder.context.company.id)],
        }
    )


def target(project, start, end, full=False):
    """Share of the works executed at the end of the period."""
    months = max((end.year - start.year) * 12 + end.month - start.month, 1)
    return 1.0 if full else min(0.15 + months / (project.duration_months * 1.2), 0.85)


def at(date, hour=9):
    """At."""
    return fields.Datetime.to_datetime(date) + timedelta(hours=hour)


def kind(name: str) -> str:
    """Kind of machine named in a BOQ line or a machine name (first word, e.g. لودر / مضخة
    / ونش برجي)."""
    for machine_kind in (
        'ونش برجي',
        'ونش متحرك',
        'لودر',
        'مضخة',
        'حفار',
        'جريدر',
        'هراس',
        'خلاطة',
        'مولد',
    ):
        if machine_kind in name or (
            machine_kind == 'ونش متحرك' and 'ونش' in name and ('برجي' not in name)
        ):
            return machine_kind
    return name.split()[0]
