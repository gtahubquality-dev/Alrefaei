{
    'name': 'Product Sales Weighted Discount',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Product sales discount based on recent purchase discounts',
    'author': 'Mahmoud Gaber',
    'license': 'LGPL-3',
    'depends': ['account', 'free_company_customization_control', 'purchase', 'sale_management'],
    'data': [
        'views/product_product_views.xml',
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'application': False,
}
