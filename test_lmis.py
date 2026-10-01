# AndrewIDs: iizanyib, ualijuni, lirumvak
"""
Automated tests for the SwiftLink Logistics MIS, written with unittest.

Run them from this folder with:

    python -m unittest test_lmis.py -v

Every test class builds the objects it needs in setUp, and anything a test
writes to disk goes into a temporary folder that is deleted afterwards. The
tests therefore do not depend on the order in which they run, nor on files
left behind by an earlier test.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from billing import Invoice
from lmis import (DuplicateInvoiceError, DuplicateTrackingIDError,
                  InvoiceNotFoundError, LogisticsMIS, NotDeliveredError,
                  PersistenceError, ScanSequenceError, ShipmentNotFoundError)
from main import ClerkConsole, ask_number, load_system, parse_number
from shipments import (BulkFreight, ExpressParcel, FragileParcel, Shipment,
                       TrackedShipment)
from tracking import ScanEvent

BILLING_DATE = "2026-09-15"
CORPORATE_ACCOUNTS = ["Gasabo Pharmacy", "Uwera Trading", "Lake Glassworks",
                      "Nyagatare Feeds", "Muhanga Cement"]

# The worked examples from the specification: transport, levy, remote
# surcharge, discount, subtotal, VAT and total for each shipment.
WORKED_EXAMPLES = {
    "SL-1001": (6000.00, 360.00, 0.00, 0.00, 6360.00, 1144.80, 7504.80),
    "SL-2014": (21000.00, 1260.00, 0.00, 2100.00, 20160.00, 3628.80,
                23788.80),
    "SL-3120": (21500.00, 1290.00, 0.00, 2150.00, 20640.00, 3715.20,
                24355.20),
    "SL-4077": (64720.00, 3883.20, 0.00, 6472.00, 62131.20, 11183.62,
                73314.82),
    "SL-5003": (362000.00, 21720.00, 8000.00, 36200.00, 355520.00,
                63993.60, 419513.60),
    "SL-5004": (458000.00, 27480.00, 0.00, 45800.00, 439680.00, 79142.40,
                518822.40)
}
REVENUE_FOR_THE_PERIOD = 1067299.62

# The scans of SL-3120 from the sample output, deliberately out of order.
SL_3120_SCANS = [
    ("2026-09-14 16:40", "Huye Depot", "out for delivery"),
    ("2026-09-14 08:30", "Kigali Depot", "received"),
    ("2026-09-14 18:15", "Huye", "delivered"),
    ("2026-09-14 12:05", "Muhanga Hub", "in transit")
]


def make_worked_example_shipments():
    """
    Builds fresh copies of the six shipments of the worked examples.
    Parameters: none.
    Returns: dict mapping tracking id to Shipment.
    """
    shipments = [
        Shipment("SL-1001", "Keza Uwase", "A. Niyonsaba", "Kigali", 4, 1500),
        TrackedShipment("SL-2014", "Gasabo Pharmacy", "D. Habimana",
                        "Musanze", 6, 1500, 400000, 0.03),
        ExpressParcel("SL-3120", "Uwera Trading", "J. Mugisha", "Huye", 2.5,
                      1800, 250000, 0.02, "in transit", 12),
        FragileParcel("SL-4077", "Lake Glassworks", "C. Ingabire", "Rubavu",
                      8, 1600, 900000, 0.05, "received", "glass", 5000),
        BulkFreight("SL-5003", "Nyagatare Feeds", "Depot 3", "Nyagatare",
                    320, 900, 6, 14),
        BulkFreight("SL-5004", "Muhanga Cement", "Depot 7", "Muhanga", 500,
                    900, 4, 12)
    ]
    return {shipment.get_tracking_id(): shipment for shipment in shipments}


def make_worked_example_system(with_invoices=True):
    """
    Builds a system holding the six worked-example shipments, the scans of
    SL-3120 and, optionally, all six invoices.
    Parameters: with_invoices : bool.
    Returns: LogisticsMIS.
    """
    system = LogisticsMIS(corporate_accounts=CORPORATE_ACCOUNTS)
    for shipment in make_worked_example_shipments().values():
        system.add_shipment(shipment)
    for timestamp, location, status in SL_3120_SCANS:
        system.record_scan("SL-3120", timestamp, location, status)
    system.record_scan("SL-2014", "2026-09-14 07:45", "Kigali Depot",
                       "received")
    if with_invoices:
        system.raise_all_invoices(BILLING_DATE)
    return system


def run_console(console, answers):
    """
    Runs the menu interface with scripted keyboard answers.
    Parameters: console : ClerkConsole, answers : list of str.
    Returns: str, everything the interface printed.
    """
    printed = io.StringIO()
    with mock.patch("builtins.input", side_effect=answers), \
            contextlib.redirect_stdout(printed):
        console.run()
    return printed.getvalue()


class FixedPriceShipment(Shipment):
    """A test double whose calculate_cost() returns a known figure, used to
    show that an invoice takes its transport charge from the shipment."""

    def calculate_cost(self):
        """
        Returns a fixed price that no billing rule could produce by itself.
        Parameters: none.
        Returns: float.
        """
        return 1234.56


class TestPricing(unittest.TestCase):
    """One test per shipment class, including both bulk freight branches."""

    def setUp(self):
        """Builds the six worked-example shipments."""
        self.shipments = make_worked_example_shipments()

    def test_plain_shipment_is_weight_times_rate(self):
        """A Shipment costs weight x base rate: 4 kg x 1,500."""
        self.assertAlmostEqual(self.shipments["SL-1001"].calculate_cost(),
                               6000.00, places=2)

    def test_tracked_shipment_adds_insurance_premium(self):
        """A TrackedShipment adds 3% of 400,000 to 6 kg x 1,500."""
        self.assertAlmostEqual(self.shipments["SL-2014"].calculate_cost(),
                               21000.00, places=2)

    def test_cost_includes_priority_fee(self):
        """An ExpressParcel adds the 12-hour priority fee, as in the spec."""
        self.assertAlmostEqual(self.shipments["SL-3120"].calculate_cost(),
                               21500.00, places=2)

    def test_fragile_surcharge_is_on_transport_only(self):
        """The 15% handling surcharge excludes the insurance premium."""
        parcel = self.shipments["SL-4077"]
        self.assertAlmostEqual(parcel.calculate_cost(), 64720.00, places=2)
        # 15% of the tracked cost would have given a larger, wrong figure.
        wrong = (8 * 1600 + 0.05 * 900000) * 1.15 + 5000
        self.assertNotAlmostEqual(parcel.calculate_cost(), wrong, places=2)

    def test_bulk_freight_priced_on_volume_when_it_is_greater(self):
        """SL-5003: 14 m3 x 25,000 beats 320 kg x 900."""
        freight = self.shipments["SL-5003"]
        self.assertGreater(freight.get_volume_m3() * 25000,
                           freight.get_weight_kg() * 900)
        self.assertAlmostEqual(freight.calculate_cost(), 362000.00, places=2)

    def test_bulk_freight_priced_on_weight_when_it_is_greater(self):
        """SL-5004: 500 kg x 900 beats 12 m3 x 25,000."""
        freight = self.shipments["SL-5004"]
        self.assertGreater(freight.get_weight_kg() * 900,
                           freight.get_volume_m3() * 25000)
        self.assertAlmostEqual(freight.calculate_cost(), 458000.00, places=2)

    def test_one_loop_prices_a_mixed_collection(self):
        """Polymorphism: one call prices all five classes correctly."""
        total = sum(shipment.calculate_cost()
                    for shipment in self.shipments.values())
        self.assertAlmostEqual(total, 933220.00, places=2)


class TestValidation(unittest.TestCase):
    """A bad value raises ValueError and leaves the object unchanged."""

    def setUp(self):
        """Builds one object of each class that the tests try to corrupt."""
        self.parcel = ExpressParcel("SL-3120", "Uwera Trading", "J. Mugisha",
                                    "Huye", 2.5, 1800, 250000, 0.02,
                                    "in transit", 12)
        self.tracked = TrackedShipment("SL-2014", "Gasabo Pharmacy",
                                       "D. Habimana", "Musanze", 6, 1500,
                                       400000, 0.03)
        self.freight = BulkFreight("SL-5003", "Nyagatare Feeds", "Depot 3",
                                   "Nyagatare", 320, 900, 6, 14)

    def test_invalid_guarantee_is_rejected(self):
        """A 36-hour guarantee is refused and the price does not move."""
        with self.assertRaises(ValueError):
            self.parcel.set_guaranteed_hours(36)
        self.assertEqual(self.parcel.get_guaranteed_hours(), 12)
        self.assertAlmostEqual(self.parcel.calculate_cost(), 21500.00,
                               places=2)

    def test_insurance_rate_above_five_percent_is_rejected(self):
        """An insurance rate of 0.20 is refused."""
        with self.assertRaises(ValueError):
            self.tracked.set_insurance_rate(0.20)
        self.assertEqual(self.tracked.get_insurance_rate(), 0.03)

    def test_pallet_count_outside_one_to_twenty_is_rejected(self):
        """Forty pallets, zero pallets and half a pallet are all refused."""
        for bad_count in (40, 0, 2.5):
            with self.subTest(pallet_count=bad_count):
                with self.assertRaises(ValueError):
                    self.freight.set_pallet_count(bad_count)
        self.assertEqual(self.freight.get_pallet_count(), 6)

    def test_malformed_tracking_id_is_rejected_and_not_counted(self):
        """A shipment with a bad id is never built, nor counted."""
        count_before = Shipment.get_shipment_count()
        with self.assertRaises(ValueError):
            Shipment("SL-99", "Sender", "Recipient", "Kigali", 4, 1500)
        self.assertEqual(Shipment.get_shipment_count(), count_before)

    def test_letters_or_nan_where_a_number_is_expected_are_rejected(self):
        """Text, NaN and True are not weights, whatever Python allows."""
        for bad_weight in ("abc", float("nan"), True):
            with self.subTest(weight=bad_weight):
                with self.assertRaises(ValueError):
                    self.parcel.set_weight_kg(bad_weight)
        self.assertEqual(self.parcel.get_weight_kg(), 2.5)

    def test_blank_destination_is_rejected(self):
        """A destination drives the remote surcharge, so it cannot be blank."""
        with self.assertRaises(ValueError):
            self.parcel.set_destination_city("   ")
        self.assertEqual(self.parcel.get_destination_city(), "Huye")

    def test_scan_timestamp_must_match_the_format(self):
        """A day-first date is not a YYYY-MM-DD HH:MM timestamp."""
        with self.assertRaises(ValueError) as context:
            ScanEvent("SL-3120", "14/09/2026", "Huye Depot", "received")
        self.assertIn("YYYY-MM-DD HH:MM", str(context.exception))

    def test_scan_status_must_be_one_of_the_four(self):
        """'lost' is not a permitted scan status; any case of one is."""
        with self.assertRaises(ValueError):
            ScanEvent("SL-3120", "2026-09-14 08:30", "Huye Depot", "lost")
        scan = ScanEvent("SL-3120", "2026-9-14 8:30", "Huye", "In Transit")
        self.assertEqual(scan.get_status(), "in transit")
        self.assertEqual(scan.get_timestamp(), "2026-09-14 08:30")

    def test_invoice_date_must_be_a_real_date(self):
        """An invoice cannot be issued on the 40th of the 13th month."""
        with self.assertRaises(ValueError):
            Invoice("SL-3120", "Uwera Trading", "2026-13-40", 21500, False,
                    True)


class TestConsignmentManagement(unittest.TestCase):
    """Adding, finding, updating and removing shipments."""

    def setUp(self):
        """Builds a system holding the six worked-example shipments."""
        self.system = make_worked_example_system(with_invoices=False)

    def test_duplicate_tracking_id_is_refused(self):
        """A second SL-3120 is refused and the first one is kept."""
        original = self.system.find_shipment("SL-3120")
        impostor = Shipment("SL-3120", "Someone Else", "Nobody", "Kigali", 1,
                            1000)
        with self.assertRaises(DuplicateTrackingIDError):
            self.system.add_shipment(impostor)
        self.assertIs(self.system.find_shipment("SL-3120"), original)
        self.assertEqual(len(self.system), 6)

    def test_unknown_tracking_id_is_refused(self):
        """Looking up an id that is not registered raises, not None."""
        with self.assertRaises(ShipmentNotFoundError):
            self.system.find_shipment("SL-9999")

    def test_lookup_returns_the_registered_object(self):
        """Lookup returns the very object that was registered."""
        freight = BulkFreight("SL-6001", "Kivu Coffee", "Depot 2", "Rusizi",
                              200, 900, 2, 5)
        self.system.add_shipment(freight)
        self.assertIs(self.system.find_shipment("SL-6001"), freight)
        self.assertIn("SL-6001", self.system)

    def test_update_changes_details_through_the_setters(self):
        """Valid corrections are applied and change the price."""
        self.system.update_shipment("SL-1001", weight_kg=5,
                                    recipient_name="A. Uwimana")
        shipment = self.system.find_shipment("SL-1001")
        self.assertEqual(shipment.get_recipient_name(), "A. Uwimana")
        self.assertAlmostEqual(shipment.calculate_cost(), 7500.00, places=2)

    def test_failed_update_changes_nothing(self):
        """If one value is refused, the others are not applied either."""
        with self.assertRaises(ValueError):
            self.system.update_shipment("SL-2014", destination_city="Rusizi",
                                        weight_kg=5000)
        shipment = self.system.find_shipment("SL-2014")
        self.assertEqual(shipment.get_destination_city(), "Musanze")
        self.assertEqual(shipment.get_weight_kg(), 6)

    def test_identity_and_status_are_not_editable(self):
        """The tracking id never changes; the status follows the scans."""
        for field_name in ("tracking_id", "current_status"):
            with self.subTest(field=field_name):
                with self.assertRaises(ValueError):
                    self.system.update_shipment("SL-2014",
                                                **{field_name: "x"})

    def test_update_reissues_an_existing_invoice(self):
        """Redirecting SL-3120 to a remote district re-prices its invoice
        under the original issue date."""
        self.system.raise_invoice("SL-3120", BILLING_DATE)
        self.system.update_shipment("SL-3120", destination_city="Rusizi")
        invoice = self.system.get_invoice("SL-3120")
        self.assertAlmostEqual(invoice.get_remote_surcharge(), 8000.00,
                               places=2)
        self.assertEqual(invoice.get_issue_date(), BILLING_DATE)

    def test_remove_takes_its_scans_and_invoice_with_it(self):
        """Removal cascades, and the id can then be reused cleanly."""
        self.system.raise_invoice("SL-3120", BILLING_DATE)
        shipment, scans, invoice = self.system.remove_shipment("SL-3120")
        self.assertEqual(shipment.get_tracking_id(), "SL-3120")
        self.assertEqual(len(scans), 4)
        self.assertIsNotNone(invoice)
        self.assertNotIn("SL-3120", self.system)
        self.assertEqual(self.system.get_scans_on("2026-09-14")[0]
                         .get_tracking_id(), "SL-2014")
        self.assertEqual(self.system.get_total_revenue(), 0)

        # A new shipment with the old id starts with a clean history.
        self.system.add_shipment(Shipment("SL-3120", "New Sender", "R. Ndoli",
                                          "Huye", 1, 1500))
        self.assertEqual(self.system.get_scan_history("SL-3120"), [])
        with self.assertRaises(InvoiceNotFoundError):
            self.system.get_invoice("SL-3120")

    def test_removing_an_unknown_shipment_is_refused(self):
        """Removing an id that is not registered raises."""
        with self.assertRaises(ShipmentNotFoundError):
            self.system.remove_shipment("SL-9999")


class TestScanTracking(unittest.TestCase):
    """Scans are stored in order, and journey figures are correct."""

    def setUp(self):
        """Builds a system whose SL-3120 scans were recorded out of order."""
        self.system = make_worked_example_system(with_invoices=False)

    def test_scans_are_returned_in_chronological_order(self):
        """History comes back sorted whatever order it was recorded in."""
        history = self.system.get_scan_history("SL-3120")
        self.assertEqual([scan.get_timestamp() for scan in history],
                         ["2026-09-14 08:30", "2026-09-14 12:05",
                          "2026-09-14 16:40", "2026-09-14 18:15"])
        self.assertEqual(history[-1].get_status(), "delivered")

    def test_transit_time_runs_from_first_scan_to_delivery(self):
        """08:30 to 18:15 is 9.75 hours, as in the sample output."""
        self.assertAlmostEqual(self.system.get_transit_hours("SL-3120"),
                               9.75, places=2)

    def test_scan_for_an_unknown_tracking_id_is_refused(self):
        """A scan cannot be recorded against an id that is not registered."""
        with self.assertRaises(ShipmentNotFoundError):
            self.system.record_scan("SL-9999", "2026-09-14 09:00",
                                    "Kigali Depot", "received")
        self.assertEqual(len(self.system.get_all_scans()), 5)

    def test_undelivered_shipment_reports_no_transit_time(self):
        """No figure is given before delivery, scanned or not."""
        for tracking_id in ("SL-2014", "SL-1001"):
            with self.subTest(tracking_id=tracking_id):
                with self.assertRaises(NotDeliveredError):
                    self.system.get_transit_hours(tracking_id)
                self.assertFalse(self.system.is_delivered(tracking_id))

    def test_network_scans_for_one_day(self):
        """Only that day's scans, across shipments, in time order."""
        self.system.record_scan("SL-1001", "2026-09-15 09:10",
                                "Kigali Depot", "received")
        on_14th = self.system.get_scans_on("2026-09-14")
        self.assertEqual(len(on_14th), 5)
        self.assertEqual(on_14th[0].get_tracking_id(), "SL-2014")
        self.assertEqual(len(self.system.get_scans_on("2026-09-15")), 1)
        with self.assertRaises(ValueError):
            self.system.get_scans_on("15/09/2026")

    def test_scans_after_delivery_are_refused(self):
        """Delivery closes the journey: no later scan, no second delivery."""
        with self.assertRaises(ScanSequenceError):
            self.system.record_scan("SL-3120", "2026-09-15 09:00",
                                    "Huye Depot", "in transit")
        with self.assertRaises(ScanSequenceError):
            self.system.record_scan("SL-3120", "2026-09-14 19:00", "Huye",
                                    "delivered")
        self.assertEqual(len(self.system.get_scan_history("SL-3120")), 4)

    def test_delivery_must_be_the_last_scan(self):
        """A delivery dated before an existing scan is refused, but an
        earlier scan that arrives late is accepted."""
        with self.assertRaises(ScanSequenceError):
            self.system.record_scan("SL-2014", "2026-09-14 07:00", "Musanze",
                                    "delivered")
        self.system.record_scan("SL-3120", "2026-09-14 10:00", "Kamonyi Hub",
                                "in transit")
        self.assertEqual(len(self.system.get_scan_history("SL-3120")), 5)

    def test_tracked_status_follows_the_latest_scan(self):
        """SL-3120 was registered in transit; its scans say delivered."""
        parcel = self.system.find_shipment("SL-3120")
        self.assertEqual(parcel.get_current_status(), "delivered")
        self.assertEqual(self.system.get_current_location("SL-3120"), "Huye")
        self.assertEqual(self.system.get_current_status("SL-1001"),
                         LogisticsMIS.NOT_SCANNED)

    def test_guarantee_compliance_verdicts(self):
        """Delivered in time is MET; delivered late, or undelivered past
        the guarantee, is MISSED; undelivered within it is PENDING."""
        late = ExpressParcel("SL-7001", "Uwera Trading", "K. Aline", "Huye",
                             1, 1800, 1000, 0.01, "received", 6)
        waiting = ExpressParcel("SL-7002", "Uwera Trading", "K. Aline",
                                "Huye", 1, 1800, 1000, 0.01, "received", 24)
        overdue = ExpressParcel("SL-7003", "Uwera Trading", "K. Aline",
                                "Huye", 1, 1800, 1000, 0.01, "received", 6)
        for parcel in (late, waiting, overdue):
            self.system.add_shipment(parcel)
        self.system.record_scan("SL-7001", "2026-09-14 08:00", "Kigali",
                                "received")
        self.system.record_scan("SL-7001", "2026-09-14 16:00", "Huye",
                                "delivered")
        self.system.record_scan("SL-7002", "2026-09-14 08:00", "Kigali",
                                "received")
        self.system.record_scan("SL-7003", "2026-09-14 08:00", "Kigali",
                                "received")
        self.system.record_scan("SL-7003", "2026-09-14 18:00", "Muhanga Hub",
                                "in transit")

        verdicts = {result["tracking_id"]: result["verdict"]
                    for result in self.system.get_guarantee_compliance()}
        self.assertEqual(verdicts, {"SL-3120": "MET", "SL-7001": "MISSED",
                                    "SL-7002": "PENDING",
                                    "SL-7003": "MISSED"})


