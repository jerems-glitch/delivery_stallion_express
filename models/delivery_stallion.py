from odoo import models, fields, api
import requests
import json
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(selection_add=[('stallion_express', 'Stallion Express')], string='Provider')
    
    # Stallion credentials
    stallion_customer_number = fields.Char(string='Customer Number')
    stallion_api_key = fields.Char(string='API Key')
    stallion_endpoint = fields.Selection([
        ('https://sandbox.stallionexpress.ca/api/v4', 'Sandbox'),
        ('https://ship.stallionexpress.ca/api/v4', 'Production')
    ], string='API Endpoint', default='https://sandbox.stallionexpress.ca/api/v4')
    
    stallion_default_service = fields.Char(string='Default Service Code', help="e.g., 'express', 'priority' etc.")

    def stallion_express_rate_shipment(self, order):
        if not self.stallion_customer_number or not self.stallion_api_key:
            raise UserError("Stallion Express credentials are not configured.")

        shipper = order.warehouse_id.partner_id
        recipient = order.partner_shipping_id

        packages = []
        for line in order.order_line.filtered(lambda l: l.product_id.type == 'product'):
            weight = line.product_id.weight or 0.5
            packages.append({
                "weight": weight,
                "length": 10,
                "width": 10,
                "height": 10,
            })

        payload = {
            "origin_postal_code": shipper.zip,
            "destination_postal_code": recipient.zip,
            "destination_country": recipient.country_id.code,
            "packages": packages,
        }

        headers = {
            'Content-Type': 'application/json',
            'X-Customer-Number': self.stallion_customer_number,
            'Authorization': f'Bearer {self.stallion_api_key}'
        }

        try:
            response = requests.post(
                f"{self.stallion_endpoint}/rates",
                headers=headers,
                json=payload,
                timeout=15
            )
            response.raise_for_status()
            data = response.json()

            rates = []
            for service in data.get('services', data.get('rates', [])):
                rates.append({
                    'carrier': self.name,
                    'service_name': service.get('service_name') or service.get('name'),
                    'price': float(service.get('total') or service.get('price')),
                    'currency': 'CAD',
                    'delivery_date': service.get('estimated_delivery'),
                    'service_code': service.get('service_code'),
                })

            return rates

        except Exception as e:
            _logger.error(f"Stallion Express API Error: {str(e)}")
            raise UserError(f"Failed to get rates from Stallion Express: {str(e)}")

    def rate_shipment(self, order):
        if self.delivery_type == 'stallion_express':
            return self.stallion_express_rate_shipment(order)
        return super().rate_shipment(order)