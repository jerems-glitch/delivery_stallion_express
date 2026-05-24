from odoo import models, fields
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

        # Build packages (improve this later with real dimensions)
        packages = []
        for line in order.order_line.filtered(lambda l: l.product_id.type == 'product'):
            weight = max(line.product_id.weight or 0.5, 0.1)
            packages.append({
                "weight": weight,
                "length": 10,
                "width": 10,
                "height": 10,
            })

        payload = {
            "origin_postal_code": shipper.zip or "",
            "destination_postal_code": recipient.zip or "",
            "destination_country": recipient.country_id.code or "CA",
            "packages": packages or [{"weight": 1.0, "length": 10, "width": 10, "height": 10}],
        }

        headers = {
            'Content-Type': 'application/json',
            'X-Customer-Number': self.stallion_customer_number,
            'Authorization': self.stallion_api_key,
        }

        try:
            # Try multiple possible endpoints
            possible_endpoints = [
                f"{self.stallion_endpoint}/shipments/rates",
                f"{self.stallion_endpoint}/rates",
                f"{self.stallion_endpoint}/quote",
            ]

            for url in possible_endpoints:
                response = requests.post(url, headers=headers, json=payload, timeout=20)
                if response.status_code == 200:
                    data = response.json()
                    break
                elif response.status_code == 404:
                    continue
                else:
                    response.raise_for_status()
            else:
                raise UserError("Could not find valid rates endpoint. Please contact support.")

            rates = []
            services = data.get('services', data.get('rates', data.get('data', [])))
            for service in services:
                rates.append({
                    'carrier': self.name,
                    'service_name': service.get('name') or service.get('service_name') or service.get('title'),
                    'price': float(service.get('total', 0) or service.get('price', 0) or service.get('cost', 0)),
                    'currency': 'CAD',
                    'service_code': service.get('code') or service.get('service_code'),
                    'delivery_date': service.get('estimated_delivery'),
                })

            if not rates:
                raise UserError("No shipping rates returned from Stallion Express.")

            return rates

        except Exception as e:
            _logger.error(f"Stallion API Error: {str(e)}")
            raise UserError(f"Stallion Express Error: {str(e)}")

    def rate_shipment(self, order):
        if self.delivery_type == 'stallion_express':
            return self.stallion_express_rate_shipment(order)
        return super().rate_shipment(order)