class TestInvoicing(unittest.TestCase):
    """Invoices follow the billing rules and match the worked examples."""

    def setUp(self):
        """Builds the worked-example system with all six invoices raised."""
        self.system = make_worked_example_system(with_invoices=True)

    def test_full_invoice_breakdown_matches_worked_example(self):
        """Every component of SL-3120 matches the worked example."""
        invoice = self.system.get_invoice("SL-3120")
        figures = (invoice.get_transport_charge(), invoice.get_fuel_levy(),
                   invoice.get_remote_surcharge(),
                   invoice.get_corporate_discount(), invoice.get_subtotal(),
                   invoice.get_vat(), invoice.get_total())
        for actual, expected in zip(figures, WORKED_EXAMPLES["SL-3120"]):
            self.assertAlmostEqual(actual, expected, places=2)

    def test_every_invoice_matches_its_worked_example(self):
        """All six invoices match, including the half-cent VAT of SL-4077."""
        for tracking_id, expected in WORKED_EXAMPLES.items():
            invoice = self.system.get_invoice(tracking_id)
            with self.subTest(tracking_id=tracking_id):
                self.assertAlmostEqual(invoice.get_vat(), expected[5],
                                       places=2)
                self.assertAlmostEqual(invoice.get_total(), expected[6],
                                       places=2)

    def test_revenue_for_the_period(self):
        """The six invoices add up to 1,067,299.62."""
        self.assertAlmostEqual(self.system.get_total_revenue(),
                               REVENUE_FOR_THE_PERIOD, places=2)

    def test_only_the_remote_district_pays_the_surcharge(self):
        """SL-5003 goes to Nyagatare and pays 8,000; the rest pay none."""
        for invoice in self.system.get_invoices():
            expected = 8000.0 if invoice.get_tracking_id() == "SL-5003" else 0
            with self.subTest(tracking_id=invoice.get_tracking_id()):
                self.assertEqual(invoice.get_remote_surcharge(), expected)

    def test_private_sender_gets_no_discount(self):
        """SL-1001 is sent by a private individual."""
        invoice = self.system.get_invoice("SL-1001")
        self.assertFalse(invoice.is_corporate())
        self.assertEqual(invoice.get_corporate_discount(), 0)

    def test_transport_charge_comes_from_calculate_cost(self):
        """The invoice uses whatever the shipment's own rule returns."""
        shipment = FixedPriceShipment("SL-8001", "Walk-in", "B. Mutoni",
                                      "Kigali", 1, 1000)
        invoice = Invoice.for_shipment(shipment, False, False, BILLING_DATE)
        self.assertAlmostEqual(invoice.get_transport_charge(), 1234.56,
                               places=2)

    def test_invoicing_twice_is_refused_unless_reissued(self):
        """A second invoice needs reissue=True."""
        with self.assertRaises(DuplicateInvoiceError):
            self.system.raise_invoice("SL-3120")
        reissued = self.system.raise_invoice("SL-3120", "2026-09-20",
                                             reissue=True)
        self.assertEqual(reissued.get_issue_date(), "2026-09-20")

    def test_raise_all_leaves_existing_invoices_alone(self):
        """Running it again raises nothing and moves no revenue."""
        self.assertEqual(self.system.raise_all_invoices("2026-10-01"), [])
        self.assertEqual(self.system.get_invoice("SL-5004").get_issue_date(),
                         BILLING_DATE)

    def test_policy_changes_without_editing_the_classes(self):
        """Rubavu made remote and Muhanga Cement no longer corporate,
        through the system's methods alone."""
        self.system.add_remote_district("rubavu")
        self.system.remove_corporate_account("Muhanga Cement")
        fragile = self.system.raise_invoice("SL-4077", reissue=True)
        freight = self.system.raise_invoice("SL-5004", reissue=True)
        self.assertEqual(fragile.get_remote_surcharge(), 8000.0)
        self.assertEqual(freight.get_corporate_discount(), 0)
        with self.assertRaises(ValueError):
            self.system.add_remote_district("Nyagatare")

    def test_invoice_text_shows_each_component(self):
        """The printed invoice lets the customer follow the arithmetic."""
        text = str(self.system.get_invoice("SL-3120"))
        for expected in ("Transport charge", "21,500.00", "Fuel levy (6%)",
                         "Corporate discount (10%)", "-2,150.00",
                         "VAT (18%)", "3,715.20", "24,355.20"):
            self.assertIn(expected, text)


