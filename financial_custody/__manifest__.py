{
    'name': 'Financial Custody',
    'version': '19.0.1.2.1',
    'category': 'Accounting/Accounting',
    'summary': (
        'Employee cash custody: request, approval, disbursement and settlement with invoices and'
        ' returns'
    ),
    'author': 'Mahmoud Gaber',
    'license': 'LGPL-3',
    'depends': ['hr', 'account', 'stock', 'mail'],
    'data': [
        'security/res_groups.xml',
        'security/ir_rules.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'views/custody_request_views.xml',
        'views/custody_settlement_views.xml',
        'views/res_config_settings_views.xml',
        'views/ir_ui_menu.xml',
    ],
    'installable': True,
    'application': True,
}
