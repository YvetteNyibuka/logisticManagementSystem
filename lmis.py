# AndrewIDs: iizanyib, ualijuni, lirumvak
"""
The SwiftLink Logistics Management Information System.

Defines LogisticsMIS, which owns every shipment, scan event and invoice and
offers the operations a depot clerk needs:

    consignment management  add, look up, update and remove shipments
    journey tracking        record scans, scan histories, network scans for
                            a day, transit times, guarantee compliance
    invoicing               raise one invoice, or all outstanding ones
    reporting               register, scan summary, monthly revenue and
                            guarantee compliance, as readable text
    persistence             save and load the whole state as JSON, and write
                            one waybill text file per shipment

Also defines the system's own exception classes. Following the separation
set up in Assignment 1, the classes here raise exceptions and return text;
they never print. The driver, main.py, decides what to tell the user.

Nothing runs on import.
"""

import json
import os
from datetime import datetime
from decimal import Decimal

from billing import RULE, Invoice, format_amount_line, round_money, to_decimal
from shipments import (ExpressParcel, Shipment, TrackedShipment,
                       build_shipment, validate_text)
from tracking import ScanEvent

# Column widths shared by the text reports.
ID_WIDTH = 9
SERVICE_WIDTH = 17
CITY_WIDTH = 13
STATUS_WIDTH = 18
LOCATION_WIDTH = 20
MONEY_WIDTH = 14
WAYBILL_RULE = "=" * 60

# The components a revenue summary adds up, in the order they are shown.
# Each pairs a key of the summary dictionary with the Invoice getter that
# supplies it.
REVENUE_COMPONENTS = (
    ("transport_charge", Invoice.get_transport_charge),
    ("fuel_levy", Invoice.get_fuel_levy),
    ("remote_surcharge", Invoice.get_remote_surcharge),
    ("corporate_discount", Invoice.get_corporate_discount),
    ("subtotal", Invoice.get_subtotal),
    ("vat", Invoice.get_vat),
    ("total", Invoice.get_total)
)

# The columns of the invoice summary, laid out like the worked examples in
# the specification: heading, width and the Invoice getter for the figure.
INVOICE_COLUMNS = (
    ("Transport", 11, Invoice.get_transport_charge),
    ("Levy", 10, Invoice.get_fuel_levy),
    ("Remote", 9, Invoice.get_remote_surcharge),
    ("Discount", 10, Invoice.get_corporate_discount),
    ("Subtotal", 11, Invoice.get_subtotal),
    ("VAT", 10, Invoice.get_vat),
    ("TOTAL", 11, Invoice.get_total)
)


class LMISError(Exception):
    """
    Base class for every failure that belongs to the LMIS itself, so a
    caller can catch them all with one clause when that is what it wants.
    """


class DuplicateTrackingIDError(LMISError):
    """Raised when a tracking id already exists in the system."""


class ShipmentNotFoundError(LMISError):
    """Raised when no shipment has the tracking id that was asked for."""


class DuplicateInvoiceError(LMISError):
    """Raised when a shipment that already has an invoice is invoiced again
    without asking for the invoice to be re-issued."""


class InvoiceNotFoundError(LMISError):
    """Raised when a shipment exists but no invoice has been raised for it."""


class NotDeliveredError(LMISError):
    """Raised when a figure that needs a delivery scan, such as the transit
    time, is asked for a shipment that has not been delivered."""


class ScanSequenceError(LMISError):
    """Raised when a scan would break the order of a journey, for example
    a scan dated after the shipment was delivered."""


class PersistenceError(LMISError):
    """Raised when the saved state or a waybill cannot be read or written."""


def _find_name(name, names):
    """
    Finds a name in a list, ignoring capitals and surrounding spaces.
    Parameters: name : str, names : list of str.
    Returns: str, the matching entry as stored, or None when absent.
    """
    wanted = str(name).strip().casefold()
    for existing in names:
        if existing.casefold() == wanted:
            return existing
    return None


def _indent(text, spaces=2):
    """
    Indents every line of a block of text.
    Parameters: text : str, spaces : int.
    Returns: str.
    """
    padding = " " * spaces
    return "\n".join(padding + line for line in text.splitlines())


