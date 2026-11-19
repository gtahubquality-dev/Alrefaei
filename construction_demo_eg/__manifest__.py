{
    'name': 'Construction Demo Data - Egypt',
    'version': '19.0.1.3.0',
    'category': 'Construction',
    'summary': (
        'Demo data of an Egyptian contracting company: 18 projects with '
        'purchases, equipment, subcontractors, deductions, vehicles and '
        'accounting'
    ),
    'author': 'Construction ERP',
    'license': 'LGPL-3',
    'depends': [
        'l10n_eg',
        'construction_bidding',
        'construction_management',
        'financial_custody',
        'construction_equipment',
        'construction_fleet',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
