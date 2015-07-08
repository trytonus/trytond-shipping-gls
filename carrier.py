# -*- coding: utf-8 -*-
"""
    carrier.py

"""
from gls_unibox_api.api import Client
from decimal import Decimal

from shipment import GLS_SERVICES
from trytond.pool import PoolMeta, Pool
from trytond.model import fields
from trytond.pyson import Eval
from trytond.transaction import Transaction

__all__ = ['Carrier']
__metaclass__ = PoolMeta

STATES = {
    'required': Eval('carrier_cost_method') == 'gls',
    'invisible': Eval('carrier_cost_method') != 'gls'
}
DEPENDS = ['carrier_cost_method']


class Carrier:
    __name__ = 'carrier'

    gls_server = fields.Char(
        "GLS Server", states=STATES, depends=DEPENDS,
        help="GLS Server Address"
    )
    gls_port = fields.Char(
        "GLS Port", states=STATES, depends=DEPENDS,
        help="GLS Server Port No."
    )
    gls_contract = fields.Char(
        "GLS Contract", states=STATES, depends=DEPENDS,
        help="GLS Contract"
    )
    gls_customer_id = fields.Char(
        "GLS Customer ID", states=STATES, depends=DEPENDS,
        help="GLS Customer ID"
    )
    gls_location = fields.Char(
        "GLS Location", states=STATES, depends=DEPENDS,
        help="GLS Location"
    )
    gls_shipping_depot_number = fields.Char(
        "GLS Depot Number", states=STATES, depends=DEPENDS
    )
    gls_shipping_service_type = fields.Selection(
        GLS_SERVICES, 'GLS Service/Product Type',
        states=STATES, depends=DEPENDS
    )
    gls_is_test = fields.Boolean(
        'Is Test', states={
            'invisible': Eval('carrier_cost_method') != 'gls'
        }, depends=DEPENDS
    )
    gls_customer_number = fields.Char(
        "GLS Customer Number", states=STATES, depends=DEPENDS
    )
    gls_customer_label = fields.Char(
        'GLS Customer Name Label', states={
            'invisible': Eval('carrier_cost_method') != 'gls',
        }, depends=DEPENDS
    )
    gls_customer_id_label = fields.Char(
        'GLS Customer ID Label', states={
            'invisible': Eval('carrier_cost_method') != 'gls',
        }, depends=DEPENDS
    )
    gls_consignor_label = fields.Char(
        'GLS Consignor Label', states={
            'invisible': Eval('carrier_cost_method') != 'gls',
        }, depends=DEPENDS
    )
    gls_printer_resolution = fields.Selection(
        [
            ('zebrazpl200', '200dpi'),
            ('zebrazpl300', '300dpi'),
        ],
        'GLS Printer Resolution',
        states={
            'invisible': Eval('carrier_cost_method') != 'gls',
        }, depends=DEPENDS
    )

    def __init__(self, *args, **kwargs):
        super(Carrier, self).__init__(*args, **kwargs)
        self._gls_unibox_client = None

    @classmethod
    def __setup__(cls):
        super(Carrier, cls).__setup__()

        selection = ('gls', 'GLS')
        if selection not in cls.carrier_cost_method.selection:
            cls.carrier_cost_method.selection.append(selection)

    def get_unibox_client(self):
        """
        Returns the configured GLS Unibox client
        """
        if self._gls_unibox_client is None:
            client = Client(
                self.gls_server,
                self.gls_port
            )
            client.test = self.gls_is_test
            self._gls_unibox_client = client

        return self._gls_unibox_client

    def get_sale_price(self):
        """Estimates the shipment rate for the current shipment
           TODO: Fix this according to GLS shipping
        """
        Currency = Pool().get('currency.currency')
        Company = Pool().get('company.company')

        if self.carrier_cost_method != 'gls':
            return super(Carrier, self).get_sale_price()  # pragma: no cover

        currency, = Currency.search([('code', '=', 'EUR')])
        company = Transaction().context.get('company')

        if company:
            currency = Company(company).currency

        return Decimal('0'), currency.id

    @staticmethod
    def default_gls_shipping_service_type():
        return 'euro_business_parcel'

    @staticmethod
    def default_gls_printer_resolution():
        return 'zebrazpl200'
