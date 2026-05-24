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

    stallion_api_token = fields.Char(string='Stallion API Token')
    stallion_test_mode = fields.Boolean(string='Test Mode', default=False)
    stallion_postage_type = fields.Char(string='Stallion Postage Type')
    last_delivery_days = fields.Char(string='Last Transit Time', readonly=True)

    # Package Type Support (Volume + Dimensional Weight)
    default_package_type_id = fields.Many2one(
        'stock.package.type',
        string='Default Package Type',
        help="Used for real dimensional weight calculation"
    )

    def stallion_express_rate_shipment(self, order):
        if not self.stallion_api_token:
            raise UserError("Stallion API Token is missing.")

        shipping_address = order.partner_shipping_id
        if not shipping_address or not shipping_address.zip:
            raise UserError("Shipping address is incomplete.")

        # === Weight & Volume Calculation ===
        total_weight = sum(
            (line.product_id.weight or 0.5) * line.product_uom_qty
            for line in order.order_line if line.product_id.type == 'product'
        ) or 0.5

        # === Get dimensions from selected Package Type (safe access) ===
        if self.default_package_type_id:
            pkg = self.default_package_type_id
            length = getattr(pkg, 'length', 12) or 12
            width  = getattr(pkg, 'width', 12) or 12
            height = getattr(pkg, 'height', 12) or 12
            size_unit = 'cm' if getattr(pkg, 'length_uom_id', False) and pkg.length_uom_id.name == 'cm' else 'in'
        else:
            length = width = height = 12
            size_unit = 'in'

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
            items = [{'description': 'Package', 'sku': 'PKG-001', 'quantity': 1,
                      'value': 10.0, 'currency': order.currency_id.name or 'CAD',
                      'country_of_origin': 'CA', 'hs_code': '123456'}]

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
            'length': length,
            'width': width,
            'height': height,
            'size_unit': size_unit,
            'items': items,
            'package_type': 'Parcel',
            'postage_types': [self.stallion_postage_type] if self.stallion_postage_type else [],
            'signature_confirmation': False,
            'insured': True,
            'region': 'ON',
        }

        url = 'https://ship.stallionexpress.ca/api/v4/rates'
        headers = {
            'Authorization': f'Bearer {self.stallion_api_token}',
            'Content-Type': 'application/json',
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            rates = data.get('rates', [])

            if not rates:
                return {'success': False, 'price': 0.0, 'error_message': 'No rates available'}

            chosen = None
            if self.stallion_postage_type:
                for r in rates:
                    if r.get('postage_type') == self.stallion_postage_type:
                        chosen = r
                        break

            if not chosen:
                return {'success': False, 'price': 0.0,
                        'error_message': f'No rate for {self.stallion_postage_type}'}

            # Dynamic transit time
            delivery_days = chosen.get('delivery_days', '')
            if delivery_days:
                new_name = f"Stallion - {self.stallion_postage_type} ({delivery_days} days)"
                self.sudo().write({
                    'name': new_name,
                    'last_delivery_days': delivery_days
                })

            return {
                'success': True,
                'price': float(chosen.get('total', 0)),
                'currency': chosen.get('currency', 'CAD'),
            }

        except Exception as e:
            return {'success': False, 'price': 0.0, 'error_message': str(e)}

    def rate_shipment(self, order):
        if self.delivery_type == 'stallion_express':
            return self.stallion_express_rate_shipment(order)
        return super().rate_shipment(order)

    def action_sync_stallion_shipping_methods(self):
        self.ensure_one()
        if not self.stallion_api_token:
            raise UserError("API Token is required.")

        base_url = 'https://ship.stallionexpress.ca'
        headers = {'Authorization': f'Bearer {self.stallion_api_token}'}

        t = requests.get(f'{base_url}/api/v4/postage-types', headers=headers, timeout=30)
        t.raise_for_status()
        postage_types = t.json().get('postage_types', [])

        created = 0
        for ptype in postage_types:
            name = f"Stallion - {ptype}"
            if not self.search([('name', '=', name)], limit=1):
                self.create({
                    'name': name,
                    'delivery_type': 'stallion_express',
                    'product_id': self.product_id.id,
                    'stallion_api_token': self.stallion_api_token,
                    'stallion_postage_type': ptype,
                    'active': True,
                })
                created += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': 'Success', 'message': f"Synced {created} methods", 'type': 'success'}
        }