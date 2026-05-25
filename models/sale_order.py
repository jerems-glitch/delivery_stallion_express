from odoo import models
import requests
import logging
import json

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _get_cached_stallion_rates(self):
        """Returns cached rates from the single bulk call"""
        return getattr(self, '_stallion_rates_cache', None)

    def _get_delivery_methods(self):
        carriers = super()._get_delivery_methods()
        result = self.env['delivery.carrier']

        # === SINGLE BULK CALL FOR ALL STALLION METHODS ===
        stallion_carriers = carriers.filtered(lambda c: c.delivery_type == 'stallion_express')
        if stallion_carriers and stallion_carriers[0].stallion_api_token:
            rates = self._fetch_all_stallion_rates(stallion_carriers[0])
            self._stallion_rates_cache = rates  # cache on order

        for carrier in carriers:
            if carrier.delivery_type == 'stallion_express':
                rate = carrier.rate_shipment(self)
                if rate.get('success'):
                    result |= carrier
            else:
                result |= carrier

        return result

    def _fetch_all_stallion_rates(self, carrier):
        """One single API call to get rates for all postage types"""
        shipping_address = self.partner_shipping_id
        if not shipping_address or not shipping_address.zip:
            return []

        total_weight = sum(
            (line.product_id.weight or 0.5) * line.product_uom_qty
            for line in self.order_line if line.product_id.type == 'product'
        ) or 0.5

        items = []
        for line in self.order_line:
            if line.product_id and line.product_id.type == 'product':
                items.append({
                    'description': line.product_id.name or 'Product',
                    'sku': line.product_id.default_code or 'N/A',
                    'quantity': max(int(line.product_uom_qty), 1),
                    'value': line.price_unit or 1.0,
                    'currency': self.currency_id.name or 'CAD',
                    'country_of_origin': 'CA',
                    'hs_code': line.product_id.hs_code or '123456',
                })

        if not items:
            items = [{'description': 'Package', 'sku': 'PKG-001', 'quantity': 1,
                      'value': 10.0, 'currency': self.currency_id.name or 'CAD',
                      'country_of_origin': 'CA', 'hs_code': '123456'}]

        to_address = {
            'name': shipping_address.name or '',
            'address1': shipping_address.street or '',
            'city': shipping_address.city or '',
            'province_code': shipping_address.state_id.code or '',
            'postal_code': (shipping_address.zip or '').replace(' ', ''),
            'country_code': shipping_address.country_id.code or 'CA',
            'is_residential': True,
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
        }

        url = 'https://ship.stallionexpress.ca/api/v4/rates'
        headers = {
            'Authorization': f'Bearer {carrier.stallion_api_token}',
            'Content-Type': 'application/json',
        }

        try:
            _logger.info("=== SINGLE BULK STALLION CALL ===")
            _logger.info(f"Payload: {json.dumps(payload, indent=2)}")

            resp = requests.post(url, json=payload, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            rates = data.get('rates', [])

            _logger.info(f"Bulk rates received: {len(rates)} methods")
            return rates

        except Exception as e:
            _logger.error(f"Bulk Stallion call failed: {e}")
            return []