class TestReports(unittest.TestCase):
    """The four reports carry the right figures in readable form."""

    def setUp(self):
        """Builds the worked-example system with all six invoices raised."""
        self.system = make_worked_example_system(with_invoices=True)

    def test_register_lists_service_destination_and_status(self):
        """Every shipment appears with its class, city and status."""
        register = self.system.format_register()
        self.assertIn("(6 shipments)", register)
        for expected in ("SL-1001", "Shipment", "not scanned yet",
                         "ExpressParcel", "Huye", "delivered",
                         "BulkFreight", "Nyagatare", "933,220.00"):
            self.assertIn(expected, register)

    def test_scan_summary_counts_scans_and_location(self):
        """SL-3120 has four scans and is at Huye."""
        summary = self.system.format_scan_summary()
        self.assertIn("5 scans across 6 shipments", summary)
        line = next(row for row in summary.splitlines() if "SL-3120" in row)
        self.assertIn(" 4 ", line)
        self.assertIn("Huye", line)

    def test_revenue_summary_totals_by_component(self):
        """September 2026 adds up; October has nothing."""
        september = self.system.get_revenue_summary("2026-09")
        self.assertEqual(september["invoice_count"], 6)
        self.assertAlmostEqual(september["transport_charge"], 933220.00,
                               places=2)
        self.assertAlmostEqual(september["corporate_discount"], 92722.00,
                               places=2)
        self.assertAlmostEqual(september["vat"], 162808.42, places=2)
        self.assertAlmostEqual(september["total"], REVENUE_FOR_THE_PERIOD,
                               places=2)
        october = self.system.get_revenue_summary("2026-10")
        self.assertEqual((october["invoice_count"], october["total"]),
                         (0, 0))
        self.assertIn("1,067,299.62",
                      self.system.format_revenue_summary("2026-09"))

    def test_guarantee_report_is_readable(self):
        """The report names the parcel, both times and the verdict."""
        report = self.system.format_guarantee_report()
        for expected in ("SL-3120", "guaranteed 12 h", "actual 9.75 h",
                         "MET"):
            self.assertIn(expected, report)


