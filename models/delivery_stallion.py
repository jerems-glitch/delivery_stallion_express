from odoo import models, fields, api
import requests
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(
        selection_add=[('stallion_express', 'Stallion Express')],
        ondelete={'stallion_express': 'set default'}
    )

    stallion_customer_number = fields.Char(string='Customer Number', required=True)
    stallion_api_key = fields.Char(string='API Token / Key', required=True)
    stallion_endpoint = fields.Selection([
        ('https://sandbox.stallionexpress.ca/api/v4', 'Sandbox'),
        ('https://ship.stallionexpress.ca/api/v4', 'Production')
    ], string='API Endpoint', default='https://sandbox.stallionexpress.ca/api/v4')

    stallion_default_service = fields.Char(string='Default Service Code')

    def stallion_express_rate_shipment(self, order):
        if not self.stallion_customer_number or not self.stallion_api_key:
            raise UserError("Please configure Stallion Express Customer Number and API Token.")

        shipper = order.warehouse_id.partner_id
        recipient = order.partner_shipping_id

        payload = {
            "origin_postal_code": shipper.zip or "",
            "destination_postal_code": recipient.zip or "",
            "destination_country": recipient.country_id.code or "CA",
            "packages": [{"weight": 1.0, "length": 10, "width": 10, "height": 10}],  # Improve later
        }

        headers = {
            'Content-Type': 'application/json',
            'X-Customer-Number': self.stallion_customer_number,
            'Authorization': self.stallion_api_key,  # Most common format
        }

        try:
            url = f"{self.stallion_endpoint}/rates"
            response = requests.post(url, headers=headers, json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()

            rates = []
            for service in data.get('services', data.get('rates', [])):
                rates.append({
                    'carrier': self.name,
                    'service_name': service.get('name') or service.get('service_name'),
                    'price': float(service.get('total', 0) or service.get('price', 0)),
                    'currency': 'CAD',
                    'service_code': service.get('code'),
                })
            return rates

        except Exception as e:
            _logger.error(f"Stallion API Error: {str(e)}")
            raise UserError(f"Stallion Express Error: {str(e)}")

    def rate_shipment(self, order):
        if self.delivery_type == 'stallion_express':
            return self.stallion_express_rate_shipment(order)
        return super().rate_shipment(order)