class LogisticsMIS:
    """
    The system: owns the shipments, their scan events and their invoices.

    Shipments are held in a dictionary keyed by tracking id, scan events in
    a dictionary of chronological lists keyed the same way, and at most one
    invoice per tracking id. ScanEvent and Invoice refer to their shipment
    by that id, which is why it must be unique and unchangeable.

    The billing policy, which districts are remote and which senders are
    corporate accounts, lives here rather than in a shipment, and is
    supplied to each invoice as it is raised.

    Data members: _shipments, _scan_events, _invoices, _remote_districts,
    _corporate_accounts.
    Class variables: SYSTEM_NAME, DEFAULT_REMOTE_DISTRICTS,
    DATA_FORMAT_VERSION, NOT_SCANNED, GUARANTEE_MET, GUARANTEE_MISSED,
    GUARANTEE_PENDING.
    """

    SYSTEM_NAME = "SwiftLink Logistics MIS"
    DEFAULT_REMOTE_DISTRICTS = ("Nyagatare", "Rusizi", "Kirehe", "Nyamasheke")
    DATA_FORMAT_VERSION = 1
    NOT_SCANNED = "not scanned yet"
    GUARANTEE_MET = "MET"
    GUARANTEE_MISSED = "MISSED"
    GUARANTEE_PENDING = "PENDING"

    def __init__(self, remote_districts=None, corporate_accounts=None):
        """
        Creates an empty system with its billing policy.

        Parameters: remote_districts : list of str, or None for the default
        four; corporate_accounts : list of str, or None for none.
        Returns: None.
        Raises: ValueError when a name is blank or listed twice.
        """
        self._shipments = {}
        self._scan_events = {}
        self._invoices = {}
        self._remote_districts = []
        self._corporate_accounts = []

        if remote_districts is None:
            remote_districts = LogisticsMIS.DEFAULT_REMOTE_DISTRICTS
        if corporate_accounts is None:
            corporate_accounts = []
        # The add methods hold the validation, so they are reused here.
        for district in remote_districts:
            self.add_remote_district(district)
        for account in corporate_accounts:
            self.add_corporate_account(account)

    # ------------------------------------------------------------------
    # Billing policy
    # ------------------------------------------------------------------

    def get_remote_districts(self):
        """
        Returns the districts that attract the remote area surcharge.
        Parameters: none.
        Returns: list of str, a copy in alphabetical order.
        """
        return sorted(self._remote_districts)

    def get_corporate_accounts(self):
        """
        Returns the senders registered as corporate accounts.
        Parameters: none.
        Returns: list of str, a copy in alphabetical order.
        """
        return sorted(self._corporate_accounts)

    def is_remote_district(self, city):
        """
        Reports whether a destination is a remote district, ignoring case.
        Parameters: city : str.
        Returns: bool.
        """
        return _find_name(city, self._remote_districts) is not None

    def is_corporate_account(self, sender_name):
        """
        Reports whether a sender is a corporate account, ignoring case.
        Parameters: sender_name : str.
        Returns: bool.
        """
        return _find_name(sender_name, self._corporate_accounts) is not None

    def add_remote_district(self, district):
        """
        Adds a district to the remote list.
        Parameters: district : str.
        Returns: None.
        Raises: ValueError when the name is blank or already listed.
        """
        district = validate_text(district, "a district name")
        if self.is_remote_district(district):
            raise ValueError(f"{district} is already a remote district")
        self._remote_districts.append(district)

    def remove_remote_district(self, district):
        """
        Removes a district from the remote list.
        Parameters: district : str.
        Returns: None.
        Raises: ValueError when the district is not in the list.
        """
        existing = _find_name(district, self._remote_districts)
        if existing is None:
            raise ValueError(f"{district} is not in the remote district list")
        self._remote_districts.remove(existing)

    def add_corporate_account(self, account):
        """
        Registers a sender as a corporate account.
        Parameters: account : str, the sender name as it appears on
        shipments.
        Returns: None.
        Raises: ValueError when the name is blank or already registered.
        """
        account = validate_text(account, "a corporate account name")
        if self.is_corporate_account(account):
            raise ValueError(f"{account} is already a corporate account")
        self._corporate_accounts.append(account)

    def remove_corporate_account(self, account):
        """
        Removes a sender from the corporate accounts.
        Parameters: account : str.
        Returns: None.
        Raises: ValueError when the account is not registered.
        """
        existing = _find_name(account, self._corporate_accounts)
        if existing is None:
            raise ValueError(f"{account} is not a corporate account")
        self._corporate_accounts.remove(existing)

    # ------------------------------------------------------------------
    # Consignment management
    # ------------------------------------------------------------------

    def add_shipment(self, shipment):
        """
        Registers a shipment in the system.
        Parameters: shipment : Shipment, of any class in the hierarchy.
        Returns: None.
        Raises: TypeError when given something that is not a Shipment,
        DuplicateTrackingIDError when its tracking id is already in use.
        """
        if not isinstance(shipment, Shipment):
            raise TypeError("only a Shipment can be registered, got "
                            f"{type(shipment).__name__}")
        tracking_id = shipment.get_tracking_id()
        if tracking_id in self._shipments:
            raise DuplicateTrackingIDError(
                f"{tracking_id} is already registered")
        self._shipments[tracking_id] = shipment
        self._scan_events[tracking_id] = []

    def find_shipment(self, tracking_id):
        """
        Looks a shipment up by tracking id.
        Parameters: tracking_id : str.
        Returns: Shipment.
        Raises: ShipmentNotFoundError when no shipment has that id; the
        method never returns None.
        """
        if tracking_id not in self._shipments:
            raise ShipmentNotFoundError(
                f"no shipment with tracking id {tracking_id}")
        return self._shipments[tracking_id]

    def get_shipments(self):
        """
        Returns every shipment, in the order they were registered.
        Parameters: none.
        Returns: list of Shipment.
        """
        return list(self._shipments.values())

    def update_shipment(self, tracking_id, /, **changes):
        """
        Corrects one or more editable details of a shipment.

        The shipment's own setters validate every value, and either every
        change is applied or none is. If the shipment has already been
        invoiced, its invoice is re-issued under the original date, so an
        invoice never disagrees with the shipment it bills.

        Parameters: tracking_id : str, changes : field names and new values,
        for example weight_kg=3.0 or destination_city="Rusizi".
        Returns: Shipment, the updated shipment.
        Raises: ShipmentNotFoundError for an unknown id, ValueError for a
        field that cannot be edited or a value a setter refuses.
        """
        # The "/" makes tracking_id positional-only, so an attempt to pass
        # tracking_id="SL-0002" as a change reaches the shipment and is
        # refused with a clear message instead of a confusing TypeError.
        shipment = self.find_shipment(tracking_id)
        shipment.update_details(changes)
        if tracking_id in self._invoices:
            issue_date = self._invoices[tracking_id].get_issue_date()
            self._invoices[tracking_id] = self._build_invoice(shipment,
                                                              issue_date)
        return shipment

    def remove_shipment(self, tracking_id):
        """
        Removes a shipment together with its scan events and its invoice.

        The scans and the invoice only have meaning through the shipment
        they refer to, so leaving them behind would create orphan records
        that no lookup can reach, that would still be counted in the
        revenue, and that would attach themselves to any future shipment
        given the same id. They are returned, so the caller can confirm or
        archive what was removed.

        Parameters: tracking_id : str.
        Returns: tuple (Shipment, list of ScanEvent, Invoice or None).
        Raises: ShipmentNotFoundError for an unknown id.
        """
        shipment = self.find_shipment(tracking_id)
        del self._shipments[tracking_id]
        removed_scans = self._scan_events.pop(tracking_id, [])
        removed_invoice = self._invoices.pop(tracking_id, None)
        return shipment, removed_scans, removed_invoice

    # ------------------------------------------------------------------
    # Journey tracking
    # ------------------------------------------------------------------

    def record_scan(self, tracking_id, timestamp, location, status):
        """
        Records a scan of a shipment at a point in the network.
        Parameters: tracking_id : str, timestamp : str (YYYY-MM-DD HH:MM),
        location : str, status : str.
        Returns: ScanEvent, the scan recorded.
        Raises: ShipmentNotFoundError when the id is unknown, ValueError
        when a scan value is invalid, ScanSequenceError when the scan would
        break the order of the journey.
        """
        # Looked up first, so a scan against an unknown id is refused.
        self.find_shipment(tracking_id)
        scan = ScanEvent(tracking_id, timestamp, location, status)
        self.add_scan_event(scan)
        return scan

    def add_scan_event(self, scan):
        """
        Adds an existing ScanEvent to its shipment's journey.

        The journey is kept in time order. A tracked shipment's status is
        moved on to the status of its latest scan, which is what
        current_status was introduced for in Assignment 1.

        Parameters: scan : ScanEvent.
        Returns: None.
        Raises: TypeError when not given a ScanEvent, ShipmentNotFoundError
        when its shipment is unknown, ScanSequenceError when it would break
        the order of the journey.
        """
        if not isinstance(scan, ScanEvent):
            raise TypeError(
                f"expected a ScanEvent, got {type(scan).__name__}")
        shipment = self.find_shipment(scan.get_tracking_id())
        history = self._scan_events[scan.get_tracking_id()]
        self._check_scan_sequence(history, scan)

        history.append(scan)
        # sort() is stable, so two scans in the same minute keep the order
        # in which they were recorded.
        history.sort(key=ScanEvent.get_datetime)
        if isinstance(shipment, TrackedShipment):
            shipment.set_current_status(history[-1].get_status())

    @staticmethod
    def _find_delivery_scan(history):
        """
        Returns the delivery scan of a journey.
        Parameters: history : list of ScanEvent.
        Returns: ScanEvent, or None when the shipment is not delivered.
        """
        for scan in history:
            if scan.is_delivery():
                return scan
        return None

    def _check_scan_sequence(self, history, scan):
        """
        Refuses a scan that would make the journey inconsistent.

        A delivery scan closes the journey: it must be the last scan, and
        there can only be one. Earlier scans that reach the system late,
        for example from a handheld that was offline, are still accepted.

        Parameters: history : list of ScanEvent in time order,
        scan : ScanEvent, the new scan.
        Returns: None.
        Raises: ScanSequenceError when the scan breaks the journey's order.
        """
        tracking_id = scan.get_tracking_id()
        delivery = LogisticsMIS._find_delivery_scan(history)
        if delivery is not None:
            if scan.is_delivery():
                raise ScanSequenceError(
                    f"{tracking_id} already has a delivery scan, at "
                    f"{delivery.get_timestamp()}")
            if scan.get_datetime() > delivery.get_datetime():
                raise ScanSequenceError(
                    f"{tracking_id} was delivered at "
                    f"{delivery.get_timestamp()}, so its journey is closed "
                    "and cannot take a later scan")
        elif (scan.is_delivery() and history
              and history[-1].get_datetime() > scan.get_datetime()):
            raise ScanSequenceError(
                f"a delivery scan must be the last of the journey, but "
                f"{tracking_id} was already scanned later, at "
                f"{history[-1].get_timestamp()}")

    def get_scan_history(self, tracking_id):
        """
        Returns the scans of one shipment in chronological order.
        Parameters: tracking_id : str.
        Returns: list of ScanEvent, a copy.
        Raises: ShipmentNotFoundError for an unknown id.
        """
        self.find_shipment(tracking_id)
        return list(self._scan_events[tracking_id])

    def get_all_scans(self):
        """
        Returns every scan in the network in chronological order.
        Parameters: none.
        Returns: list of ScanEvent.
        """
        every_scan = []
        for history in self._scan_events.values():
            every_scan.extend(history)
        every_scan.sort(key=ScanEvent.get_datetime)
        return every_scan

    def get_scans_on(self, day):
        """
        Returns the scans recorded across the whole network on one day.
        Parameters: day : str, in the form YYYY-MM-DD.
        Returns: list of ScanEvent in time order.
        Raises: ValueError when the date cannot be parsed.
        """
        wanted = ScanEvent.parse_date(day)
        return [scan for scan in self.get_all_scans()
                if scan.get_date() == wanted]

    def get_latest_scan(self, tracking_id):
        """
        Returns the most recent scan of a shipment.
        Parameters: tracking_id : str.
        Returns: ScanEvent, or None when it has not been scanned yet.
        Raises: ShipmentNotFoundError for an unknown id.
        """
        history = self.get_scan_history(tracking_id)
        if not history:
            return None
        return history[-1]

    def get_current_status(self, tracking_id):
        """
        Returns where a shipment stands: the status of its latest scan.

        A tracked shipment that has not been scanned reports the status it
        was registered with; any other unscanned shipment reports that it
        has not been scanned yet.

        Parameters: tracking_id : str.
        Returns: str.
        Raises: ShipmentNotFoundError for an unknown id.
        """
        latest = self.get_latest_scan(tracking_id)
        if latest is not None:
            return latest.get_status()
        shipment = self.find_shipment(tracking_id)
        if isinstance(shipment, TrackedShipment):
            return shipment.get_current_status()
        return LogisticsMIS.NOT_SCANNED

    def get_current_location(self, tracking_id):
        """
        Returns where a shipment was last scanned.
        Parameters: tracking_id : str.
        Returns: str.
        Raises: ShipmentNotFoundError for an unknown id.
        """
        latest = self.get_latest_scan(tracking_id)
        if latest is None:
            return LogisticsMIS.NOT_SCANNED
        return latest.get_location()

    def is_delivered(self, tracking_id):
        """
        Reports whether a shipment has a delivery scan.
        Parameters: tracking_id : str.
        Returns: bool.
        Raises: ShipmentNotFoundError for an unknown id.
        """
        history = self.get_scan_history(tracking_id)
        return LogisticsMIS._find_delivery_scan(history) is not None

    def get_transit_hours(self, tracking_id):
        """
        Returns the time from a shipment's first scan to its delivery scan.
        Parameters: tracking_id : str.
        Returns: float, hours.
        Raises: ShipmentNotFoundError for an unknown id, NotDeliveredError
        when there is no delivery scan yet, rather than returning a figure
        that would mislead.
        """
        history = self.get_scan_history(tracking_id)
        delivery = LogisticsMIS._find_delivery_scan(history)
        if delivery is None:
            if not history:
                raise NotDeliveredError(
                    f"{tracking_id} has not been scanned yet, so it has no "
                    "transit time")
            latest = history[-1]
            raise NotDeliveredError(
                f"{tracking_id} has not been delivered yet (last scan: "
                f"{latest.get_status()} at {latest.get_location()}, "
                f"{latest.get_timestamp()}), so it has no transit time")
        # Subtracting two datetimes gives a timedelta.
        elapsed = delivery.get_datetime() - history[0].get_datetime()
        return elapsed.total_seconds() / 3600

    def get_guarantee_compliance(self):
        """
        Checks every ExpressParcel against its delivery guarantee.

        This is the report that reaches back into the Assignment 1
        hierarchy: guaranteed_hours comes from each ExpressParcel.

        Verdicts: MET when delivered within the guarantee; MISSED when
        delivered late, or when still undelivered but already past it;
        PENDING when undelivered and still within it.

        Parameters: none.
        Returns: list of dict with the keys tracking_id, guaranteed_hours,
        delivered (bool), elapsed_hours (float, or None when never
        scanned) and verdict (str).
        """
        results = []
        for shipment in self._shipments.values():
            if not isinstance(shipment, ExpressParcel):
                continue
            tracking_id = shipment.get_tracking_id()
            guaranteed = shipment.get_guaranteed_hours()
            history = self._scan_events[tracking_id]
            delivered = self.is_delivered(tracking_id)

            if delivered:
                elapsed = self.get_transit_hours(tracking_id)
            elif history:
                # Not delivered: measure how long it has been travelling.
                span = history[-1].get_datetime() - history[0].get_datetime()
                elapsed = span.total_seconds() / 3600
            else:
                elapsed = None

            if elapsed is not None and elapsed > guaranteed:
                verdict = LogisticsMIS.GUARANTEE_MISSED
            elif delivered:
                verdict = LogisticsMIS.GUARANTEE_MET
            else:
                verdict = LogisticsMIS.GUARANTEE_PENDING
            results.append({
                "tracking_id": tracking_id,
                "guaranteed_hours": guaranteed,
                "delivered": delivered,
                "elapsed_hours": elapsed,
                "verdict": verdict
            })
        return results

    # ------------------------------------------------------------------
    # Invoicing
    # ------------------------------------------------------------------

    def _build_invoice(self, shipment, issue_date):
        """
        Builds an invoice for a shipment, supplying the billing policy.
        Parameters: shipment : Shipment, issue_date : str or None.
        Returns: Invoice.
        """
        return Invoice.for_shipment(
            shipment,
            is_remote=self.is_remote_district(
                shipment.get_destination_city()),
            is_corporate=self.is_corporate_account(
                shipment.get_sender_name()),
            issue_date=issue_date)

    def raise_invoice(self, tracking_id, issue_date=None, reissue=False):
        """
        Raises the invoice for one shipment, applying the billing rules.

        Parameters: tracking_id : str, issue_date : str (YYYY-MM-DD) or
        None for today, reissue : bool, True to replace an existing invoice
        with one that reflects the current details and policy.
        Returns: Invoice.
        Raises: ShipmentNotFoundError for an unknown id,
        DuplicateInvoiceError when already invoiced and reissue is False,
        ValueError for an invalid date.
        """
        shipment = self.find_shipment(tracking_id)
        if tracking_id in self._invoices and not reissue:
            existing = self._invoices[tracking_id]
            raise DuplicateInvoiceError(
                f"{tracking_id} was already invoiced as "
                f"{existing.get_invoice_number()} on "
                f"{existing.get_issue_date()}")
        invoice = self._build_invoice(shipment, issue_date)
        self._invoices[tracking_id] = invoice
        return invoice

    def raise_all_invoices(self, issue_date=None):
        """
        Raises an invoice for every shipment that does not have one yet.

        Invoices already issued are left alone, so running this again in a
        later month never moves earlier revenue into the new month.

        Parameters: issue_date : str (YYYY-MM-DD) or None for today.
        Returns: list of Invoice, the invoices raised by this call.
        Raises: ValueError for an invalid date, before anything is raised.
        """
        if issue_date is not None:
            issue_date = Invoice.parse_date(issue_date)
        raised = []
        # Polymorphism: the collection mixes all five shipment classes, and
        # each invoice gets its transport charge from calculate_cost(),
        # which runs the pricing rule of the shipment's own class.
        for shipment in self._shipments.values():
            tracking_id = shipment.get_tracking_id()
            if tracking_id not in self._invoices:
                raised.append(self.raise_invoice(tracking_id, issue_date))
        return raised

    def has_invoice(self, tracking_id):
        """
        Reports whether a shipment has been invoiced.
        Parameters: tracking_id : str.
        Returns: bool.
        Raises: ShipmentNotFoundError for an unknown id.
        """
        self.find_shipment(tracking_id)
        return tracking_id in self._invoices

    def get_invoice(self, tracking_id):
        """
        Returns the invoice of one shipment.
        Parameters: tracking_id : str.
        Returns: Invoice.
        Raises: ShipmentNotFoundError for an unknown id,
        InvoiceNotFoundError when no invoice has been raised for it yet.
        """
        self.find_shipment(tracking_id)
        if tracking_id not in self._invoices:
            raise InvoiceNotFoundError(
                f"no invoice has been raised for {tracking_id} yet")
        return self._invoices[tracking_id]

    def get_invoices(self):
        """
        Returns every invoice, in the order the shipments were registered.
        Parameters: none.
        Returns: list of Invoice.
        """
        return [self._invoices[tracking_id]
                for tracking_id in self._shipments
                if tracking_id in self._invoices]

    def _store_invoice(self, invoice):
        """
        Stores an invoice read back from a saved file.
        Parameters: invoice : Invoice.
        Returns: None.
        Raises: ShipmentNotFoundError when its shipment is unknown,
        DuplicateInvoiceError when that shipment already has one.
        """
        tracking_id = invoice.get_tracking_id()
        self.find_shipment(tracking_id)
        if tracking_id in self._invoices:
            raise DuplicateInvoiceError(
                f"{tracking_id} has more than one saved invoice")
        self._invoices[tracking_id] = invoice

    # ------------------------------------------------------------------
    # Reporting: figures
    # ------------------------------------------------------------------

    def get_revenue_summary(self, month):
        """
        Adds up the invoices issued in one month, component by component.

        Parameters: month : str, in the form YYYY-MM.
        Returns: dict with the keys month, invoice_count and one key per
        component: transport_charge, fuel_levy, remote_surcharge,
        corporate_discount, subtotal, vat and total.
        Raises: ValueError when the month cannot be parsed.
        """
        month = Invoice.parse_month(month)
        invoices = [invoice for invoice in self.get_invoices()
                    if invoice.get_billing_month() == month]
        summary = {"month": month, "invoice_count": len(invoices)}
        for key, getter in REVENUE_COMPONENTS:
            # Added as Decimals, so the sum carries no binary float noise.
            component_total = sum((to_decimal(getter(invoice))
                                   for invoice in invoices), Decimal(0))
            summary[key] = round_money(component_total)
        return summary

    def get_total_revenue(self):
        """
        Returns the total payable across every invoice in the system.
        Parameters: none.
        Returns: float.
        """
        return round_money(sum((to_decimal(invoice.get_total())
                                for invoice in self._invoices.values()),
                               Decimal(0)))

    # ------------------------------------------------------------------
    # Reporting: readable text
    # ------------------------------------------------------------------

    def format_register(self):
        """
        Returns the consignment register: every shipment, its service,
        destination, status and transport charge.
        Parameters: none.
        Returns: str.
        """
        lines = [f"Consignment register ({len(self._shipments)} shipments)"]
        if not self._shipments:
            lines.append("  No shipments are registered.")
            return "\n".join(lines)
        lines.append(f"  {'ID':<{ID_WIDTH}}{'Service':<{SERVICE_WIDTH}}"
                     f"{'Destination':<{CITY_WIDTH}}"
                     f"{'Status':<{STATUS_WIDTH}}"
                     f"{'Charge (RWF)':>{MONEY_WIDTH}}")
        total = 0
        for shipment in self._shipments.values():
            tracking_id = shipment.get_tracking_id()
            # Polymorphic: each shipment prices itself by its own rule.
            cost = shipment.calculate_cost()
            total += cost
            lines.append(
                f"  {tracking_id:<{ID_WIDTH}}"
                f"{shipment.get_service_type():<{SERVICE_WIDTH}}"
                f"{shipment.get_destination_city():<{CITY_WIDTH}}"
                f"{self.get_current_status(tracking_id):<{STATUS_WIDTH}}"
                f"{cost:>{MONEY_WIDTH},.2f}")
        width = ID_WIDTH + SERVICE_WIDTH + CITY_WIDTH + STATUS_WIDTH
        lines.append("  " + "-" * (width + MONEY_WIDTH))
        lines.append(f"  {'Total transport charges':<{width}}"
                     f"{total:>{MONEY_WIDTH},.2f}")
        return "\n".join(lines)

    def _format_transit_line(self, tracking_id):
        """
        Returns the transit time line shown under a scan history.
        Parameters: tracking_id : str.
        Returns: str.
        """
        if not self.is_delivered(tracking_id):
            return "  Transit time: not available until it is delivered"
        hours = self.get_transit_hours(tracking_id)
        return f"  Transit time: {hours:.2f} hours"

    def format_scan_history(self, tracking_id):
        """
        Returns one shipment's scans in chronological order, followed by
        its transit time.
        Parameters: tracking_id : str.
        Returns: str.
        Raises: ShipmentNotFoundError for an unknown id.
        """
        shipment = self.find_shipment(tracking_id)
        history = self.get_scan_history(tracking_id)
        lines = [f"Scan history for {tracking_id} "
                 f"({shipment.get_service_type()} to "
                 f"{shipment.get_destination_city()})"]
        if not history:
            lines.append("  No scans recorded yet.")
            return "\n".join(lines)
        for scan in history:
            lines.append("  " + scan.format_line(show_tracking_id=False))
        lines.append(self._format_transit_line(tracking_id))
        return "\n".join(lines)

    def format_scans_on(self, day):
        """
        Returns every scan recorded across the network on one day.
        Parameters: day : str, in the form YYYY-MM-DD.
        Returns: str.
        Raises: ValueError when the date cannot be parsed.
        """
        scans = self.get_scans_on(day)
        shown_day = ScanEvent.parse_date(day).isoformat()
        lines = [f"Network scans on {shown_day} ({len(scans)} scans)"]
        if not scans:
            lines.append("  No scans were recorded on that day.")
        for scan in scans:
            lines.append("  " + scan.format_line())
        return "\n".join(lines)

    def format_scan_summary(self):
        """
        Returns how many scans each shipment has and where it now is.
        Parameters: none.
        Returns: str.
        """
        scan_total = sum(len(history)
                         for history in self._scan_events.values())
        lines = [f"Scan summary ({scan_total} scans across "
                 f"{len(self._shipments)} shipments)"]
        if not self._shipments:
            lines.append("  No shipments are registered.")
            return "\n".join(lines)
        lines.append(f"  {'ID':<{ID_WIDTH}}{'Scans':>5}  "
                     f"{'Current location':<{LOCATION_WIDTH}}"
                     f"{'Status':<{STATUS_WIDTH}}Last scan")
        for tracking_id, history in self._scan_events.items():
            latest = self.get_latest_scan(tracking_id)
            last_time = latest.get_timestamp() if latest else "-"
            lines.append(
                f"  {tracking_id:<{ID_WIDTH}}{len(history):>5}  "
                f"{self.get_current_location(tracking_id):<{LOCATION_WIDTH}}"
                f"{self.get_current_status(tracking_id):<{STATUS_WIDTH}}"
                f"{last_time}")
        return "\n".join(lines)

    def format_revenue_summary(self, month):
        """
        Returns the revenue for one month, by component and in total.
        Parameters: month : str, in the form YYYY-MM.
        Returns: str.
        Raises: ValueError when the month cannot be parsed.
        """
        summary = self.get_revenue_summary(month)
        month_name = datetime.strptime(summary["month"],
                                       Invoice.MONTH_FORMAT)
        discount = summary["corporate_discount"]
        lines = [
            f"Revenue summary, {month_name:%B %Y} "
            f"({summary['invoice_count']} invoices)",
            format_amount_line("Transport charges",
                               summary["transport_charge"]),
            format_amount_line(
                f"Fuel levy ({Invoice.FUEL_LEVY_RATE:.0%})",
                summary["fuel_levy"]),
            format_amount_line("Remote area surcharges",
                               summary["remote_surcharge"]),
            format_amount_line(
                "Corporate discounts "
                f"({Invoice.CORPORATE_DISCOUNT_RATE:.0%})",
                -discount if discount else 0.0),
            "  " + RULE,
            format_amount_line("Subtotal", summary["subtotal"]),
            format_amount_line(f"VAT ({Invoice.VAT_RATE:.0%})",
                               summary["vat"]),
            format_amount_line("Total revenue (RWF)", summary["total"])
        ]
        if not summary["invoice_count"]:
            lines.insert(1, "  No invoices were issued in that month.")
        return "\n".join(lines)

    def format_invoice_summary(self):
        """
        Returns every invoice on one line, broken down by component in the
        layout of the worked examples, followed by the total revenue.
        Parameters: none.
        Returns: str.
        """
        invoices = self.get_invoices()
        lines = [f"Invoice summary ({len(invoices)} invoices, RWF)"]
        if not invoices:
            lines.append("  No invoices have been raised yet.")
            return "\n".join(lines)
        heading = f"  {'ID':<{ID_WIDTH - 1}}"
        for title, width, _ in INVOICE_COLUMNS:
            heading += f"{title:>{width}}"
        lines.append(heading)
        for invoice in invoices:
            row = f"  {invoice.get_tracking_id():<{ID_WIDTH - 1}}"
            for _, width, getter in INVOICE_COLUMNS:
                row += f"{getter(invoice):>{width},.2f}"
            lines.append(row)
        lines.append(f"  Revenue for the period: "
                     f"{self.get_total_revenue():,.2f}")
        return "\n".join(lines)

    def format_guarantee_report(self):
        """
        Returns the guarantee compliance report for express parcels.
        Parameters: none.
        Returns: str.
        """
        results = self.get_guarantee_compliance()
        lines = ["Guarantee compliance (express parcels)"]
        if not results:
            lines.append("  There are no express parcels in the system.")
            return "\n".join(lines)
        for result in results:
            if result["delivered"]:
                detail = f"actual {result['elapsed_hours']:.2f} h"
            elif result["elapsed_hours"] is not None:
                detail = (f"not delivered, {result['elapsed_hours']:.2f} h "
                          "so far")
            else:
                detail = "not scanned yet"
            lines.append(f"  {result['tracking_id']:<{ID_WIDTH}}"
                         f"guaranteed {result['guaranteed_hours']:>2} h   "
                         f"{detail:<32}{result['verdict']}")
        verdicts = [result["verdict"] for result in results]
        lines.append(
            f"  Totals: "
            f"{verdicts.count(LogisticsMIS.GUARANTEE_MET)} met, "
            f"{verdicts.count(LogisticsMIS.GUARANTEE_MISSED)} missed, "
            f"{verdicts.count(LogisticsMIS.GUARANTEE_PENDING)} pending")
        return "\n".join(lines)

    def format_waybill(self, tracking_id):
        """
        Returns the waybill of one shipment: its details, its scan history
        and its invoice breakdown.
        Parameters: tracking_id : str.
        Returns: str.
        Raises: ShipmentNotFoundError for an unknown id.
        """
        shipment = self.find_shipment(tracking_id)
        lines = [
            WAYBILL_RULE,
            f"{Shipment.company_name.upper()} - WAYBILL {tracking_id}",
            WAYBILL_RULE,
            "",
            "SHIPMENT DETAILS",
            # __str__ is overridden down the hierarchy, so this one line
            # shows the right details for every class of shipment.
            _indent(str(shipment)),
            f"  Transport charge: {shipment.calculate_cost():,.2f} RWF",
            f"  Current status: {self.get_current_status(tracking_id)} "
            f"({self.get_current_location(tracking_id)})",
            "",
            "SCAN HISTORY",
            _indent(self.format_scan_history(tracking_id)),
            "",
            "INVOICE"
        ]
        if tracking_id in self._invoices:
            lines.append(_indent(str(self._invoices[tracking_id])))
        else:
            lines.append("  No invoice has been raised for this shipment yet.")
        lines.append(WAYBILL_RULE)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dict(self):
        """
        Returns the entire state of the system as a dictionary that
        json.dump can write: the policy, shipments, scans and invoices.
        Parameters: none.
        Returns: dict.
        """
        return {
            "system": LogisticsMIS.SYSTEM_NAME,
            "format_version": LogisticsMIS.DATA_FORMAT_VERSION,
            "policy": {
                "remote_districts": self.get_remote_districts(),
                "corporate_accounts": self.get_corporate_accounts()
            },
            "shipments": [shipment.to_dict()
                          for shipment in self._shipments.values()],
            "scan_events": [scan.to_dict() for scan in self.get_all_scans()],
            "invoices": [invoice.to_dict()
                         for invoice in self.get_invoices()]
        }

    @classmethod
    def from_dict(cls, data):
        """
        Rebuilds a system from a dictionary written by to_dict().

        A damaged record is skipped and reported instead of costing the
        depot the whole file. Scans and invoices whose shipment was skipped
        are skipped with it, since they would have nothing to refer to.

        Parameters: data : dict.
        Returns: tuple (LogisticsMIS, list of str describing any record
        that was skipped).
        Raises: ValueError when data is not a saved LMIS state at all.
        """
        if not isinstance(data, dict):
            raise ValueError("it does not hold a JSON object")
        for section in ("policy", "shipments", "scan_events", "invoices"):
            if section not in data:
                raise ValueError(f"the '{section}' section is missing")
        for section in ("shipments", "scan_events", "invoices"):
            if not isinstance(data[section], list):
                raise ValueError(f"the '{section}' section is not a list")
        policy = data["policy"]
        for key in ("remote_districts", "corporate_accounts"):
            if not isinstance(policy, dict) or not isinstance(
                    policy.get(key), list):
                raise ValueError(f"the policy has no '{key}' list")
        system = cls(policy["remote_districts"], policy["corporate_accounts"])

        warnings = []
        for position, record in enumerate(data["shipments"], start=1):
            try:
                system.add_shipment(build_shipment(record))
            except (KeyError, TypeError, ValueError,
                    DuplicateTrackingIDError) as error:
                warnings.append(f"skipped shipment record {position}: "
                                f"{error}")

        scans = []
        for position, record in enumerate(data["scan_events"], start=1):
            try:
                scans.append(ScanEvent.from_dict(record))
            except (KeyError, TypeError, ValueError) as error:
                warnings.append(f"skipped scan record {position}: {error}")
        # Added in time order, so the journey rules see each scan in turn.
        scans.sort(key=ScanEvent.get_datetime)
        for scan in scans:
            try:
                system.add_scan_event(scan)
            except (ShipmentNotFoundError, ScanSequenceError) as error:
                warnings.append(f"skipped the scan of "
                                f"{scan.get_tracking_id()} at "
                                f"{scan.get_timestamp()}: {error}")

        for position, record in enumerate(data["invoices"], start=1):
            try:
                system._store_invoice(Invoice.from_dict(record))
            except (KeyError, TypeError, ValueError, ShipmentNotFoundError,
                    DuplicateInvoiceError) as error:
                warnings.append(f"skipped invoice record {position}: "
                                f"{error}")
        return system, warnings

    def save(self, filename):
        """
        Saves the entire state of the system to a JSON file.

        The data is written to a temporary file first and then moved into
        place in one step, so a failure part-way through never leaves a
        half-written file where the last good save used to be.

        Parameters: filename : str.
        Returns: None.
        Raises: PersistenceError when the file cannot be written.
        """
        data = self.to_dict()
        temporary_name = filename + ".tmp"
        try:
            folder = os.path.dirname(filename)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(temporary_name, "w", encoding="utf-8") as data_file:
                # indent keeps the saved file readable for a person.
                json.dump(data, data_file, indent=4)
            os.replace(temporary_name, filename)
        except OSError as error:
            raise PersistenceError(
                f"could not save to {filename}: {error.strerror or error}"
            ) from error

    def load(self, filename):
        """
        Replaces the state of the system with the state saved in a file.

        The file is read and rebuilt in full before anything is replaced,
        so a load that fails leaves the system exactly as it was.

        Parameters: filename : str.
        Returns: list of str describing any record that was skipped, empty
        when everything loaded.
        Raises: PersistenceError when the file is missing, unreadable,
        not valid JSON, or not LMIS data.
        """
        # FileNotFoundError is a kind of OSError, and JSONDecodeError and
        # UnicodeDecodeError are kinds of ValueError, so the most specific
        # clauses come first.
        try:
            with open(filename, "r", encoding="utf-8") as data_file:
                data = json.load(data_file)
        except FileNotFoundError as error:
            raise PersistenceError(
                f"no saved data file was found at {filename}") from error
        except json.JSONDecodeError as error:
            raise PersistenceError(
                f"{filename} is not valid JSON ({error.msg} at line "
                f"{error.lineno}, column {error.colno})") from error
        except UnicodeDecodeError as error:
            raise PersistenceError(
                f"{filename} is not a readable text file") from error
        except OSError as error:
            raise PersistenceError(
                f"could not read {filename}: {error.strerror or error}"
            ) from error

        try:
            loaded, warnings = LogisticsMIS.from_dict(data)
        except ValueError as error:
            raise PersistenceError(
                f"{filename} does not hold LMIS data: {error}") from error

        self._shipments = loaded._shipments
        self._scan_events = loaded._scan_events
        self._invoices = loaded._invoices
        self._remote_districts = loaded._remote_districts
        self._corporate_accounts = loaded._corporate_accounts
        return warnings

    def write_waybill(self, tracking_id, folder):
        """
        Writes one shipment's waybill to TRACKING_ID.txt inside a folder.
        Parameters: tracking_id : str, folder : str, created if needed.
        Returns: str, the path of the file written.
        Raises: ShipmentNotFoundError for an unknown id, PersistenceError
        when the file cannot be written.
        """
        text = self.format_waybill(tracking_id)
        path = os.path.join(folder, f"{tracking_id}.txt")
        try:
            os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as waybill_file:
                waybill_file.write(text + "\n")
        except OSError as error:
            raise PersistenceError(
                f"could not write the waybill {path}: "
                f"{error.strerror or error}") from error
        return path

    def write_all_waybills(self, folder):
        """
        Writes a waybill for every shipment in the system.
        Parameters: folder : str, created if needed.
        Returns: list of str, the paths of the files written.
        Raises: PersistenceError when a file cannot be written.
        """
        return [self.write_waybill(tracking_id, folder)
                for tracking_id in self._shipments]

    # ------------------------------------------------------------------
    # Python protocols
    # ------------------------------------------------------------------

    def __len__(self):
        """
        Returns the number of shipments, so len(system) reads naturally.
        Parameters: none.
        Returns: int.
        """
        return len(self._shipments)

    def __contains__(self, tracking_id):
        """
        Supports "tracking_id in system".
        Parameters: tracking_id : str.
        Returns: bool.
        """
        return tracking_id in self._shipments

    def __str__(self):
        """
        Returns a one-line summary of what the system holds.
        Parameters: none.
        Returns: str.
        """
        scan_total = sum(len(history)
                         for history in self._scan_events.values())
        return (f"{LogisticsMIS.SYSTEM_NAME}: {len(self._shipments)} "
                f"shipments, {scan_total} scan events, "
                f"{len(self._invoices)} invoices")
