"""
Tests for the freight quoting rules and the rate request sheets.

The arithmetic tests use plain stand-in objects rather than saved rows: the
quoting module only reads attributes off whatever it is handed, so the freight
rules can be checked without a database. Anything failing there is a pricing
bug, not a Django bug.

The rate sheet tests do need the database, because a round trip through Excel is
only meaningful against real destinations and cargo types.
"""

from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from openpyxl import load_workbook

from . import quoting, rate_sheets
from .models import (CargoType, CompanySettings, ShippingCompany,
                     ShippingDestination, ShippingRate, TeamMember,
                     sync_legacy_rate_columns)


def rate_row(rate, method='air', divisor=0, minimum=0, company=None, transit=''):
    """A stand-in ShippingRate. 0 on divisor/minimum means "inherit"."""
    return SimpleNamespace(
        rate=Decimal(str(rate)), method=method,
        volumetric_divisor=Decimal(str(divisor)), minimum=Decimal(str(minimum)),
        transit_days=transit, company=company)


def company(name='TestCo', divisor=0, min_kg=0, min_cbm=0):
    """A stand-in ShippingCompany carrying the middle level of fallbacks."""
    return SimpleNamespace(
        name=name, volumetric_divisor=Decimal(str(divisor)),
        min_chargeable_kg=Decimal(str(min_kg)), min_cbm=Decimal(str(min_cbm)))


def global_settings(**values):
    """A stand-in CompanySettings supplying the outermost fallbacks."""
    defaults = {
        'air_shipping_rate': Decimal('0'), 'sea_shipping_rate': Decimal('0'),
        'ksa_air_shipping_rate': Decimal('0'), 'ksa_sea_shipping_rate': Decimal('0'),
        'no_brand_battery_air_shipping_rate': Decimal('0'),
        'no_brand_battery_sea_shipping_rate': Decimal('0'),
        'no_brand_battery_ksa_air_shipping_rate': Decimal('0'),
        'no_brand_battery_ksa_sea_shipping_rate': Decimal('0'),
        'volumetric_divisor': Decimal('6000'),
        'min_chargeable_kg': Decimal('0'), 'min_cbm': Decimal('0'),
    }
    defaults.update({k: Decimal(str(v)) for k, v in values.items()})
    return SimpleNamespace(**defaults)


# A 60x40x40 cm carton weighing 8 kg. Bulky for its weight, so at the IATA
# divisor of 6000 it is charged as 16 kg rather than 8 - the single case the
# whole volumetric rule exists for.
BULKY = [{'length_cm': 60, 'width_cm': 40, 'height_cm': 40, 'weight_kg': 8, 'quantity': 1}]


class VolumetricWeightTests(SimpleTestCase):
    """max(actual, volume/divisor) - the rule air freight is priced on."""

    def test_volume_wins_for_a_bulky_carton(self):
        m = quoting.line_metrics(60, 40, 40, 8, 1, Decimal('6000'))
        self.assertEqual(m['actual_kg'], Decimal('8.000'))
        self.assertEqual(m['volumetric_kg'], Decimal('16.000'))
        self.assertEqual(m['chargeable_kg'], Decimal('16.000'))

    def test_weight_wins_for_a_dense_carton(self):
        m = quoting.line_metrics(60, 40, 40, 30, 1, Decimal('6000'))
        self.assertEqual(m['chargeable_kg'], Decimal('30.000'))

    def test_a_smaller_divisor_charges_more_for_the_same_box(self):
        at_6000 = quoting.line_metrics(60, 40, 40, 8, 1, Decimal('6000'))
        at_5000 = quoting.line_metrics(60, 40, 40, 8, 1, Decimal('5000'))
        self.assertEqual(at_5000['volumetric_kg'], Decimal('19.200'))
        self.assertGreater(at_5000['chargeable_kg'], at_6000['chargeable_kg'])

    def test_quantity_scales_weight_and_volume(self):
        m = quoting.line_metrics(60, 40, 40, 8, 10, Decimal('6000'))
        self.assertEqual(m['actual_kg'], Decimal('80.000'))
        self.assertEqual(m['volumetric_kg'], Decimal('160.000'))
        self.assertEqual(m['cbm'], Decimal('0.960'))

    def test_cbm_is_volume_over_a_million(self):
        self.assertEqual(
            quoting.line_metrics(100, 100, 100, 1, 1, Decimal('6000'))['cbm'],
            Decimal('1.000'))

    def test_a_zero_divisor_does_not_divide_by_zero(self):
        self.assertEqual(
            quoting.line_metrics(10, 10, 10, 1, 1, Decimal('0'))['volumetric_kg'],
            Decimal('0'))

    def test_missing_and_junk_values_are_treated_as_zero(self):
        m = quoting.line_metrics(None, '', 'abc', None, 0, Decimal('6000'))
        self.assertEqual(m['actual_kg'], Decimal('0.000'))
        self.assertEqual(m['volumetric_kg'], Decimal('0.000'))


