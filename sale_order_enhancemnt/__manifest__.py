{
    "name": "Sale Order Enhancement",
    "summary": "Enhance sale order customer credit details.",
    "version": "19.0.1.0.0",
    "category": "Sales",
    "license": "LGPL-3",
    "depends": [
        "account",
        "free_company_customization_control",
        "sale",
        "sale_management",
        "sale_stock",
    ],
    "data": [
        "views/sale_order_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "sale_order_enhancemnt/static/src/js/inventory_location_onhand_buttons.js",
            "sale_order_enhancemnt/static/src/js/sale_order_line_enter_navigation.js",
            "sale_order_enhancemnt/static/src/xml/inventory_location_onhand_buttons.xml",
        ],
    },
    "installable": True,
}
