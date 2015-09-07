# -*- coding: utf-8 -*-
"""
    test_shipment
    Test GLS Integration
"""
from decimal import Decimal
from datetime import datetime
from dateutil.relativedelta import relativedelta

import os
import unittest
import trytond.tests.test_tryton
from trytond.tests.test_tryton import POOL, DB_NAME, USER, CONTEXT
from trytond.transaction import Transaction
from trytond.config import config

config.set('database', 'path', '.')


class TestGLSShipping(unittest.TestCase):
    """
    Test GLS Integration
    """

    def setUp(self):
        trytond.tests.test_tryton.install_module('shipping_gls')
        self.Address = POOL.get('party.address')
        self.Sale = POOL.get('sale.sale')
        self.SaleLine = POOL.get('sale.line')
        self.SaleConfig = POOL.get('sale.configuration')
        self.PackageType = POOL.get('stock.package.type')
        self.Package = POOL.get('stock.package')
        self.Product = POOL.get('product.product')
        self.Uom = POOL.get('product.uom')
        self.Account = POOL.get('account.account')
        self.Category = POOL.get('product.category')
        self.Carrier = POOL.get('carrier')
        self.Party = POOL.get('party.party')
        self.PartyContact = POOL.get('party.contact_mechanism')
        self.PaymentTerm = POOL.get('account.invoice.payment_term')
        self.Country = POOL.get('country.country')
        self.Subdivision = POOL.get('country.subdivision')
        self.PartyAddress = POOL.get('party.address')
        self.StockLocation = POOL.get('stock.location')
        self.StockShipmentOut = POOL.get('stock.shipment.out')
        self.Currency = POOL.get('currency.currency')
        self.Company = POOL.get('company.company')
        self.IrAttachment = POOL.get('ir.attachment')
        self.User = POOL.get('res.user')
        self.Template = POOL.get('product.template')
        self.GenerateLabel = POOL.get('shipping.label', type="wizard")

        assert 'GLS_SERVER' in os.environ, \
            "GLS_SERVER missing. Hint:Use export GLS_SERVER=<string>"
        assert 'GLS_PORT' in os.environ, \
            "GLS_PORT missing. Hint:Use export GLS_PORT=<string>"
        assert 'GLS_CONTRACT' in os.environ, \
            "GLS_CONTRACT missing. Hint:Use export GLS_CONTRACT=<string>"

        self.gls_server = os.environ['GLS_SERVER']
        self.gls_port = os.environ['GLS_PORT']
        self.gls_contract = os.environ['GLS_CONTRACT']

    def _create_coa_minimal(self, company):
        """Create a minimal chart of accounts
        """
        AccountTemplate = POOL.get('account.account.template')
        Account = POOL.get('account.account')

        account_create_chart = POOL.get(
            'account.create_chart', type="wizard"
        )

        account_template, = AccountTemplate.search(
            [('parent', '=', None)]
        )

        session_id, _, _ = account_create_chart.create()
        create_chart = account_create_chart(session_id)
        create_chart.account.account_template = account_template
        create_chart.account.company = company
        create_chart.transition_create_account()

        receivable, = Account.search([
            ('kind', '=', 'receivable'),
            ('company', '=', company),
        ])
        payable, = Account.search([
            ('kind', '=', 'payable'),
            ('company', '=', company),
        ])
        create_chart.properties.company = company
        create_chart.properties.account_receivable = receivable
        create_chart.properties.account_payable = payable
        create_chart.transition_create_properties()

    def _create_fiscal_year(self, date_=None, company=None):
        """
        Creates a fiscal year and requried sequences
        """
        FiscalYear = POOL.get('account.fiscalyear')
        Sequence = POOL.get('ir.sequence')
        SequenceStrict = POOL.get('ir.sequence.strict')
        Company = POOL.get('company.company')

        if date_ is None:
            date_ = datetime.utcnow().date()

        if not company:
            company, = Company.search([], limit=1)

        invoice_sequence, = SequenceStrict.create([{
            'name': '%s' % date_.year,
            'code': 'account.invoice',
            'company': company
        }])
        fiscal_year, = FiscalYear.create([{
            'name': '%s' % date_.year,
            'start_date': date_ + relativedelta(month=1, day=1),
            'end_date': date_ + relativedelta(month=12, day=31),
            'company': company,
            'post_move_sequence': Sequence.create([{
                'name': '%s' % date_.year,
                'code': 'account.move',
                'company': company,
            }])[0],
            'out_invoice_sequence': invoice_sequence,
            'in_invoice_sequence': invoice_sequence,
            'out_credit_note_sequence': invoice_sequence,
            'in_credit_note_sequence': invoice_sequence,
        }])
        FiscalYear.create_period([fiscal_year])
        return fiscal_year

    def _get_account_by_kind(self, kind, company=None, silent=True):
        """Returns an account with given spec
        :param kind: receivable/payable/expense/revenue
        :param silent: dont raise error if account is not found
        """
        Account = POOL.get('account.account')
        Company = POOL.get('company.company')

        if company is None:
            company, = Company.search([], limit=1)

        accounts = Account.search([
            ('kind', '=', kind),
            ('company', '=', company)
        ], limit=1)
        if not accounts and not silent:
            raise Exception("Account not found")
        return accounts[0] if accounts else None

    def _create_payment_term(self):
        """Create a simple payment term with all advance
        """
        PaymentTerm = POOL.get('account.invoice.payment_term')

        return PaymentTerm.create([{
            'name': 'Direct',
            'lines': [('create', [{'type': 'remainder'}])]
        }])

    def setup_defaults(self):
        """Method to setup defaults
        """
        # Create currency
        self.currency, = self.Currency.create([{
            'name': 'Euro',
            'code': 'EUR',
            'symbol': 'EUR',
        }])

        country_de, country_tw = self.Country.create([{
            'name': 'Germany',
            'code': 'DE',
        }, {
            'name': 'Taiwan',
            'code': 'TW',
        }])

        subdivision_bw, = self.Subdivision.create([{
            'name': 'Baden-Württemberg',
            'code': 'DE-BW',
            'type': 'state',
            'country': country_de.id,
        }])

        with Transaction().set_context(company=None):
            company_party, = self.Party.create([{
                'name': 'Orkos',
                'vat_number': '123456',
                'addresses': [('create', [{
                    'name': 'Fruchtzentrale Orkos',
                    'street': 'Luetzowstr. 28a',
                    'streetbis': '',
                    'zip': '45141',
                    'city': 'Dortmund',
                    'country': country_de.id,
                }])],
                'contact_mechanisms': [('create', [{
                    'type': 'phone',
                    'value': '030244547777778',
                }, {
                    'type': 'email',
                    'value': 'max@muster.de',
                }, {
                    'type': 'fax',
                    'value': '030244547777778',
                }, {
                    'type': 'mobile',
                    'value': '9876543212',
                }, {
                    'type': 'website',
                    'value': 'example.com',
                }])],
            }])

        self.company, = self.Company.create([{
            'party': company_party.id,
            'currency': self.currency.id,
        }])

        self.User.write(
            [self.User(USER)], {
                'main_company': self.company.id,
                'company': self.company.id,
            }
        )

        CONTEXT.update(self.User.get_preferences(context_only=True))

        self._create_fiscal_year(company=self.company)
        self._create_coa_minimal(company=self.company)
        self.payment_term, = self._create_payment_term()

        account_revenue, = self.Account.search([
            ('kind', '=', 'revenue')
        ])

        # Create product category
        category, = self.Category.create([{
            'name': 'Test Category',
        }])

        uom_kg, = self.Uom.search([('symbol', '=', 'kg')])
        uom_cm, = self.Uom.search([('symbol', '=', 'cm')])
        uom_pound, = self.Uom.search([('symbol', '=', 'lb')])

        # Carrier Carrier Product
        carrier_product_template, = self.Template.create([{
            'name': 'Test Carrier Product',
            'category': category.id,
            'type': 'service',
            'salable': True,
            'sale_uom': uom_kg,
            'list_price': Decimal('10'),
            'cost_price': Decimal('5'),
            'default_uom': uom_kg,
            'cost_price_method': 'fixed',
            'account_revenue': account_revenue.id,
            'products': [('create', self.Template.default_products())]
        }])

        carrier_product = carrier_product_template.products[0]

        # Create product
        template, = self.Template.create([{
            'name': 'Test Product',
            'category': category.id,
            'type': 'goods',
            'salable': True,
            'sale_uom': uom_kg,
            'list_price': Decimal('10'),
            'cost_price': Decimal('5'),
            'default_uom': uom_kg,
            'account_revenue': account_revenue.id,
            'weight': .5,
            'weight_uom': uom_pound.id,
            'products': [('create', self.Template.default_products())]
        }])

        self.product = template.products[0]

        # Create party
        carrier_party, = self.Party.create([{
            'name': 'Test Party',
        }])

        # Create party
        carrier_party, = self.Party.create([{
            'name': 'Test Party',
        }])

        values = {
            'party': carrier_party.id,
            'currency': self.company.currency.id,
            'carrier_product': carrier_product.id,
            'carrier_cost_method': 'gls',
            'gls_server': self.gls_server,
            'gls_port': self.gls_port,
            'gls_contract': self.gls_contract,
            'gls_customer_id': '2760179437',
            'gls_location': 'DE 460',
            'gls_shipping_depot_number': '46',
            'gls_is_test': True,
            'gls_customer_number': '15082',
            'gls_consignor_label': 'Empfanger',
            'gls_customer_id_label': 'ID-Nr',
            'gls_customer_label': 'Kd-Nr',
        }

        self.carrier, = self.Carrier.create([values])

        self.sale_party, self.sale_party2 = self.Party.create([{
            'name': 'GLS Germany',
            'vat_number': '123456',
            'addresses': [('create', [{
                'name': 'GLS Germany',
                'street': 'Huckarder Str. 91',
                'streetbis': '',
                'zip': '44147',
                'city': 'Dortmund',
                'country': country_de.id,
                'subdivision': subdivision_bw.id,
            }])],
            'contact_mechanisms': [('create', [{
                'type': 'phone',
                'value': '+886 2 27781-8',
            }, {
                'type': 'email',
                'value': 'kai@wahn.de',
            }])],
        }, {
            'name': 'Klammer Company',
            'vat_number': '123456',
            'addresses': [('create', [{
                'name': 'John Wick',
                'street': 'Chung Hsiao East Road.',
                'streetbis': '55',
                'zip': '100',
                'city': 'Taipeh',
                'country': country_tw.id,
            }])],
            'contact_mechanisms': [('create', [{
                'type': 'phone',
                'value': '+886 2 27781-8',
            }, {
                'type': 'email',
                'value': 'kai@wahn.de',
            }])],
        }])
        sale_config = self.SaleConfig()
        sale_config.save()

    def create_sale(self, party, is_gls_shipping=False):
        """
        Create and confirm sale order for party with default values.
        """
        with Transaction().set_context(company=self.company.id):

            # Create sale order
            sale_line1 = self.SaleLine(**{
                'type': 'line',
                'quantity': 1,
                'product': self.product,
                'unit_price': Decimal('10.00'),
                'description': 'Test Description1',
                'unit': self.product.template.default_uom,
            })
            sale_line2 = self.SaleLine(**{
                'type': 'line',
                'quantity': 1,
                'product': self.product,
                'unit_price': Decimal('5.00'),
                'description': 'Test Description2',
                'unit': self.product.template.default_uom,
            })
            sale = self.Sale(**{
                'reference': 'S-1001',
                'payment_term': self.payment_term,
                'party': party.id,
                'invoice_address': party.addresses[0].id,
                'shipment_address': party.addresses[0].id,
                'carrier': self.carrier.id,
                'lines': [sale_line1, sale_line2],
                'gls_shipping_depot_number': '46',
            })

            sale.save()

            sale.on_change_carrier()

            self.StockLocation.write([sale.warehouse], {
                'address': self.company.party.addresses[0].id,
            })

            # Confirm and process sale order
            self.assertEqual(len(sale.lines), 2)
            self.Sale.quote([sale])
            self.Sale.confirm([sale])
            self.Sale.process([sale])

    def test_0010_generate_gls_labels(self):
        """
        Test that GLS labels are being generated
        """
        Attachment = POOL.get('ir.attachment')

        with Transaction().start(DB_NAME, USER, context=CONTEXT):

            # Call method to create sale order
            self.setup_defaults()
            self.create_sale(self.sale_party, is_gls_shipping=True)

            shipment, = self.StockShipmentOut.search([])
            shipment.on_change_carrier()

            # Make shipment in packed state.
            shipment.assign([shipment])
            shipment.pack([shipment])

            shipment.save()

            # Create package
            package_type, = self.PackageType.create([{
                'name': 'Box',
            }])
            package1, = self.Package.create([{
                'code': 'ABC',
                'type': package_type.id,
                'shipment': (shipment.__name__, shipment.id),
                'moves': [('add', [shipment.outgoing_moves[0].id])],
            }])
            package2, = self.Package.create([{
                'code': 'DEF',
                'type': package_type.id,
                'shipment': (shipment.__name__, shipment.id),
                'moves': [('add', [shipment.outgoing_moves[1].id])],
            }])

            with Transaction().set_context(
                company=self.company.id, active_id=shipment.id
            ):
                # Call method to generate labels.
                session_id, start_state, _ = self.GenerateLabel.create()

                generate_label = self.GenerateLabel(session_id)

                result = generate_label.default_start({})

                self.assertEqual(result['shipment'], shipment.id)
                self.assertEqual(result['carrier'], shipment.carrier.id)

                generate_label.start.shipment = shipment.id
                generate_label.start.carrier = result['carrier']

                result = generate_label.default_gls_config({})

                generate_label.gls_config.depot_number = \
                    shipment.gls_shipping_depot_number
                generate_label.gls_config.service_type = \
                    shipment.gls_shipping_service_type

                generate_label.default_generate({})

            self.assertFalse(shipment.tracking_number is None)
            self.assertFalse(shipment.gls_parcel_number is None)

            for package in shipment.packages:
                self.assertFalse(package.tracking_number is None)

            self.assertEqual(
                Attachment.search_count([
                    (
                        'resource', 'like',
                        '%s,%s' % (shipment.__name__, shipment.id)
                    )
                ]), 2
            )