class ShipmentTotalsTests(SimpleTestCase):

    def test_chargeable_weight_is_summed_per_line(self):
        """
        The mixed-shipment case, and the easiest one to get wrong.

        One bulky-light carton (charged on its 16 kg of volume) and one
        small-dense one (charged on its 40 kg of weight) come to 56 kg. Taking
        max() across the shipment TOTALS instead gives max(48, 17.667) = 48 kg
        and undercharges by eight kilos - an error that grows with every mixed
        consignment and is only found when the airline invoices.
        """
        lines = [
            {'length_cm': 60, 'width_cm': 40, 'height_cm': 40, 'weight_kg': 8, 'quantity': 1},
            {'length_cm': 20, 'width_cm': 20, 'height_cm': 25, 'weight_kg': 40, 'quantity': 1},
        ]
        totals = quoting.shipment_totals(lines, Decimal('6000'))
        self.assertEqual(totals['actual_kg'], Decimal('48.000'))
        self.assertEqual(totals['volumetric_kg'], Decimal('17.667'))
        self.assertEqual(totals['chargeable_kg'], Decimal('56.000'))
        self.assertNotEqual(totals['chargeable_kg'], Decimal('48.000'))

    def test_counts_cartons_not_lines(self):
        lines = [
            {'length_cm': 10, 'width_cm': 10, 'height_cm': 10, 'weight_kg': 1, 'quantity': 4},
            {'length_cm': 10, 'width_cm': 10, 'height_cm': 10, 'weight_kg': 1, 'quantity': 6},
        ]
        self.assertEqual(quoting.shipment_totals(lines, Decimal('6000'))['cartons'], 10)


class DivisorFallbackTests(SimpleTestCase):
    """Lane, then company, then global, then IATA."""

    def test_the_lane_wins_when_it_sets_one(self):
        self.assertEqual(
            quoting.divisor_for(rate_row(20, divisor=4500), company(divisor=5000),
                                global_settings()),
            Decimal('4500'))

    def test_falls_back_to_the_company(self):
        self.assertEqual(
            quoting.divisor_for(rate_row(20), company(divisor=5000), global_settings()),
            Decimal('5000'))

    def test_falls_back_to_the_global_default(self):
        self.assertEqual(
            quoting.divisor_for(rate_row(20), company(),
                                global_settings(volumetric_divisor=5500)),
            Decimal('5500'))

    def test_falls_back_to_iata_when_nothing_is_configured(self):
        self.assertEqual(
            quoting.divisor_for(rate_row(20), company(),
                                global_settings(volumetric_divisor=0)),
            Decimal('6000'))


class QuoteTests(SimpleTestCase):

    def test_air_cost_is_chargeable_weight_times_rate(self):
        quote = quoting.quote_for_rate(
            rate_row(22, divisor=6000, company=company()), BULKY, global_settings())
        self.assertEqual(quote['billed'], Decimal('16.000'))   # volumetric, not 8
        self.assertEqual(quote['cost'], Decimal('352.00'))
        self.assertTrue(quote['volumetric_applied'])

    def test_sea_cost_is_cbm_times_rate(self):
        quote = quoting.quote_for_rate(
            rate_row(120, method='sea', company=company()), BULKY, global_settings())
        self.assertEqual(quote['billed'], Decimal('0.096'))
        self.assertEqual(quote['cost'], Decimal('11.52'))
        self.assertFalse(quote['volumetric_applied'])

    def test_a_rate_of_zero_is_not_a_quote(self):
        """
        Not a free shipment.

        A lane with no rate has to be ABSENT from the comparison. Quoting it at
        0.00 would make it the cheapest every time and show the customer free
        shipping.
        """
        self.assertIsNone(quoting.quote_for_rate(
            rate_row(0, company=company()), BULKY, global_settings()))

    def test_lane_minimum_is_applied_and_flagged(self):
        quote = quoting.quote_for_rate(
            rate_row(25, divisor=6000, minimum=45, company=company()),
            BULKY, global_settings())
        self.assertEqual(quote['billed'], Decimal('45'))
        self.assertTrue(quote['minimum_applied'])
        self.assertEqual(quote['cost'], Decimal('1125.00'))

    def test_minimum_falls_back_to_the_company_then_the_global(self):
        from_company = quoting.quote_for_rate(
            rate_row(25, divisor=6000, company=company(min_kg=45)),
            BULKY, global_settings())
        self.assertEqual(from_company['billed'], Decimal('45'))

        from_global = quoting.quote_for_rate(
            rate_row(25, divisor=6000, company=company()),
            BULKY, global_settings(min_chargeable_kg=30))
        self.assertEqual(from_global['billed'], Decimal('30'))

    def test_sea_minimum_uses_cbm_not_kilograms(self):
        quote = quoting.quote_for_rate(
            rate_row(100, method='sea', company=company(min_cbm=1)),
            BULKY, global_settings())
        self.assertEqual(quote['billed'], Decimal('1'))
        self.assertEqual(quote['cost'], Decimal('100.00'))

    def test_a_shipment_over_the_minimum_is_not_flagged(self):
        quote = quoting.quote_for_rate(
            rate_row(25, divisor=6000, minimum=5, company=company()),
            BULKY, global_settings())
        self.assertFalse(quote['minimum_applied'])
        self.assertEqual(quote['billed'], Decimal('16.000'))


class BestQuoteTests(SimpleTestCase):

    def test_cheapest_first_and_each_lane_uses_its_own_divisor(self):
        """
        A lower rate per KG is not necessarily a lower price.

        SharpRate charges 20/kg but divides by 5000, so it bills 19.2 kg = 384.
        FairVolume charges 22/kg and divides by 6000, billing 16 kg = 352.
        Comparing on the rate column alone would pick the dearer one.
        """
        quotes = quoting.best_quote(
            [rate_row(20, divisor=5000, company=company('SharpRate')),
             rate_row(22, divisor=6000, company=company('FairVolume'))],
            BULKY, global_settings())
        self.assertEqual([q['company_name'] for q in quotes], ['FairVolume', 'SharpRate'])
        self.assertEqual(quotes[0]['cost'], Decimal('352.00'))
        self.assertEqual(quotes[1]['cost'], Decimal('384.00'))

    def test_no_rates_yields_no_quotes(self):
        self.assertEqual(quoting.best_quote([], BULKY, global_settings()), [])


