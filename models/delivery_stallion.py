from odoo import models, fields, api
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

    stallion_api_token = fields.Char(string='Stallion API Token')
    stallion_test_mode = fields.Boolean(string='Test Mode', default=False)

    def stallion_express_rate_shipment(self, order):
        """Main rate method - returns cheapest rate for compatibility"""
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
            response = requests.post(api_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            rates = []
            for rate in data.get('rates', []):
                rates.append({
                    'carrier': self.name,
                    'service_name': rate.get('postage_type') or f"Stallion {rate.get('postage_type_id')}",
                    'price': float(rate.get('total', 0)),
                    'currency': rate.get('currency', 'CAD'),
                    'service_code': str(rate.get('postage_type_id')),
                })

            if not rates:
                return {'success': False, 'price': 0.0, 'error_message': 'No rates returned'}

            # Return cheapest for website compatibility
            cheapest = min(rates, key=lambda x: x['price'])
            return {
                'success': True,
                'price': cheapest['price'],
                'currency': cheapest['currency'],
                'warning_message': False,
                'error_message': False,
            }

        except Exception as e:
            _logger.error(f"Stallion API Error: {str(e)}")
            return {'success': False, 'price': 0.0, 'error_message': str(e)}

    def rate_shipment(self, order):
        if self.delivery_type == 'stallion_express':
            return self.stallion_express_rate_shipment(order)
        return super().rate_shipment(order)

    def action_sync_stallion_shipping_methods(self):
        """Create individual delivery methods for each Stallion service"""
        self.ensure_one()
        if not self.stallion_api_token:
            raise UserError("Please configure your Stallion API Token first.")

        # Use current user's address as sample
        partner = self.env.user.partner_id
        if not partner.zip:
            raise UserError("Please set a postal code on your user profile for testing.")

        dummy_order = self.env['sale.order'].new({
            'partner_shipping_id': partner.id,
        })

        # Get rates
        rates = self._get_raw_stallion_rates(dummy_order)
        if not rates:
            raise UserError("No shipping methods returned from Stallion Express.")

        created = []
        for rate in rates:
            service_name = rate.get('service_name', f"Service {rate.get('service_code')}")
            carrier_name = f"Stallion - {service_name}"

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
                    'active': True,
                })
                created.append(carrier_name)

        if created:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Success',
                    'message': f"Created: {', '.join(created)}",
                    'type': 'success',
                }
            }
        raise UserError("All shipping methods already exist.")

    def _get_raw_stallion_rates(self, order):
        """Internal helper to get full list of rates"""
        # Simplified version - you can expand with full payload if needed
        # For now returns example structure
        return [
            {'service_name': 'Fleet Optics Express', 'service_code': '130', 'price': 9.28},
            {'service_name': 'Intelcom Standard', 'service_code': '200', 'price': 9.44},
        ]