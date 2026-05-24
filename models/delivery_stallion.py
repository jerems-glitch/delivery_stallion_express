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
    stallion_test_mode = fields.Boolean(string='Test Mode', default=True)
    stallion_postage_type_id = fields.Integer(string='Postage Type ID')

    def stallion_express_rate_shipment(self, order):
        if not self.stallion_api_token:
            raise UserError("Stallion Express API Token is not configured.")

        shipping_address = order.partner_shipping_id
        company_address = order.company_id.partner_id or order.warehouse_id.partner_id

        total_weight = sum(
            (line.product_id.weight or 0.5) * line.product_uom_qty
            for line in order.order_line if line.product_id.type == 'product'
        ) or 0.5

        items = []
        for line in order.order_line:
            if line.product_id and line.product_id.type == 'product':
                items.append({
                    'description': line.product_id.name or 'Product',
                    'sku': line.product_id.default_code or '',
                    'quantity': int(line.product_uom_qty),
                    'value': line.price_unit,
                    'currency': order.currency_id.name or 'CAD',
                })

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
            'weight': total_weight,
            'length': 12,
            'width': 12,
            'height': 12,
            'size_unit': 'in',
            'items': items or [{}],
            'package_type': 'Parcel',
            'postage_types': [],
            'signature_confirmation': False,
            'insured': True,
        }

        base_url = 'https://sandbox.stallionexpress.ca' if self.stallion_test_mode else 'https://ship.stallionexpress.ca'
        api_url = f'{base_url}/api/v4/rates'

        headers = {
            'Authorization': f'Bearer {self.stallion_api_token}',
            'Content-Type': 'application/json',
        }

        try:
            _logger.info(f"Stallion Request URL: {api_url}")
            _logger.info(f"Stallion Request Payload: {json.dumps(payload, indent=2)}")

            response = requests.post(api_url, json=payload, headers=headers, timeout=30)

            _logger.info(f"Stallion Response Status: {response.status_code}")
            _logger.info(f"Stallion Response Body: {response.text}")

            response.raise_for_status()
            data = response.json()

            rates = []
            for rate in data.get('rates', []):
                rates.append({
                    'carrier': self.name,
                    'service_name': rate.get('service_name') or rate.get(
                        'name') or f"Stallion {rate.get('postage_type_id')}",
                    'price': float(rate.get('total', 0)),
                    'currency': 'CAD',
                    'service_code': str(rate.get('postage_type_id')),
                })

            if not rates:
                raise UserError("No rates returned. Check server logs for details.")

            return rates

        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP Error {response.status_code}: {response.text}"
            _logger.error(error_msg)
            raise UserError(f"Stallion Express Error: {error_msg}")
        except Exception as e:
            _logger.error(f"Unexpected error: {str(e)}")
            raise UserError(f"Stallion Express Error: {str(e)}")

    def rate_shipment(self, order):
        if self.delivery_type == 'stallion_express':
            return self.stallion_express_rate_shipment(order)
        return super().rate_shipment(order)