class HouseRateTests(SimpleTestCase):
    """The global fallback that keeps the calculator answering."""

    def test_the_eight_legacy_lanes_have_a_global(self):
        row = quoting.house_rate_row(
            global_settings(air_shipping_rate=28), 'AE', 'general', 'air')
        self.assertIsNotNone(row)
        self.assertEqual(row.rate, Decimal('28'))

    def test_battery_falls_back_to_the_battery_global_not_the_standard_one(self):
        """
        The fallback must match the cargo type, not just the method.

        An earlier version fell through to air_shipping_rate - the GENERAL cargo
        rate - so dangerous goods were quoted at around half what they cost,
        silently, with nothing to indicate the wrong column had been read.
        """
        settings = global_settings(air_shipping_rate=28,
                                   no_brand_battery_air_shipping_rate=55)
        row = quoting.house_rate_row(settings, 'AE', 'non-branded-battery', 'air')
        self.assertEqual(row.rate, Decimal('55'))

    def test_a_lane_with_no_global_returns_nothing(self):
        """A new country or cargo type has no house rate and never had one."""
        settings = global_settings(air_shipping_rate=28)
        self.assertIsNone(quoting.house_rate_row(settings, 'OM', 'general', 'air'))
        self.assertIsNone(quoting.house_rate_row(settings, 'AE', 'beauty', 'air'))

    def test_every_legacy_field_exists_on_the_model(self):
        """Guards the hand-written map against a rename in models.py."""
        actual = {f.name for f in CompanySettings._meta.get_fields()}
        for field in quoting.SETTINGS_RATE_FIELDS.values():
            with self.subTest(field=field):
                self.assertIn(field, actual)


class RateDataTestCase(TestCase):
    """Shared fixtures for anything that needs real rows."""

    @classmethod
    def setUpTestData(cls):
        # Both are created by migration 0025; fetched rather than created so the
        # tests exercise the same rows the application uses.
        cls.uae = ShippingDestination.objects.get(code='AE')
        cls.ksa = ShippingDestination.objects.get(code='SA')
        cls.general = CargoType.objects.get(slug='general')
        cls.battery = CargoType.objects.get(slug='non-branded-battery')
        cls.beauty = CargoType.objects.get(slug='beauty')
        cls.company = ShippingCompany.objects.create(name='Falcon Air Cargo')


class SeedDataTests(RateDataTestCase):
    """What migration 0025 put in place."""

    def test_the_six_cargo_types_exist(self):
        slugs = set(CargoType.objects.values_list('slug', flat=True))
        self.assertEqual(slugs, {
            'general', 'branded', 'non-branded', 'branded-battery',
            'non-branded-battery', 'beauty'})

    def test_both_original_destinations_exist(self):
        self.assertEqual(
            set(ShippingDestination.objects.values_list('code', flat=True)),
            {'AE', 'SA'})


class LegacyColumnBridgeTests(RateDataTestCase):
    """
    Order pricing still reads the eight columns, so they must follow the rows.

    Without this the website would quote one number and the order screen would
    charge another, with nothing to say the two had diverged.
    """

    def test_saving_a_rate_mirrors_it_onto_the_legacy_column(self):
        ShippingRate.objects.create(
            company=self.company, destination=self.uae, cargo_type=self.general,
            method='air', rate=Decimal('24.50'))
        self.company.refresh_from_db()
        self.assertEqual(self.company.air_rate, Decimal('24.50'))

    def test_each_of_the_eight_lanes_maps_to_its_own_column(self):
        cases = [
            (self.uae, self.general, 'air', 'air_rate'),
            (self.uae, self.general, 'sea', 'sea_rate'),
            (self.ksa, self.general, 'air', 'ksa_air_rate'),
            (self.ksa, self.general, 'sea', 'ksa_sea_rate'),
            (self.uae, self.battery, 'air', 'nbb_air_rate'),
            (self.uae, self.battery, 'sea', 'nbb_sea_rate'),
            (self.ksa, self.battery, 'air', 'nbb_ksa_air_rate'),
            (self.ksa, self.battery, 'sea', 'nbb_ksa_sea_rate'),
        ]
        for index, (destination, cargo, method, column) in enumerate(cases, start=1):
            ShippingRate.objects.create(
                company=self.company, destination=destination, cargo_type=cargo,
                method=method, rate=Decimal(index))
        self.company.refresh_from_db()
        for index, (_, _, _, column) in enumerate(cases, start=1):
            with self.subTest(column=column):
                self.assertEqual(getattr(self.company, column), Decimal(index))

    def test_a_new_cargo_type_touches_no_legacy_column(self):
        """
        Beauty has no column, and must not be written into someone else's.

        This is the check that stops a new category quietly overwriting the
        general-cargo rate the order screen reads.
        """
        ShippingRate.objects.create(
            company=self.company, destination=self.uae, cargo_type=self.beauty,
            method='air', rate=Decimal('99'))
        self.company.refresh_from_db()
        self.assertEqual(self.company.air_rate, Decimal('0'))

    def test_removing_a_rate_clears_its_column(self):
        rate = ShippingRate.objects.create(
            company=self.company, destination=self.uae, cargo_type=self.general,
            method='air', rate=Decimal('24.50'))
        rate.delete()
        sync_legacy_rate_columns(self.company)
        self.company.refresh_from_db()
        self.assertEqual(self.company.air_rate, Decimal('0'))


