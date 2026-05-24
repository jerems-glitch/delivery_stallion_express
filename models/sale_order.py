from odoo import models
import logging

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _get_delivery_methods(self):
        carriers = super()._get_delivery_methods()
        result = self.env['delivery.carrier']

        for carrier in carriers:
            if carrier.delivery_type == 'stallion_express':
                rate = carrier.rate_shipment(self)
                if rate.get('success'):
                    result |= carrier
                else:
                    # Debug log so we can see why a method is hidden
                    _logger.warning(
                        f"Stallion method hidden: {carrier.name} | "
                        f"Reason: {rate.get('error_message', 'Unknown error')}"
                    )
            else:
                result |= carrier

        return result