"""Egyptian construction demo partners workflows."""

from operator import methodcaller
from odoo import Command
from .demo_data import BANKS, CONSULTANTS, OWNERS, PRODUCTS, SUBCONTRACTORS, VENDORS


def setup_users(builder):
    """Site engineers (without password: they cannot log in until the administrator sets one)."""
    group = builder.context.root_env.ref('construction_management.group_construction_user')
    users_model = (
        builder.context.env['res.users']
        .sudo()
        .with_context(no_reset_password=True, active_test=False)
    )
    builder.partners.engineers = users_model
    for name, login in (
        ('م. أحمد سامي', 'eng.ahmed'),
        ('م. محمد عادل', 'eng.mohamed'),
        ('م. عمرو حسين', 'eng.amr'),
        ('م. هشام نبيل', 'eng.hesham'),
    ):
        user = users_model.search([('login', '=', login)], limit=1) or users_model.create(
            {
                'name': name,
                'login': login,
                'lang': builder.context.admin.lang,
                'group_ids': [Command.link(group.id)],
                'company_id': builder.context.company.id,
                'company_ids': [Command.link(builder.context.company.id)],
            }
        )
        builder.partners.engineers |= user


def partner(builder, name, **vals):
    """Create a demo partner without allowing duplicate default keyword arguments."""
    country_id = builder.context.root_env.ref('base.eg').id
    if 'is_company' in vals or 'country_id' in vals:
        raise TypeError('Partner defaults were supplied more than once.')
    return builder.context.env['res.partner'].create(
        {'name': name, 'is_company': True, 'country_id': country_id, **vals}
    )


def setup_partners_products(builder):
    """Setup partners products."""
    builder.partners.owners = [partner(builder, name, customer_rank=1) for name in OWNERS]
    builder.partners.consultants = [partner(builder, name) for name in CONSULTANTS]
    builder.partners.vendors = {
        key: partner(builder, name, supplier_rank=1) for (key, name) in VENDORS.items()
    }
    builder.partners.subcontractors = {
        key: partner(builder, name, supplier_rank=1) for (key, name) in SUBCONTRACTORS.items()
    }
    builder.partners.banks = [
        builder.context.env['res.bank'].create({'name': name}) for name in BANKS
    ]
    product_model = builder.context.env['product.product']
    builder.equipment.products = {}
    for key, (name, uom_xmlid, cost, vendor_key) in PRODUCTS.items():
        uom = builder.context.root_env.ref(uom_xmlid)
        product = product_model.create(
            {
                'name': name,
                'type': 'consu',
                'is_storable': True,
                'uom_id': uom.id,
                'standard_price': cost,
                'purchase_ok': True,
                'sale_ok': False,
                'seller_ids': [
                    Command.create(
                        {'partner_id': builder.partners.vendors[vendor_key].id, 'price': cost}
                    )
                ],
            }
        )
        builder.equipment.products[key] = product
    builder.equipment.rental_service = product_model.create(
        {
            'name': 'إيجار معدات (بالساعة)',
            'type': 'service',
            'purchase_ok': True,
            'sale_ok': False,
            'purchase_method': 'purchase',
            'uom_id': builder.context.root_env.ref('uom.product_uom_hour').id,
        }
    )
    quant_model = builder.context.env['stock.quant'].sudo()
    for key, product in builder.equipment.products.items():
        methodcaller(
            '_update_available_quantity', product, builder.accounting.main_wh.lot_stock_id, 100000
        )(quant_model)
