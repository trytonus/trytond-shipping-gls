# -*- coding: utf-8 -*-
"""
    carrier.py

    :copyright: (c) 2015 by Openlabs Technologies & Consulting (P) Limited
    :license: BSD, see LICENSE for more details.
"""
import os
from gls_unibox_api.api import Response, Shipment
from random import randint
from pystache import Renderer

from trytond.pool import PoolMeta, Pool
from trytond.model import fields, ModelView
from trytond.wizard import Wizard, StateView, Button
from trytond.pyson import Eval, Bool
from trytond.tools import file_open

__all__ = ['ShipmentOut', 'Package', 'GenerateShippingLabel', 'ShippingGLS']
__metaclass__ = PoolMeta

GLS_SERVICES = [
    ('euro_business_parcel', '[Euro] Business Parcel(Standard)'),
    ('cash_service_dac', 'Cash Service DAC'),
    ('cash_service_exchange', 'Cash Service - Exchange Service'),
    ('delivery_at_work', 'Delivery At Work - Service'),
    ('guaranteed_24', 'Guaranteed 24 - Service'),
    ('shop_return', 'Shop Return - Service'),
    ('intercompany', 'InterCompany - Service'),
    ('express_parcel', 'Express Parcel'),
    ('exchange_outgoing', 'Exchange - Service Outgoing Transport'),
    ('pick_return', 'Pick Up and Return - Exchange/Cash+Exchange'),
]

GLS_PRODUCT_CODES = {
    'euro_business_parcel': '10',  # XXX: This has a range
    'cash_service_dac': '71',
    'cash_service_exchange': '72',
    'delivery_at_work': '74',
    'guaranteed_24': '75',
    'shop_return': '76',
    'intercompany': '78',
    'express_parcel': '85',
    'exchange_outgoing': '87',
    'pick_return': '89',
}

STATES = {
    'readonly': Eval('state') == 'done',
    'required': Bool(Eval('is_gls_shipping')),
}

DEPENDS = ['is_gls_shipping', 'state']


