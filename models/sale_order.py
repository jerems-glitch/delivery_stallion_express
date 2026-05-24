from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _get_delivery_methods(self):
        """Hide Stallion carriers that have no available rate"""
        carriers = super()._get_delivery_methods()
        result = self.env['delivery.carrier']

        for carrier in carriers:
            if carrier.delivery_type == 'stallion_express':
                rate = carrier.rate_shipment(self)
                if rate.get('success'):
                    result |= carrier
            else:
                result |= carrier

        return result