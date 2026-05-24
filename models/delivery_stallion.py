from odoo import models, fields
import requests
from odoo.exceptions import UserError
import logging
import json

_logger = logging.getLogger(__name__)


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(
        selection_add=[('stallion_express', 'Stallion Express')],
        ondelete={'stallion_express': 'set default'}
    )

    stallion_api_token = fields.Char(string='Stallion API Token', required=True)
    stallion_test_mode = fields.Boolean(string='Test Mode', default=False)
    stallion_postage_type_id = fields.Integer(string='Postage Type ID')

    def stallion_express_rate_shipment(self, order):
        if not self.stallion_api_token:
            raise UserError("Please configure your Stallion Express API Token.")

        shipping_address = order.partner_shipping_id
        if not shipping_address or not shipping_address.zip:
            raise UserError("Shipping address or postal code is missing.")

        # Calculate weight
        total_weight = sum(
            (line.product_id.weight or 0.5) * line.product_uom_qty
            for line in order.order_line if line.product_id.type == 'product'
        ) or 0.5

        # Build items - ALWAYS send at least one item
        items = []
        for line in order.order_line:
            if line.product_id and line.product_id.type == 'product':
                items.append({
                    'description': line.product_id.name or 'Product',
                    'sku': line.product_id.default_code or 'N/A',
                    'quantity': max(int(line.product_uom_qty), 1),
                    'value': line.price_unit or 1.0,
                    'currency': order.currency_id.name or 'CAD',
                    'country_of_origin': 'CA',
                    'hs_code': line.product_id.hs_code or '123456',
                })

        # Fallback: If no items (empty cart or only shipping products), send a default item
        if not items:
            items = [{
                'description': 'Package',
                'sku': 'PKG-001',
                'quantity': 1,
                'value': 10.0,
                'currency': order.currency_id.name or 'CAD',
                'country_of_origin': 'CA',
                'hs_code': '123456',
            }]

        to_address = {
            'name': shipping_address.name or '',
            'company': shipping_address.parent_id.name if shipping_address.parent_id else '',
            'address1': shipping_address.street or '',
            'address2': shipping_address.street2 or '',
            'city': shipping_address.city or '',
            'province_code': shipping_address.state_id.code or '',
            'postal_code': (shipping_address.zip or '').replace(' ', ''),
            'country_code': shipping_address.country_id.code or 'CA',
            'phone': shipping_address.phone or '',
            'email': shipping_address.email or '',
            'is_residential': not bool(shipping_address.is_company),
        }

        payload = {
            'to_address': to_address,
            'is_return': False,
            'weight_unit': 'kg',
            'weight': round(total_weight, 2),
            'length': 12,
            'width': 12,
            'height': 12,
            'size_unit': 'in',
            'items': items,
            'package_type': 'Parcel',
            'postage_types': [],
            'signature_confirmation': False,
            'insured': True,
            'region': 'ON',
        }

        base_url = 'https://ship.stallionexpress.ca'
        api_url = f'{base_url}/api/v4/rates'

        headers = {
            'Authorization': f'Bearer {self.stallion_api_token}',
            'Content-Type': 'application/json',
        }

        try:
            _logger.info(f"Stallion Request URL: {api_url}")
            response = requests.post(api_url, json=payload, headers=headers, timeout=30)

            _logger.info(f"Stallion Response Status: {response.status_code}")
            _logger.info(f"Stallion Response: {response.text[:2000]}")

            if response.status_code != 200:
                raise UserError(f"Stallion Error ({response.status_code}): {response.text[:600]}")

            data = response.json()
            rates = []
            for rate in data.get('rates', []):
                rates.append({
                    'carrier': self.name,
                    'service_name': rate.get('service_name') or rate.get('name') or 'Stallion Express',
                    'price': float(rate.get('total', 0)),
                    'currency': 'CAD',
                    'service_code': str(rate.get('postage_type_id')),
                })

            return rates

        except Exception as e:
            _logger.error(f"Stallion Error: {str(e)}")
            raise UserError(f"Stallion Express Error: {str(e)}")
    def rate_shipment(self, order):
        if self.delivery_type == 'stallion_express':
            return self.stallion_express_rate_shipment(order)
        return super().rate_shipment(order)