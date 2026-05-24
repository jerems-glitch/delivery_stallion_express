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
    transit_days = fields.Char(string='Typical Transit Time')   # ← NEW

    def stallion_express_rate_shipment(self, order):
        # ... (keep your current working rate_shipment logic)
        # Just make sure it still works as before
        pass

    def rate_shipment(self, order):
        if self.delivery_type == 'stallion_express':
            return self.stallion_express_rate_shipment(order)
        return super().rate_shipment(order)

    # ====================== IMPROVED SYNC WITH TRANSIT TIME ======================
    def action_sync_stallion_shipping_methods(self):
        self.ensure_one()
        if not self.stallion_api_token:
            raise UserError("Please enter your Stallion API Token first.")

        base_url = 'https://ship.stallionexpress.ca'
        headers = {'Authorization': f'Bearer {self.stallion_api_token}'}

        # 1. Get all postage types
        types_resp = requests.get(f'{base_url}/api/v4/postage-types', headers=headers, timeout=30)
        types_resp.raise_for_status()
        postage_types = types_resp.json().get('postage_types', [])

        if not postage_types:
            raise UserError("No postage types returned from Stallion.")

        # 2. Get sample rates to capture delivery_days (using your address)
        partner = self.env.user.partner_id
        sample_order = self.env['sale.order'].new({'partner_shipping_id': partner.id})

        # Build minimal payload
        payload = self._build_sample_payload(sample_order)
        rates_resp = requests.post(f'{base_url}/api/v4/rates', json=payload, headers=headers, timeout=30)
        rates_resp.raise_for_status()
        rates_data = rates_resp.json().get('rates', [])

        # Create map of postage_type → delivery_days
        transit_map = {}
        for rate in rates_data:
            ptype = rate.get('postage_type')
            days = rate.get('delivery_days')
            if ptype and days:
                transit_map[ptype] = days

        created = []
        for ptype in postage_types:
            carrier_name = f"Stallion - {ptype}"
            transit = transit_map.get(ptype, '')

            if transit:
                display_name = f"{carrier_name} ({transit} days)"
            else:
                display_name = carrier_name

            existing = self.search([
                ('name', 'ilike', f"Stallion - {ptype}"),
                ('delivery_type', '=', 'stallion_express')
            ], limit=1)

            vals = {
                'name': display_name,
                'delivery_type': 'stallion_express',
                'product_id': self.product_id.id,
                'stallion_api_token': self.stallion_api_token,
                'stallion_postage_type': ptype,
                'transit_days': transit,
                'active': True,
            }

            if existing:
                existing.write(vals)
            else:
                self.create(vals)
                created.append(ptype)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Shipping Methods Updated',
                'message': f"Synced {len(postage_types)} methods with transit times",
                'type': 'success',
            }
        }

    def _build_sample_payload(self, order):
        """Helper to build a sample payload for getting transit times"""
        partner = order.partner_shipping_id or self.env.user.partner_id
        return {
            'to_address': {
                'name': partner.name or '',
                'address1': partner.street or '',
                'city': partner.city or '',
                'province_code': partner.state_id.code or '',
                'postal_code': (partner.zip or '').replace(' ', ''),
                'country_code': partner.country_id.code or 'CA',
                'is_residential': True,
            },
            'weight': 1,
            'weight_unit': 'kg',
            'length': 12, 'width': 12, 'height': 12,
            'size_unit': 'in',
            'items': [{'description': 'Sample', 'quantity': 1, 'value': 10, 'currency': 'CAD'}],
            'package_type': 'Parcel',
        }