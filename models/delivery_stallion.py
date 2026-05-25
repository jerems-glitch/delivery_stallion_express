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

    stallion_api_token = fields.Char(string='Stallion API Token')
    stallion_test_mode = fields.Boolean(string='Test Mode', default=False)
    stallion_postage_type = fields.Char(string='Stallion Postage Type')
    last_delivery_days = fields.Char(string='Last Transit Time', readonly=True)

    default_package_type_id = fields.Many2one(
        'stock.package.type',
        string='Default Package Type'
    )

    def stallion_express_rate_shipment(self, order):
        """Fast version - reads from bulk cached rates"""
        if not self.stallion_api_token:
            raise UserError("Stallion API Token is missing.")

        cached_rates = order._get_cached_stallion_rates()
        if not cached_rates:
            return {'success': False, 'price': 0.0, 'error_message': 'No rates available'}

        # Find matching rate for this specific method
        chosen = None
        if self.stallion_postage_type:
            for r in cached_rates:
                if r.get('postage_type') == self.stallion_postage_type:
                    chosen = r
                    break

        if not chosen:
            return {'success': False, 'price': 0.0, 'error_message': f'No rate for {self.stallion_postage_type}'}

        # Add user's Additional Margin
        base_price = float(chosen.get('total', 0))
        margin = self.margin or 0.0
        final_price = base_price + margin

        # Save transit time
        delivery_days = chosen.get('delivery_days', '')
        if delivery_days:
            self.sudo().write({'last_delivery_days': delivery_days})

        return {
            'success': True,
            'price': final_price,
            'currency': chosen.get('currency', 'CAD'),
        }

    def rate_shipment(self, order):
        if self.delivery_type == 'stallion_express':
            return self.stallion_express_rate_shipment(order)
        return super().rate_shipment(order)