class LaneRatesTests(RateDataTestCase):

    def test_only_rates_for_the_asked_lane_come_back(self):
        other = ShippingCompany.objects.create(name='Gulf Line')
        ShippingRate.objects.create(
            company=self.company, destination=self.uae, cargo_type=self.general,
            method='air', rate=Decimal('22'))
        ShippingRate.objects.create(
            company=other, destination=self.uae, cargo_type=self.general,
            method='air', rate=Decimal('26'))
        # Same companies, different lanes - none of these may appear.
        ShippingRate.objects.create(
            company=self.company, destination=self.ksa, cargo_type=self.general,
            method='air', rate=Decimal('30'))
        ShippingRate.objects.create(
            company=self.company, destination=self.uae, cargo_type=self.beauty,
            method='air', rate=Decimal('40'))
        ShippingRate.objects.create(
            company=self.company, destination=self.uae, cargo_type=self.general,
            method='sea', rate=Decimal('400'))

        rates = list(quoting.lane_rates('AE', 'general', 'air'))
        self.assertEqual(len(rates), 2)
        self.assertEqual({r.rate for r in rates}, {Decimal('22'), Decimal('26')})

    def test_an_inactive_destination_is_not_quoted(self):
        ShippingRate.objects.create(
            company=self.company, destination=self.ksa, cargo_type=self.general,
            method='air', rate=Decimal('30'))
        self.ksa.is_active = False
        self.ksa.save()
        self.assertEqual(list(quoting.lane_rates('SA', 'general', 'air')), [])


