{
    'name': 'Product Code Purchase Import',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Purchase',
    'summary': 'Import RFQ lines by a custom product code',
    'author': 'Mahmoud Gaber',
    'license': 'LGPL-3',
    'depends': ['free_company_customization_control', 'purchase'],
    'data': [
        'views/product_template_views.xml',
        'views/product_product_views.xml',
        'views/purchase_order_views.xml',
    ],
    'installable': True,
}
