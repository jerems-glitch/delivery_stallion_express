{
    'name': 'Stallion Express Delivery',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Delivery',
    'summary': 'Integrate Stallion Express shipping with rate selection at checkout',
    'description': """
        Integrate Stallion Express for real-time shipping rates.
        Customers can select preferred shipping methods during checkout.
    """,
    'depends': ['delivery', 'sale', 'website_sale'],
    'author': 'Jeremy McLellan',
    'license': 'LGPL-3',
    'application': False,
    'installable': True,
    'auto_install': False,
    'data': [
        'data/stallion_data.xml',
        'views/delivery_stallion_views.xml',
        'views/delivery_checkout_views.xml',
    ],
}