class TestPersistence(unittest.TestCase):
    """Saving and loading preserve the system; waybills are written."""

    def setUp(self):
        """Builds the worked-example system and a private temporary folder."""
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.data_file = os.path.join(self.folder, "data", "lmis_data.json")
        self.system = make_worked_example_system(with_invoices=True)

    def reload(self):
        """
        Saves the system and loads it back into a new one.
        Parameters: none.
        Returns: LogisticsMIS, the reloaded system.
        """
        self.system.save(self.data_file)
        reloaded = LogisticsMIS()
        self.assertEqual(reloaded.load(self.data_file), [])
        return reloaded

    def test_round_trip_preserves_the_revenue_total(self):
        """The reloaded system reports the same revenue, and re-pricing its
        shipments from scratch gives the same figure again."""
        reloaded = self.reload()
        self.assertAlmostEqual(reloaded.get_total_revenue(),
                               REVENUE_FOR_THE_PERIOD, places=2)
        for shipment in reloaded.get_shipments():
            reloaded.raise_invoice(shipment.get_tracking_id(), BILLING_DATE,
                                   reissue=True)
        self.assertAlmostEqual(reloaded.get_total_revenue(),
                               REVENUE_FOR_THE_PERIOD, places=2)

    def test_type_key_rebuilds_the_right_classes(self):
        """Each shipment comes back as its own class."""
        reloaded = self.reload()
        classes = [type(shipment) for shipment in reloaded.get_shipments()]
        self.assertEqual(classes, [Shipment, TrackedShipment, ExpressParcel,
                                   FragileParcel, BulkFreight, BulkFreight])

    def test_round_trip_preserves_scans_policy_and_invoices(self):
        """Scans, transit time, policy and invoice details all survive."""
        reloaded = self.reload()
        self.assertEqual(
            [scan.to_dict() for scan in reloaded.get_all_scans()],
            [scan.to_dict() for scan in self.system.get_all_scans()])
        self.assertAlmostEqual(reloaded.get_transit_hours("SL-3120"), 9.75,
                               places=2)
        self.assertEqual(reloaded.get_corporate_accounts(),
                         self.system.get_corporate_accounts())
        self.assertEqual(reloaded.get_invoice("SL-5003").to_dict(),
                         self.system.get_invoice("SL-5003").to_dict())

    def test_new_classes_carry_a_type_key(self):
        """ScanEvent and Invoice extend the Assignment 1 type-key approach,
        and a record of the wrong type is refused."""
        scan = self.system.get_scan_history("SL-3120")[0]
        invoice = self.system.get_invoice("SL-3120")
        self.assertEqual(scan.to_dict()["type"], "ScanEvent")
        self.assertEqual(invoice.to_dict()["type"], "Invoice")
        self.assertEqual(ScanEvent.from_dict(scan.to_dict()).to_dict(),
                         scan.to_dict())
        self.assertAlmostEqual(
            Invoice.from_dict(invoice.to_dict()).get_total(), 24355.20,
            places=2)
        with self.assertRaises(ValueError):
            Invoice.from_dict(scan.to_dict())

    def test_one_waybill_per_shipment(self):
        """Six files named TRACKING_ID.txt, each with details, scans and
        the invoice breakdown."""
        waybill_folder = os.path.join(self.folder, "waybills")
        paths = self.system.write_all_waybills(waybill_folder)
        self.assertEqual(sorted(os.listdir(waybill_folder)),
                         [f"{tracking_id}.txt"
                          for tracking_id in sorted(WORKED_EXAMPLES)])
        self.assertEqual(len(paths), 6)
        with open(os.path.join(waybill_folder, "SL-3120.txt"),
                  encoding="utf-8") as waybill:
            text = waybill.read()
        for expected in ("WAYBILL SL-3120", "ExpressParcel", "Muhanga Hub",
                         "Transit time: 9.75 hours", "Total payable",
                         "24,355.20"):
            self.assertIn(expected, text)