class RateSheetTests(RateDataTestCase):
    """Building the workbook a forwarder fills in, and reading it back."""

    def build(self, method='air'):
        workbook = rate_sheets.build_rate_request(self.company, method)
        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        return buffer

    def test_air_sheet_has_a_tab_per_destination_plus_instructions(self):
        workbook = load_workbook(self.build('air'))
        self.assertEqual(workbook.sheetnames,
                         ['Instructions', 'United Arab Emirates', 'Saudi Arabia'])

    def test_air_sheet_asks_for_the_divisor_and_sea_does_not(self):
        """
        The two documents differ, which is why they are two documents.

        Air needs a volumetric divisor and a minimum weight; sea needs a minimum
        CBM. One combined sheet would ask every recipient to ignore half the
        columns, which is how columns get filled in wrong.
        """
        air = load_workbook(self.build('air'))['United Arab Emirates']
        headers = [c.value for c in air[rate_sheets.ROW_HEADER]]
        self.assertIn('Volumetric Divisor', headers)
        self.assertIn('Rate per KG', headers)

        sea = load_workbook(self.build('sea'))['United Arab Emirates']
        headers = [c.value for c in sea[rate_sheets.ROW_HEADER]]
        self.assertNotIn('Volumetric Divisor', headers)
        self.assertIn('Rate per CBM', headers)

    def test_every_active_cargo_type_gets_a_row(self):
        sheet = load_workbook(self.build('air'))['United Arab Emirates']
        names = [sheet.cell(row=r, column=1).value
                 for r in range(rate_sheets.ROW_FIRST_RATE,
                                rate_sheets.ROW_FIRST_RATE + 6)]
        self.assertIn('General Goods', names)
        self.assertIn('Beauty & Cosmetics', names)
        self.assertIn('Non-Branded with Battery', names)

    def test_existing_rates_are_prefilled(self):
        """A forwarder reviewing last quarter only changes what moved."""
        ShippingRate.objects.create(
            company=self.company, destination=self.uae, cargo_type=self.general,
            method='air', rate=Decimal('22.50'), volumetric_divisor=Decimal('5000'))
        sheet = load_workbook(self.build('air'))['United Arab Emirates']
        row = self._row_for(sheet, 'General Goods')
        self.assertEqual(sheet.cell(row=row, column=2).value, 22.5)
        self.assertEqual(sheet.cell(row=row, column=4).value, 5000)

    def _row_for(self, sheet, cargo_name):
        for row in range(rate_sheets.ROW_FIRST_RATE, sheet.max_row + 1):
            if sheet.cell(row=row, column=1).value == cargo_name:
                return row
        self.fail(f'no row for {cargo_name}')

    # -- round trip ------------------------------------------------------

    def fill_and_import(self, method, values, mangle=None):
        """
        Fill in a generated sheet the way a forwarder would, then import it.

        Args:
            method (str): 'air' or 'sea'.
            values (dict): {cargo name: (rate, minimum, divisor)}.
            mangle (callable | None): given the sheet, to break it on purpose.
        """
        workbook = load_workbook(self.build(method))
        sheet = workbook['United Arab Emirates']
        for cargo_name, numbers in values.items():
            row = self._row_for(sheet, cargo_name)
            for offset, value in enumerate(numbers, start=2):
                if value is not None:
                    sheet.cell(row=row, column=offset, value=value)
        if mangle:
            mangle(sheet)
        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        return rate_sheets.apply_rate_request(self.company, method, buffer)

    def test_a_filled_air_sheet_imports(self):
        report = self.fill_and_import('air', {
            'General Goods': (22.5, 45, 5000),
            'Beauty & Cosmetics': (38, None, None),
        })
        self.assertEqual(len(report.created), 2)
        self.assertEqual(report.unmatched, [])

        rate = ShippingRate.objects.get(
            company=self.company, destination=self.uae,
            cargo_type=self.general, method='air')
        self.assertEqual(rate.rate, Decimal('22.50'))
        self.assertEqual(rate.minimum, Decimal('45'))
        self.assertEqual(rate.volumetric_divisor, Decimal('5000'))

    def test_a_filled_sea_sheet_imports_without_a_divisor_column(self):
        report = self.fill_and_import('sea', {'General Goods': (410, 1, None)})
        self.assertEqual(len(report.created), 1)
        rate = ShippingRate.objects.get(
            company=self.company, method='sea', cargo_type=self.general)
        self.assertEqual(rate.rate, Decimal('410'))
        self.assertEqual(rate.minimum, Decimal('1'))

    def test_a_blank_row_leaves_an_existing_rate_alone(self):
        """
        A forwarder quoting one lane has not withdrawn the others.

        Treating blanks as deletions would mean a partial reply wiped every rate
        they did not happen to retype.
        """
        ShippingRate.objects.create(
            company=self.company, destination=self.uae, cargo_type=self.general,
            method='air', rate=Decimal('22'))
        report = self.fill_and_import('air', {'Beauty & Cosmetics': (38, None, None)})
        self.assertGreater(report.skipped_blank, 0)
        self.assertEqual(
            ShippingRate.objects.get(company=self.company, cargo_type=self.general,
                                     method='air').rate,
            Decimal('22'))

    def test_reimporting_the_same_sheet_changes_nothing(self):
        values = {'General Goods': (22.5, None, None)}
        self.fill_and_import('air', values)
        second = self.fill_and_import('air', values)
        self.assertEqual(second.created, [])
        self.assertEqual(second.updated, [])
        self.assertGreater(second.unchanged, 0)
        self.assertEqual(
            ShippingRate.objects.filter(company=self.company, cargo_type=self.general,
                                        method='air').count(), 1)

    def test_a_changed_rate_is_reported_as_updated(self):
        self.fill_and_import('air', {'General Goods': (22, None, None)})
        report = self.fill_and_import('air', {'General Goods': (24, None, None)})
        self.assertEqual(report.created, [])
        self.assertEqual(len(report.updated), 1)

    def test_currency_text_and_thousands_separators_are_tolerated(self):
        """Forwarders type "AED 1,250.00" into a cell marked Rate."""
        report = self.fill_and_import('sea', {'General Goods': ('AED 1,250.00', None, None)})
        self.assertEqual(len(report.created), 1)
        self.assertEqual(
            ShippingRate.objects.get(company=self.company, method='sea',
                                     cargo_type=self.general).rate,
            Decimal('1250.00'))

    def test_not_applicable_text_is_read_as_not_quoted(self):
        report = self.fill_and_import('air', {'General Goods': ('n/a', None, None)})
        self.assertEqual(report.created, [])
        self.assertGreater(report.skipped_blank, 0)

    def test_a_renamed_tab_still_imports_via_the_ref_column(self):
        """
        Forwarders rename tabs. The ref column is what survives it.

        Matching on the sheet name would lose every rate in a file where someone
        typed "Dubai" over "United Arab Emirates".
        """
        def rename(sheet):
            sheet.title = 'Dubai Rates'

        report = self.fill_and_import('air', {'General Goods': (22, None, None)},
                                      mangle=rename)
        self.assertEqual(len(report.created), 1)
        self.assertEqual(report.unmatched, [])

    def test_a_deleted_ref_column_falls_back_to_the_header_and_row_label(self):
        """The ref column gets deleted. The sheet must still import."""
        def wipe_refs(sheet):
            ref_column = len(rate_sheets.columns_for('air'))
            for row in range(rate_sheets.ROW_FIRST_RATE, sheet.max_row + 1):
                # .value = None, NOT cell(..., value=None). openpyxl treats a
                # None argument as "no value supplied" and leaves the cell
                # alone, so the second form silently fails to clear anything -
                # which made an earlier version of this test pass without ever
                # removing a ref.
                sheet.cell(row=row, column=ref_column).value = None

        report = self.fill_and_import('air', {'General Goods': (22, None, None)},
                                      mangle=wipe_refs)
        self.assertEqual(len(report.created), 1)
        self.assertEqual(report.unmatched, [])

    def test_an_unrecognisable_row_is_reported_not_dropped(self):
        """
        A rate that failed to import looks exactly like one never quoted.

        Reporting it is the only thing that distinguishes the two.
        """
        def rewrite_label(sheet):
            row = self._row_for(sheet, 'General Goods')
            ref_column = len(rate_sheets.columns_for('air'))
            sheet.cell(row=row, column=1, value='Something Else Entirely')
            sheet.cell(row=row, column=ref_column).value = None

        report = self.fill_and_import('air', {'General Goods': (22, None, None)},
                                      mangle=rewrite_label)
        self.assertEqual(report.created, [])
        self.assertEqual(len(report.unmatched), 1)
        self.assertIn('Something Else Entirely', report.unmatched[0])

    def test_import_mirrors_onto_the_legacy_column(self):
        self.fill_and_import('air', {'General Goods': (23.75, None, None)})
        self.company.refresh_from_db()
        self.assertEqual(self.company.air_rate, Decimal('23.75'))


class NewCountryTests(RateDataTestCase):
    """
    Adding a country must be data entry, not a schema change.

    This is the whole reason rates became rows.
    """

    def test_a_new_country_gets_its_own_tab_and_quotes(self):
        oman = ShippingDestination.objects.create(
            name='Oman', code='OM', sort_order=30)

        workbook = rate_sheets.build_rate_request(self.company, 'air')
        self.assertIn('Oman', workbook.sheetnames)

        ShippingRate.objects.create(
            company=self.company, destination=oman, cargo_type=self.general,
            method='air', rate=Decimal('19'), volumetric_divisor=Decimal('6000'))

        quotes = quoting.best_quote(
            list(quoting.lane_rates('OM', 'general', 'air')), BULKY,
            CompanySettings.get_settings())
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0]['cost'], Decimal('304.00'))   # 16 kg x 19

    def test_a_new_cargo_type_gets_a_row_on_every_sheet(self):
        CargoType.objects.create(name='Fragile', slug='fragile', sort_order=70)
        sheet = rate_sheets.build_rate_request(
            self.company, 'sea')['United Arab Emirates']
        names = [sheet.cell(row=r, column=1).value
                 for r in range(rate_sheets.ROW_FIRST_RATE, sheet.max_row + 1)]
        self.assertIn('Fragile', names)


