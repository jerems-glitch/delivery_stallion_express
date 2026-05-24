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

    stallion_api_token = fields.Char(string='Stallion API Token')
    stallion_test_mode = fields.Boolean(string='Test Mode', default=False)
    stallion_postage_type = fields.Char(string='Stallion Postage Type')  # ← NEW FIELD

    # ====================== RATE SHIPMENT ======================
    def stallion_express_rate_shipment(self, order):
        if not self.stallion_api_token:
            raise UserError("Stallion Express API Token is not configured.")

        shipping_address = order.partner_shipping_id
        if not shipping_address or not shipping_address.zip:
            raise UserError("Shipping address or postal code is missing.")

        total_weight = sum(
            (line.product_id.weight or 0.5) * line.product_uom_qty
            for line in order.order_line if line.product_id.type == 'product'
        ) or 0.5

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
            'postage_types': [self.stallion_postage_type] if self.stallion_postage_type else [],
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
            response = requests.post(api_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            rates = data.get('rates', [])
            if not rates:
                return {'success': False, 'price': 0.0, 'error_message': 'No rates returned'}

            # If this carrier has a specific postage type, try to match it
            if self.stallion_postage_type:
                for rate in rates:
                    if rate.get('postage_type') == self.stallion_postage_type:
                        return {
                            'success': True,
                            'price': float(rate.get('total', 0)),
                            'currency': rate.get('currency', 'CAD'),
                            'warning_message': False,
                            'error_message': False,
                        }

            # Fallback: return cheapest
            cheapest = min(rates, key=lambda x: float(x.get('total', 0)))
            return {
                'success': True,
                'price': float(cheapest.get('total', 0)),
                'currency': cheapest.get('currency', 'CAD'),
                'warning_message': False,
                'error_message': False,
            }

        except Exception as e:
            _logger.error(f"Stallion Error: {str(e)}")
            return {'success': False, 'price': 0.0, 'error_message': str(e)}

    def rate_shipment(self, order):
        if self.delivery_type == 'stallion_express':
            return self.stallion_express_rate_shipment(order)
        return super().rate_shipment(order)

    # ====================== SYNC BUTTON ======================
    def action_sync_stallion_shipping_methods(self):
        self.ensure_one()
        if not self.stallion_api_token:
            raise UserError("Please enter your Stallion API Token first.")

        url = 'https://ship.stallionexpress.ca/api/v4/postage-types'
        headers = {'Authorization': f'Bearer {self.stallion_api_token}'}

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            postage_types = data.get('postage_types', [])

            created = []
            for ptype in postage_types:
                carrier_name = f"Stallion - {ptype}"

                existing = self.search([
                    ('name', '=', carrier_name),
                    ('delivery_type', '=', 'stallion_express')
                ], limit=1)

                if not existing:
                    self.create({
                        'name': carrier_name,
                        'delivery_type': 'stallion_express',
                        'product_id': self.product_id.id,
                        'stallion_api_token': self.stallion_api_token,
                        'stallion_test_mode': self.stallion_test_mode,
                        'stallion_postage_type': ptype,           # ← Save the exact type
                        'active': True,
                    })
                    created.append(ptype)

            if created:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success',
                        'message': f"Created {len(created)} shipping methods",
                        'type': 'success',
                    }
                }
            raise UserError("All methods already exist.")

        except Exception as e:
            raise UserError(f"Sync failed: {str(e)}")