class TestFailureHandling(unittest.TestCase):
    """Missing, malformed and damaged files never crash the system."""

    def setUp(self):
        """Builds a small system and a private temporary folder."""
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.system = make_worked_example_system(with_invoices=True)

    def write_file(self, name, content):
        """
        Writes a text file into the temporary folder.
        Parameters: name : str, content : str.
        Returns: str, the path written.
        """
        path = os.path.join(self.folder, name)
        with open(path, "w", encoding="utf-8") as file:
            file.write(content)
        return path

    def test_loading_a_missing_file_does_not_crash(self):
        """A clear, catchable error; the system keeps working."""
        missing = os.path.join(self.folder, "no_such_file.json")
        with self.assertRaises(PersistenceError) as context:
            self.system.load(missing)
        self.assertIn("no saved data file", str(context.exception))
        self.assertEqual(len(self.system), 6)
        self.system.record_scan("SL-2014", "2026-09-14 13:20", "Musanze Hub",
                                "in transit")

    def test_loading_malformed_json_does_not_crash(self):
        """Broken JSON is reported and the current state is kept."""
        path = self.write_file("broken.json", '{"shipments": [ {"type": ')
        with self.assertRaises(PersistenceError) as context:
            self.system.load(path)
        self.assertIn("not valid JSON", str(context.exception))
        self.assertAlmostEqual(self.system.get_total_revenue(),
                               REVENUE_FOR_THE_PERIOD, places=2)

    def test_loading_json_that_is_not_lmis_data_is_refused(self):
        """Valid JSON of the wrong shape is refused as a whole."""
        path = self.write_file("list.json", "[1, 2, 3]")
        with self.assertRaises(PersistenceError):
            self.system.load(path)
        self.assertEqual(len(self.system), 6)

    def test_damaged_record_is_skipped_with_a_warning(self):
        """One bad shipment costs only itself and the scans that refer to
        it; everything else loads."""
        data = self.system.to_dict()
        data["shipments"][2]["weight_kg"] = "heavy"
        path = self.write_file("damaged.json", json.dumps(data))
        reloaded = LogisticsMIS()
        warnings = reloaded.load(path)
        self.assertEqual(len(reloaded), 5)
        self.assertNotIn("SL-3120", reloaded)
        self.assertTrue(any("shipment record 3" in warning
                            for warning in warnings))
        self.assertTrue(any("SL-3120" in warning for warning in warnings))

    def test_driver_starts_empty_when_the_data_file_is_missing(self):
        """The driver turns the failure into advice and an empty system."""
        system, messages = load_system(os.path.join(self.folder, "x.json"))
        self.assertEqual(len(system), 0)
        self.assertIn("Starting with an empty system", " ".join(messages))

    def test_unwritable_waybill_folder_raises_a_persistence_error(self):
        """A folder path that is really a file cannot hold waybills."""
        blocker = self.write_file("not_a_folder", "")
        with self.assertRaises(PersistenceError):
            self.system.write_all_waybills(blocker)