class SmtpProfileTests(TestCase):
    """
    Which mail server each kind of email is sent through.

    The three profiles exist so that order updates, security mail and marketing
    can come from different addresses — and, when the business grows into it,
    different servers. Until then one mailbox has to serve all three, and that
    is the case these tests are really about.
    """

    def setUp(self):
        self.settings = CompanySettings.get_settings()
        # One mailbox, on implicit SSL. Port 465 with TLS off is a completely
        # ordinary cPanel configuration and it is what exposed the bug below.
        self.settings.email_from_address = 'orders@mudassirllc.com'
        self.settings.email_smtp_host = 'mail.mudassirllc.com'
        self.settings.email_smtp_port = 465
        self.settings.email_smtp_user = 'orders@mudassirllc.com'
        self.settings.email_smtp_password = 'secret'
        self.settings.email_use_tls = False
        # security and news are left without a host of their own.
        self.settings.security_email_smtp_host = ''
        self.settings.news_email_smtp_host = ''
        self.settings.save()

    def test_one_mailbox_serves_all_three_profiles(self):
        """
        The whole connection is inherited, not a mixture of servers.

        This previously produced the right host and credentials on the WRONG
        port with the WRONG encryption: `security_email_smtp_port` defaults to
        587, and 587 is truthy, so the `or` fallback never fired; `use_tls` had
        no fallback at all. Every password reset and sign-in code failed, and
        `fail_silently=True` meant it failed invisibly.
        """
        for profile_name in ('order_status', 'security', 'news'):
            profile = self.settings.get_smtp_profile(profile_name)
            with self.subTest(profile=profile_name):
                self.assertEqual(profile['host'], 'mail.mudassirllc.com')
                self.assertEqual(profile['port'], 465)
                self.assertEqual(profile['user'], 'orders@mudassirllc.com')
                self.assertEqual(profile['password'], 'secret')
                self.assertIs(profile['use_tls'], False)

    def test_the_sender_address_stays_per_profile(self):
        """
        from_address is a label, not a connection setting.

        Inheriting the server must not collapse three senders into one — being
        able to send security mail from security@ while it travels over the
        order mailbox is the point of the feature.
        """
        self.settings.security_email_from_address = 'security@mudassirllc.com'
        self.settings.news_email_from_address = 'news@mudassirllc.com'
        self.settings.save()

        self.assertEqual(
            self.settings.get_smtp_profile('order_status')['from_address'],
            'orders@mudassirllc.com')
        self.assertEqual(
            self.settings.get_smtp_profile('security')['from_address'],
            'security@mudassirllc.com')
        self.assertEqual(
            self.settings.get_smtp_profile('news')['from_address'],
            'news@mudassirllc.com')

    def test_a_profile_with_its_own_host_is_left_alone(self):
        """A dedicated server for security mail must not inherit anything."""
        self.settings.security_email_smtp_host = 'smtp.sendgrid.net'
        self.settings.security_email_smtp_port = 587
        self.settings.security_email_smtp_user = 'apikey'
        self.settings.security_email_smtp_password = 'sg-key'
        self.settings.security_email_use_tls = True
        self.settings.save()

        profile = self.settings.get_smtp_profile('security')
        self.assertEqual(profile['host'], 'smtp.sendgrid.net')
        self.assertEqual(profile['port'], 587)
        self.assertEqual(profile['user'], 'apikey')
        self.assertIs(profile['use_tls'], True)

        # ...and the others are untouched by it.
        self.assertEqual(
            self.settings.get_smtp_profile('order_status')['host'],
            'mail.mudassirllc.com')

    def test_an_unknown_email_type_falls_back_to_order_status(self):
        self.assertEqual(
            self.settings.get_smtp_profile('nonsense'),
            self.settings.get_smtp_profile('order_status'))

    def test_nothing_configured_yields_an_empty_host(self):
        """
        An empty host is what the diagnostic command reports on.

        It must stay empty rather than acquiring a plausible-looking default —
        a default would make an unconfigured site look configured.
        """
        blank = CompanySettings.get_settings()
        blank.email_smtp_host = ''
        blank.security_email_smtp_host = ''
        blank.save()
        for name in ('order_status', 'security', 'news'):
            with self.subTest(profile=name):
                self.assertEqual(blank.get_smtp_profile(name)['host'], '')


class TypedEmailTests(TestCase):
    """The sender used for each kind of email, checked through Django's outbox."""

    def setUp(self):
        self.settings = CompanySettings.get_settings()
        self.settings.email_from_address = 'orders@mudassirllc.com'
        self.settings.security_email_from_address = 'security@mudassirllc.com'
        self.settings.news_email_from_address = 'news@mudassirllc.com'
        # No host anywhere, so the helper uses Django's configured backend —
        # which the test runner replaces with an in-memory outbox.
        self.settings.email_smtp_host = ''
        self.settings.security_email_smtp_host = ''
        self.settings.news_email_smtp_host = ''
        self.settings.save()

    def test_each_type_sends_from_its_own_address(self):
        from django.core import mail
        from utils.email_utils import send_typed_email

        expected = {
            'order_status': 'orders@mudassirllc.com',
            'security': 'security@mudassirllc.com',
            'news': 'news@mudassirllc.com',
        }
        for email_type, sender in expected.items():
            mail.outbox.clear()
            send_typed_email(email_type, 'Subject', 'Body', ['buyer@example.com'])
            with self.subTest(email_type=email_type):
                self.assertEqual(len(mail.outbox), 1)
                self.assertEqual(mail.outbox[0].from_email, sender)
                self.assertEqual(mail.outbox[0].to, ['buyer@example.com'])

    def test_failures_are_swallowed_by_default(self):
        """
        Documenting the behaviour that makes the diagnostic command necessary.

        A customer placing an order must not see a 500 because the mail server
        blinked — but the same default is why a completely unconfigured site
        looks healthy.
        """
        from utils.email_utils import send_typed_email

        sent = send_typed_email(
            'order_status', 'S', 'B', ['buyer@example.com'], from_email=None)
        self.assertIsInstance(sent, int)


