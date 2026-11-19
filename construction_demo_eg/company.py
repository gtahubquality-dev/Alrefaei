"""Egyptian construction demo company workflows."""

from functools import partial
from operator import methodcaller
from odoo import Command
from . import utils
from .demo_data import COMPANY_NAME


def setup_company(builder):
    """Setup company."""
    root = builder.context.root_env
    company = builder.context.company.sudo()
    egypt = root.ref('base.eg')
    egp = root.ref('base.EGP')
    if not egp.active:
        egp.active = True
    if not builder.context.keep and company.chart_template != 'eg':
        company.write({'country_id': egypt.id})
        root['account.chart.template'].try_loading('eg', company, install_demo=False)
    setup_language(builder)
    if not builder.context.keep:
        if company.name in ('YourCompany', 'My Company', 'Your Company') or not company.name:
            company.name = COMPANY_NAME
        company.write(
            {
                'country_id': egypt.id,
                'city': 'القاهرة',
                'street': 'التجمع الخامس - شارع التسعين',
                'phone': '+20 2 2500 0000',
            }
        )
    builder.context.admin.sudo().write(
        {
            'group_ids': [
                Command.link(root.ref(xmlid).id)
                for xmlid in (
                    'construction_management.group_construction_executive',
                    'construction_management.group_construction_manager',
                    'construction_management.group_construction_finance',
                    'construction_management.group_construction_transport',
                    'financial_custody.group_custody_manager',
                    'stock.group_stock_manager',
                    'purchase.group_purchase_manager',
                    'account.group_account_manager',
                )
            ]
        }
    )
    builder.context.admin.sudo().company_ids = [Command.link(company.id)]
    journal_model = builder.context.env['account.journal'].sudo()
    builder.accounting.bank = journal_model.search(
        [('type', '=', 'bank'), ('company_id', '=', company.id)], limit=1
    ) or journal_model.create(
        {'name': 'البنك - جاري', 'code': 'BNKD', 'type': 'bank', 'company_id': company.id}
    )
    if not builder.context.keep:
        builder.accounting.bank.name = 'البنك الأهلي المصري - جاري'
    builder.accounting.cash = journal_model.search(
        [('type', '=', 'cash'), ('company_id', '=', company.id)], limit=1
    ) or journal_model.create(
        {'name': 'الخزينة الرئيسية', 'code': 'CSH1', 'type': 'cash', 'company_id': company.id}
    )
    misc = journal_model.search(
        [('type', '=', 'general'), ('company_id', '=', company.id)], limit=1
    )
    acc = partial(utils.ensure_account, builder)
    builder.accounting.accounts = {
        'revenue': acc('509001', 'إيرادات أعمال المقاولات', 'income'),
        'retention': acc('109101', 'ضمان أعمال لدى الملاك', 'asset_current'),
        'advance': acc('209101', 'دفعات مقدمة من الملاك', 'liability_current'),
        'insurance': acc('109102', 'تأمينات نهائية لدى الملاك', 'asset_current'),
        'sub_expense': acc('409105', 'أعمال مقاولي الباطن', 'expense_direct_cost'),
        'sub_retention': acc('209105', 'ضمان أعمال مقاولي الباطن', 'liability_current'),
        'sub_advance': acc('109105', 'دفعات مقدمة لمقاولي الباطن', 'asset_current'),
        'labor': acc('409104', 'أجور عمالة المشروعات', 'expense_direct_cost'),
        'accrued': acc('209104', 'أجور مستحقة', 'liability_current'),
        'equip_usage': acc('409101', 'تكلفة تشغيل المعدات', 'expense_direct_cost'),
        'equip_income': acc('509101', 'إيرادات تحميل المعدات', 'income_other'),
        'equip_cost': acc('409102', 'مصروفات صيانة ووقود المعدات', 'expense_direct_cost'),
        'transport': acc('409103', 'مصروفات نقل العربات', 'expense_direct_cost'),
        'custody': acc('109103', 'عهد الموظفين والسائقين', 'asset_current'),
        'wht_owner': acc('109104', 'ضرائب خصم من المنبع (مدينة)', 'asset_current'),
        'stamp': acc('409106', 'دمغة نقابة المهندسين', 'expense'),
        'social': acc('409107', 'تأمينات اجتماعية على المستخلصات', 'expense'),
        'suspense': acc('109106', 'تعليات لدى الملاك', 'asset_current'),
        'wht_sub': acc('209106', 'ضرائب خصم وإضافة مستحقة', 'liability_current'),
        'social_sub': acc('209107', 'تأمينات اجتماعية مستحقة', 'liability_current'),
    }
    tax_model = builder.context.env['account.tax'].sudo()
    sale_vat = tax_model.search(
        [('type_tax_use', '=', 'sale'), ('amount', '=', 14), ('company_id', '=', company.id)],
        limit=1,
    )
    purchase_vat = tax_model.search(
        [('type_tax_use', '=', 'purchase'), ('amount', '=', 14), ('company_id', '=', company.id)],
        limit=1,
    )
    sale_vat = sale_vat or company.account_sale_tax_id
    purchase_vat = purchase_vat or company.account_purchase_tax_id
    projects_wh = builder.context.env['construction.project'].search([]).warehouse_id
    main_wh = company.construction_equipment_warehouse_id or builder.context.env[
        'stock.warehouse'
    ].search([('company_id', '=', company.id), ('id', 'not in', projects_wh.ids)], limit=1)
    if not builder.context.keep:
        main_wh.sudo().write({'name': 'المخزن الرئيسي - العبور'})
    builder.accounting.main_wh = main_wh
    a = builder.accounting.accounts
    settings = {
        'construction_journal_id': misc.id,
        'construction_revenue_account_id': a['revenue'].id,
        'construction_retention_account_id': a['retention'].id,
        'construction_advance_account_id': a['advance'].id,
        'construction_insurance_account_id': a['insurance'].id,
        'construction_sub_expense_account_id': a['sub_expense'].id,
        'construction_sub_retention_account_id': a['sub_retention'].id,
        'construction_sub_advance_account_id': a['sub_advance'].id,
        'construction_labor_expense_account_id': a['labor'].id,
        'construction_labor_accrual_account_id': a['accrued'].id,
        'construction_equipment_expense_account_id': a['equip_usage'].id,
        'construction_equipment_income_account_id': a['equip_income'].id,
        'construction_equipment_cost_account_id': a['equip_cost'].id,
        'construction_equipment_warehouse_id': main_wh.id,
        'construction_transport_expense_account_id': a['transport'].id,
        'custody_account_id': a['custody'].id,
        'custody_journal_id': builder.accounting.cash.id,
        'custody_settlement_journal_id': misc.id,
        'construction_owner_tax_ids': [Command.set(sale_vat.ids)],
        'construction_sub_tax_ids': [Command.set(purchase_vat.ids)],
        'construction_customer_contract_terms': (
            '<p>يلتزم المقاول بتنفيذ الأعمال طبقاً للمواصفات والرسومات المعتمدة '
            'ومقايسة الأعمال، وتصرف المستخلصات شهرياً خلال 30 يوماً من اعتمادها من '
            'الاستشاري، مع خصم ضمان الأعمال والدفعة المقدمة والاستقطاعات '
            'القانونية.</p>'
        ),
    }
    settings = {name: value for (name, value) in settings.items() if name in company._fields}
    if builder.context.keep:
        settings = {name: value for (name, value) in settings.items() if not company[name]}
    company.write(settings)
    builder.accounting.misc = company.construction_journal_id or misc
    builder.accounting.cash = company.custody_journal_id or builder.accounting.cash


def setup_language(builder):
    """Activate Arabic and apply the existing administrator language settings."""
    root = builder.context.root_env
    lang = (
        root['res.lang'].with_context(active_test=False).search([('code', '=', 'ar_001')], limit=1)
    )
    if lang and (not lang.active):
        lang.active = True
        methodcaller('_update_translations', ['ar_001'])(
            root['ir.module.module'].search([('state', '=', 'installed')])
        )
    if lang:
        builder.context.admin.sudo().lang = 'ar_001'
