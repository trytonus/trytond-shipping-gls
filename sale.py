# -*- coding: utf-8 -*-
"""
    sale.py

"""
from trytond.pool import PoolMeta, Pool
from trytond.model import fields
from trytond.pyson import Eval, Bool

from shipment import GLS_SERVICES

__all__ = ['Sale']
__metaclass__ = PoolMeta

STATES = {
    'readonly': Eval('state') == 'done',
    'required': Bool(Eval('is_gls_shipping')),
}
DEPENDS = ['state', 'is_gls_shipping']


class Sale:
    "Sale"
    __name__ = 'sale.sale'

    is_gls_shipping = fields.Function(
        fields.Boolean('Is GLS Shipping?'),
        getter='get_is_gls_shipping'
    )

    gls_shipping_depot_number = fields.Char(
        "GLS Depot Number", size=2,
        states=STATES, depends=DEPENDS
    )

    gls_shipping_service_type = fields.Selection(
        GLS_SERVICES, 'GLS Service/Product Type', states=STATES,
        depends=DEPENDS
    )

    def get_is_gls_shipping(self, name=None):
        """
        Checks if shipping is to be done using GLS
        """
        return self.carrier and self.carrier.carrier_cost_method == 'gls'

    @staticmethod
    def default_gls_shipping_service_type():
        return 'euro_business_parcel'

    @fields.depends('is_gls_shipping', 'carrier')
    def on_change_carrier(self):
        """
        Show/Hide GLS tab in view on change of carrier
        """
        res = super(Sale, self).on_change_carrier()

        if self.carrier and self.carrier.carrier_cost_method == 'gls':
            res['is_gls_shipping'] = True
            res['gls_shipping_depot_number'] = \
                self.carrier.gls_shipping_depot_number
            res['gls_shipping_service_type'] = \
                self.carrier.gls_shipping_service_type

            # Future-proof: change active record
            self.is_gls_shipping = True
            self.gls_shipping_depot_number = res['gls_shipping_depot_number']
            self.gls_shipping_service_type = res['gls_shipping_service_type']

        return res

    def _get_shipment_sale(self, Shipment, key):
        """
        Downstream implementation which adds gls-specific fields to the unsaved
        Shipment record.
        """
        ShipmentOut = Pool().get('stock.shipment.out')

        shipment = super(Sale, self)._get_shipment_sale(Shipment, key)

        if Shipment == ShipmentOut and self.is_gls_shipping:
            shipment.gls_shipping_depot_number = self.gls_shipping_depot_number
            shipment.gls_shipping_service_type = self.gls_shipping_service_type

        return shipment