class TeamMemberTests(TestCase):
    """
    The people shown in "Meet Our Team", and the rule that there are none by
    default.

    The section used to hardcode three colleagues over stock photographs. The
    behaviour worth protecting is not that the list renders — it is that an
    unconfigured site shows NOTHING rather than inventing staff.
    """

    def setUp(self):
        from django.contrib.auth.models import User

        self.staff = User.objects.create_user('teamadmin', 'ta@example.com', 'pw')
        profile = self.staff.profile
        profile.role = 'admin'
        profile.save()
        self.client.force_login(self.staff)

    def add(self, **overrides):
        payload = {'name': 'Mudassir Khan', 'role': 'Founder & CEO',
                   'sort_order': '0', 'is_active': '1'}
        payload.update(overrides)
        return self.client.post('/settings/team/add/', payload)

    # -- the empty state --------------------------------------------------

    def test_the_about_page_shows_no_team_section_when_none_are_added(self):
        """An empty About page is honest; three invented people are not."""
        response = self.client.get('/about/')
        self.assertNotContains(response, 'Meet Our Team')

    def test_the_section_appears_once_a_real_person_is_added(self):
        self.add()
        response = self.client.get('/about/')
        self.assertContains(response, 'Meet Our Team')
        self.assertContains(response, 'Mudassir Khan')

    def test_the_old_hardcoded_people_are_gone(self):
        """
        The placeholder colleagues must not come back.

        "Li Wei" and "Zhang Mei" were template literals with stock portraits.
        If either reappears in the markup, someone has re-hardcoded the section.
        """
        self.add()
        html = self.client.get('/about/').content.decode()
        self.assertNotIn('Li Wei', html)
        self.assertNotIn('Zhang Mei', html)
        self.assertNotIn('images/stock/team-office', html)

    # -- visibility -------------------------------------------------------

    def test_an_inactive_member_is_hidden_from_the_website(self):
        self.add(name='Retired Colleague', is_active='0')
        response = self.client.get('/about/')
        self.assertNotContains(response, 'Retired Colleague')

    def test_members_appear_in_sort_order(self):
        self.add(name='Second Person', sort_order='2')
        self.add(name='First Person', sort_order='1')
        html = self.client.get('/about/').content.decode()
        self.assertLess(html.index('First Person'), html.index('Second Person'))

    # -- editing ----------------------------------------------------------

    def test_editing_without_uploading_keeps_the_existing_photo(self):
        """
        Changing a job title must not silently delete somebody's photograph.

        The file input is empty on every edit, so a naive handler would
        overwrite the stored photo with nothing.
        """
        import io as _io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        buffer = _io.BytesIO()
        Image.new('RGB', (40, 40), (10, 20, 30)).save(buffer, 'PNG')
        buffer.seek(0)
        self.add(photo=SimpleUploadedFile('p.png', buffer.getvalue(), content_type='image/png'))

        member = TeamMember.objects.get(name='Mudassir Khan')
        original = member.photo.name
        self.assertTrue(original)

        self.client.post(f'/settings/team/{member.id}/save/',
                         {'name': 'Mudassir Khan', 'role': 'Managing Director',
                          'sort_order': '0', 'is_active': '1'})
        member.refresh_from_db()
        self.assertEqual(member.photo.name, original)
        self.assertEqual(member.role, 'Managing Director')

    def test_a_member_without_a_photo_gets_a_monogram(self):
        self.add(name='Li Wei')
        member = TeamMember.objects.get(name='Li Wei')
        self.assertEqual(member.initials, 'LW')
        self.assertContains(self.client.get('/about/'), 'team-photo-initials')

    def test_initials_never_blank(self):
        self.assertEqual(TeamMember(name='').initials, '?')
        self.assertEqual(TeamMember(name='Cher').initials, 'C')
        self.assertEqual(TeamMember(name='Ana Maria de Souza').initials, 'AM')

    # -- validation and access -------------------------------------------

    def test_a_name_and_role_are_both_required(self):
        self.assertFalse(self.add(name='').json()['success'])
        self.assertFalse(self.add(role='').json()['success'])
        self.assertEqual(TeamMember.objects.count(), 0)

    def test_deleting_removes_them_from_the_website(self):
        self.add()
        member = TeamMember.objects.get(name='Mudassir Khan')
        response = self.client.post(f'/settings/team/{member.id}/delete/')
        self.assertTrue(response.json()['success'])
        self.assertEqual(TeamMember.objects.count(), 0)
        self.assertNotContains(self.client.get('/about/'), 'Meet Our Team')

    def test_a_customer_cannot_manage_the_team(self):
        """The team list is a public claim about the business — staff only."""
        from django.contrib.auth.models import User

        customer = User.objects.create_user('buyer', 'buyer@example.com', 'pw')
        customer.profile.role = 'customer'
        customer.profile.save()
        self.client.force_login(customer)

        response = self.add()
        self.assertNotEqual(response.status_code, 200)
        self.assertEqual(TeamMember.objects.count(), 0)