class TestUserInterface(unittest.TestCase):
    """The menu interface survives bad input and reaches the features."""

    def setUp(self):
        """Builds a console around a small system with private files."""
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.data_file = os.path.join(self.folder, "lmis_data.json")
        self.system = make_worked_example_system(with_invoices=True)
        self.console = ClerkConsole(self.system, self.data_file,
                                    os.path.join(self.folder, "waybills"))

    def test_letters_typed_for_a_number_are_refused_politely(self):
        """'abc' prompts again instead of crashing; 1,500 is understood."""
        printed = io.StringIO()
        with mock.patch("builtins.input", side_effect=["abc", "1,500"]), \
                contextlib.redirect_stdout(printed):
            self.assertEqual(ask_number("Rate"), 1500.0)
        self.assertIn("'abc' is not a number", printed.getvalue())
        with self.assertRaises(ValueError):
            parse_number("4.5", whole_number=True)

    def test_menu_survives_bad_choices_and_unknown_ids(self):
        """Nonsense menu choices and an unknown id produce advice."""
        output = run_console(self.console, ["99", "hello", "2", "SL-9999",
                                            "8", "SL-2014", "0"])
        self.assertIn("'99' is not an option", output)
        self.assertIn("no shipment with tracking id SL-9999", output)
        self.assertIn("SL-2014 has not been delivered yet", output)
        self.assertIn("Goodbye", output)

    def test_menu_registers_a_shipment_and_saves_on_exit(self):
        """A full registration through the menu, with a typo on the way,
        ends in a saved file holding the new shipment."""
        answers = ["1", "BulkFreight", "SL-7001", "Kivu Coffee", "Depot 2",
                   "Rusizi", "heavy", "300", "900", "4", "10",
                   "0", "y"]
        output = run_console(self.console, answers)
        self.assertIn("Registered SL-7001", output)
        with open(self.data_file, encoding="utf-8") as data_file:
            saved = json.load(data_file)
        saved_ids = [record["tracking_id"] for record in saved["shipments"]]
        self.assertIn("SL-7001", saved_ids)

    def test_cancelling_leaves_the_system_unchanged(self):
        """Typing q part-way through registration changes nothing."""
        output = run_console(self.console, ["1", "Shipment", "SL-7002",
                                            "q", "0"])
        self.assertIn("Cancelled", output)
        self.assertNotIn("SL-7002", self.system)

    def test_modules_run_nothing_on_import(self):
        """Importing the five modules prints nothing and starts nothing."""
        folder = os.path.dirname(os.path.abspath(__file__))
        result = subprocess.run(
            [sys.executable, "-c",
             "import shipments, tracking, billing, lmis, main"],
            cwd=folder, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
