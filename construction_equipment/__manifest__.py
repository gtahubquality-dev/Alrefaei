{
    'name': 'Construction Machines & Equipment',
    'version': '19.0.1.7.1',
    'category': 'Services/Construction',
    'summary': (
        'Machines and equipment: movements, inventory '
        'transfers, usage costs, expenses and dashboard'
    ),
    'author': 'Mahmoud Gaber',
    'license': 'LGPL-3',
    'depends': ['construction_management', 'financial_custody', 'stock', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'security/ir_rules.xml',
        'data/ir_sequence.xml',
        'views/construction_equipment_views.xml',
        'views/construction_equipment_rental_views.xml',
        'views/construction_equipment_request_views.xml',
        'views/construction_equipment_movement_views.xml',
        'views/construction_equipment_usage_views.xml',
        'views/construction_equipment_expense_views.xml',
        'views/construction_equipment_dashboard_views.xml',
        'views/ir_actions_server_views.xml',
        'views/res_config_settings_views.xml',
        'views/ir_ui_menu.xml',
    ],
    'assets': {
        'web.assets_backend': ['construction_equipment/static/src/scss/equipment_dashboard.scss']
    },
    'post_init_hook': '_post_init_hook',
    'installable': True,
    'application': True,
}