class SettingsSaveSafetyTests(TestCase):
    """
    Saving settings must never silently zero a money field.

    Every rate here was once parsed with ``float()`` inside
    ``except ValueError: field = 0``. A blank input raises, so clearing a box -
    or saving a form that did not carry that box - wrote a zero over a live
    rate under a "saved successfully" banner.

    The damage was real in both directions: commission at 0 stops being charged
    on new orders, and a global shipping rate at 0 reads as "no published rate"
    to the quoting engine, so the public calculator stops answering for that
    route. Neither announces itself.
    """

    def setUp(self):
        from django.contrib.auth.models import User

        staff = User.objects.create_user('cfg', 'cfg@example.com', 'pw')
        profile = staff.profile
        profile.role = 'admin'
        profile.save()
        self.client.force_login(staff)

        self.settings = CompanySettings.get_settings()
        self.settings.air_shipping_rate = Decimal('28.50')
        self.settings.sea_shipping_rate = Decimal('480.00')
        self.settings.commission_percentage = Decimal('7.50')
        self.settings.exchange_rate = Decimal('1.95')
        self.settings.save()

    def reread(self):
        self.settings.refresh_from_db()
        return self.settings

    def test_a_blank_rate_keeps_the_stored_value(self):
        self.client.post('/settings/', {
            'company_name': 'Mudassir LLC', 'currency': 'AED',
            'air_shipping_rate': '', 'commission_percentage': '', 'exchange_rate': '',
        })
        settings = self.reread()
        self.assertEqual(settings.air_shipping_rate, Decimal('28.50'))
        self.assertEqual(settings.commission_percentage, Decimal('7.50'))
        self.assertEqual(settings.exchange_rate, Decimal('1.95'))

    def test_saving_the_rate_page_does_not_wipe_untouched_rates(self):
        """
        The worst form of the bug.

        This page exists to hold rates, and changing one of them destroyed the
        rest: every rate posts together, so the ones left blank were zeroed.
        """
        self.client.post('/settings/shipping-calculator/', {'sea_shipping_rate': '500'})
        settings = self.reread()
        self.assertEqual(settings.sea_shipping_rate, Decimal('500.00'))
        self.assertEqual(settings.air_shipping_rate, Decimal('28.50'))

    def test_a_real_edit_still_applies(self):
        """Refusing to write nonsense must not become refusing to write."""
        self.client.post('/settings/shipping-calculator/', {
            'air_shipping_rate': '31.25', 'sea_shipping_rate': '505'})
        settings = self.reread()
        self.assertEqual(settings.air_shipping_rate, Decimal('31.25'))
        self.assertEqual(settings.sea_shipping_rate, Decimal('505.00'))

    def test_unparseable_input_keeps_the_stored_value(self):
        self.client.post('/settings/shipping-calculator/', {'air_shipping_rate': 'twenty'})
        self.assertEqual(self.reread().air_shipping_rate, Decimal('28.50'))

    def test_a_rate_can_still_be_set_to_zero_deliberately(self):
        """
        Zero typed on purpose is a legitimate value.

        The fix must distinguish "the user cleared this" from "the user typed
        0", not refuse zero outright.
        """
        self.client.post('/settings/shipping-calculator/', {'air_shipping_rate': '0'})
        self.assertEqual(self.reread().air_shipping_rate, Decimal('0'))

    def test_decimals_are_stored_exactly_as_typed(self):
        """
        float() stored the nearest binary approximation of the number.

        At two decimal places that usually rounds back, but on a half-cent
        boundary it does not, and the exchange rate carries six.
        """
        self.client.post('/settings/', {
            'company_name': 'Mudassir LLC', 'currency': 'AED',
            'exchange_rate': '1.952500', 'commission_percentage': '2.675'})
        settings = self.reread()
        self.assertEqual(settings.exchange_rate, Decimal('1.952500'))
        self.assertEqual(settings.commission_percentage, Decimal('2.68'))


class SettingsPageTests(TestCase):
    """The settings page: saved passwords stay secret, and stay saved."""

    def setUp(self):
        from django.contrib.auth.models import User

        admin = User.objects.create_user('setadmin', 'sa@example.com', 'pw')
        admin.profile.role = 'admin'
        admin.profile.save()
        self.client.force_login(admin)

        settings = CompanySettings.get_settings()
        settings.email_smtp_password = 'hunter2-secret'
        settings.save()

    def save(self, **fields):
        payload = {'company_name': 'Mudassir LLC'}
        payload.update(fields)
        response = self.client.post('/settings/', payload)
        self.assertTrue(response.json()['success'], response.content)
        return CompanySettings.get_settings()

    def test_the_saved_password_is_not_printed_into_the_page(self):
        """Anyone with the page or its source open could read it."""
        html = self.client.get('/settings/').content.decode()
        self.assertNotIn('hunter2-secret', html)
        self.assertIn('Saved - leave blank to keep it', html)

    def test_saving_with_the_box_left_blank_keeps_the_password(self):
        """What the placeholder promises. It used to erase it."""
        settings = self.save(email_smtp_password='')
        self.assertEqual(settings.email_smtp_password, 'hunter2-secret')

    def test_typing_a_new_password_replaces_it(self):
        settings = self.save(email_smtp_password='new-pass')
        self.assertEqual(settings.email_smtp_password, 'new-pass')

    def test_the_remove_box_clears_it(self):
        settings = self.save(clear_email_smtp_password='1')
        self.assertEqual(settings.email_smtp_password, '')

    def test_the_page_has_search_and_a_save_bar(self):
        response = self.client.get('/settings/')
        self.assertContains(response, 'id="settingsSearch"')
        self.assertContains(response, 'id="settingsSaveBar"')
