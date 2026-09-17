{
    "name": "Purchase Order Alternative Enhancement",
    "summary": "Enhance alternative purchase order comparison.",
    "version": "19.0.1.0.0",
    "category": "Purchase",
    "license": "LGPL-3",
    "depends": [
        "product_sales_weighted_discount",
        "purchase_requisition",
        "stock",
    ],
    "data": [
        "views/purchase_order_line_compare_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "purchase_order_alternative_enhancement/static/src/views/list/"
            "purchase_order_line_compare_list_renderer.js",
        ],
    },
    "installable": True,
}