class Package:
    __name__ = 'stock.package'

    gls_parcel_number = fields.Char(
        "Parcel Number", size=12,
        readonly=True
    )

    @classmethod
    def __setup__(cls):
        super(Package, cls).__setup__()

        cls._sql_constraints += [
            (
                'unique_parcel_number', 'UNIQUE(gls_parcel_number)',
                'The parcel number must be unique'
            )
        ]

    def _gen_parcel_check_number(self, parcel_number):
        """
        This method is used to calculate the check digit that is required at
        the end of the parcel number. It is calculated according to the
        Modulo 10+1 method.
        """
        sum_ = 0

        # Multiply each digit by weights, starting in reverse
        for idx, value in enumerate(parcel_number[::-1]):
            if idx % 2 == 0:
                # Multiply by 3 for even indices
                sum_ += (int(value) * 3)
            else:
                # Add the digit as it is, for odd indices
                sum_ += int(value)

        # Increment by 1
        sum_ += 1

        # Find next multiple of 10
        next_multiple = ((sum_ // 10) + 1) * 10

        # Subtract sum from this multiple
        return str(next_multiple - sum_)

    def _gen_parcel_number(self):
        """
        This method is used to generate the complete parcel number for GLS
        shipments. It is generated according to the following pattern -:

          Digit(s)  |  Index
            1-2     |  = Shipping-depot number
            3-4     |  = Product/service type
            5-11    |  = Randomly generated parcel number
            12      |  = Check digit
        """
        intermediate_parcel_number = ''.join(
            ["%s" % randint(0, 9) for num in range(0, 7)]
        )

        result = (
            self.shipment.gls_shipping_depot_number +
            GLS_PRODUCT_CODES[self.shipment.gls_shipping_service_type] +
            intermediate_parcel_number
        )

        # Now calculate check_digit
        check_digit = self._gen_parcel_check_number(result)

        return result + check_digit

    def _make_gls_label(self):
        """
        This method gets the prepared Shipment object and calls the GLS API
        for label generation.
        """
        Attachment = Pool().get('ir.attachment')

        shipment = self._get_shipment_object()
        response = Response.parse(shipment.create_label())

        # Get tracking number
        tracking_number = response.values.get('T8913')
        assert tracking_number

        # Create attachment
        # When saving data, the rendered template needs to be encoded back
        # to latin-1. This prevents any issues when a hexdigest of the data
        # is created by the data field setter.
        Attachment.create([{
            'name': "%s_%s.zpl" % (tracking_number, self.gls_parcel_number),
            'data': self.render_template(
                self.get_template_data(
                    'shipping_gls/labels/standard_label.txt'
                ),
                response.values
            ).encode('latin-1'),
            'resource': '%s,%s' % (self.shipment.__name__, self.shipment.id),
        }])

        return tracking_number

    def _get_shipment_object(self):
        """
        This method returns a Shipment object for consumption by the GLS API
        """
        shipment = self.shipment

        client = shipment.carrier.get_unibox_client()
        shipment_api = Shipment(client)

        shipment_api.software.name = 'Python'
        shipment_api.software.version = '2.7'

        consignee_address = shipment.customer.addresses[0]
        consignor_address = shipment.company.party.addresses[0]

        shipment_api.consignee.country = consignee_address.country.code
        shipment_api.consignee.zip = consignee_address.zip
        shipment_api.shipping_date = shipment.effective_date

        # TODO: Remove hardcoded values
        shipment_api.consignor.customer_number = 15082
        shipment_api.consignor.name = shipment.company.party.name
        shipment_api.consignor.name2 = consignor_address.name
        shipment_api.consignor.street = consignor_address.street
        shipment_api.consignor.country = consignor_address.country.code
        shipment_api.consignor.zip = consignor_address.zip
        shipment_api.consignor.place = consignor_address.city
        shipment_api.consignor.label = 'Empfanger'
        shipment_api.consignor.consignor = 'Essen'

        shipment_api.consignee.customer_number_label = 'Kd-Nr'
        shipment_api.consignee.customer_number = 4600
        shipment_api.consignee.id_type = 'ID-Nr'
        shipment_api.consignee.id_value = 800018406

        shipment_api.parcel = self.code  # sequence
        shipment_api.parcel_weight = self.package_weight

        shipment_api.parcel_number = self.gls_parcel_number
        shipment_api.quantity = 1

        shipment_api.gls_contract = shipment.carrier.gls_contract
        shipment_api.gls_customer_id = shipment.carrier.gls_customer_id
        shipment_api.location = shipment.carrier.gls_location

        return shipment_api

    @classmethod
    def get_template_data(cls, template_path):
        """
        Returns template data given a template path.

        :param path: String of the form '<module_name>/path/to/templates'
        """
        module, path = template_path.split('/', 1)

        try:
            with file_open(os.path.join(module, path)) as f:
                return f.read()
        except IOError:
            return None

    @classmethod
    def render_template(cls, template_string, context):
        """
        Render the template using pystache - this library has been chosen due to
        the fact that most web-ready templating engines in Python cannot deal
        with non-ascii characters when rendering a template. Pystache allows us
        to do so by setting attributes like string_encoding and file_encoding.

        The data returned from the GLS Server is presumably in latin-1 encoding,
        which is non-ascii and fits this use case.
        """
        renderer = Renderer(string_encoding='latin-1')

        return renderer.render(template_string, context)


class ShipmentOut:
    __name__ = 'stock.shipment.out'

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

    @staticmethod
    def default_gls_shipping_service_type():
        return 'euro_business_parcel'

    def get_is_gls_shipping(self, name=None):
        """
        Checks if shipping is to be done using GLS
        """
        return self.carrier and self.carrier.carrier_cost_method == 'gls'

    @fields.depends('is_gls_shipping', 'carrier')
    def on_change_carrier(self):
        """
        Show/Hide GLS tab in view on change of carrier
        """
        res = super(ShipmentOut, self).on_change_carrier()

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

    def _get_weight_uom(self):
        """
        Return uom for GLS
        """
        UOM = Pool().get('product.uom')
        if self.is_gls_shipping:
            return UOM.search([('symbol', '=', 'kg')])[0]
        return super(ShipmentOut, self)._get_weight_uom()  # pragma: no cover

    def make_gls_labels(self):
        """
        This method generates labels for each package/parcel in the given
        shipment.
        """
        if self.state not in ('packed', 'done'):
            self.raise_user_error('invalid_state')

        if not self.is_gls_shipping:
            self.raise_user_error('wrong_carrier', 'GLS')

        for package in self.packages:
            package.gls_parcel_number = package._gen_parcel_number()

            if not package.tracking_number:
                tracking_number = package._make_gls_label()
                package.tracking_number = tracking_number.strip()
            package.save()


class GenerateShippingLabel(Wizard):
    __name__ = 'shipping.label'

    gls_config = StateView(
        'shipping.label.gls',
        'shipping_gls.shipping_gls_config_wizard_view_form',
        [
            Button('Back', 'start', 'tryton-go-previous'),
            Button('Continue', 'generate', 'tryton-go-next'),
        ]
    )

    # TODO: Write a better final StateView for GLS, since no attachment is
    # saved in this case and only the tracking number is shown.

    def transition_next(self):
        state = super(GenerateShippingLabel, self).transition_next()

        if self.start.carrier.carrier_cost_method == 'gls':
            return 'gls_config'
        return state

    def default_gls_config(self, data):
        shipment = self.start.shipment

        return {
            'service_type': shipment.gls_shipping_service_type,
            'depot_number': shipment.gls_shipping_depot_number,
        }

    def update_shipment(self):
        """
        Downstream implementation which adds GLS-specific details if carrier
        cost method is gls.
        """
        shipment = super(GenerateShippingLabel, self).update_shipment()

        if self.start.carrier.carrier_cost_method == 'gls':
            shipment.gls_shipping_service_type = self.gls_config.service_type
            shipment.gls_shipping_depot_number = self.gls_config.depot_number

        return shipment


class ShippingGLS(ModelView):
    'Generate Labels'
    __name__ = 'shipping.label.gls'

    service_type = fields.Selection(
        GLS_SERVICES, "GLS Service/Product Type",
        required=True
    )

    depot_number = fields.Char(
        "GLS Depot Number", size=2, required=True
    )
