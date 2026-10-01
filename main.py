# AndrewIDs: iizanyib, ualijuni, lirumvak
"""
The driver of the SwiftLink Logistics MIS.

Run it in one of two ways:

    python main.py          the menu-driven interface for a depot clerk
    python main.py --demo   a demonstration of every feature, which also
                            writes data/lmis_data.json and one waybill per
                            shipment into the waybills folder

This module is the calling code of the system. The classes raise
exceptions; it is here that they are caught and turned into messages that
tell the user what went wrong and what to do about it.

Nothing runs on import: main() is called only when the file is run.
"""

import os
import sys
import tempfile
from datetime import datetime
from itertools import zip_longest

from billing import Invoice
from lmis import (DuplicateInvoiceError, DuplicateTrackingIDError,
                  InvoiceNotFoundError, LMISError, LogisticsMIS,
                  NotDeliveredError, PersistenceError, ScanSequenceError,
                  ShipmentNotFoundError)
from shipments import (SHIPMENT_CLASSES, BulkFreight, ExpressParcel,
                       FragileParcel, Shipment, TrackedShipment)
from tracking import ScanEvent

# Files are placed next to this script, wherever it is run from.
BASE_FOLDER = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_FOLDER, "data", "lmis_data.json")
WAYBILL_FOLDER = os.path.join(BASE_FOLDER, "waybills")

# The sample consignment used by the demonstration and by menu option 20:
# the six shipments of the worked examples, billed in September 2026.
SAMPLE_BILLING_DATE = "2026-09-15"
SAMPLE_MONTH = "2026-09"
SAMPLE_CORPORATE_ACCOUNTS = ["Gasabo Pharmacy", "Uwera Trading",
                             "Lake Glassworks", "Nyagatare Feeds",
                             "Muhanga Cement"]
SAMPLE_SCANS = [
    ("SL-5003", "2026-09-14 06:30", "Kigali Depot", "received"),
    ("SL-5004", "2026-09-14 07:00", "Kigali Depot", "received"),
    ("SL-2014", "2026-09-14 07:45", "Kigali Depot", "received"),
    ("SL-3120", "2026-09-14 08:30", "Kigali Depot", "received"),
    ("SL-4077", "2026-09-14 10:00", "Kigali Depot", "received"),
    ("SL-5004", "2026-09-14 10:30", "Muhanga Hub", "out for delivery"),
    ("SL-5003", "2026-09-14 11:45", "Kayonza Hub", "in transit"),
    ("SL-3120", "2026-09-14 12:05", "Muhanga Hub", "in transit"),
    ("SL-5004", "2026-09-14 12:40", "Muhanga", "delivered"),
    ("SL-2014", "2026-09-14 13:20", "Musanze Hub", "in transit"),
    ("SL-4077", "2026-09-14 15:30", "Musanze Hub", "in transit"),
    ("SL-3120", "2026-09-14 16:40", "Huye Depot", "out for delivery"),
    ("SL-3120", "2026-09-14 18:15", "Huye", "delivered"),
    ("SL-4077", "2026-09-15 08:10", "Rubavu Depot", "out for delivery"),
    ("SL-1001", "2026-09-15 09:10", "Kigali Depot", "received")
]

# Fields whose values come from a fixed list, offered as a choice.
FIELD_CHOICES = {
    "guaranteed_hours": tuple(ExpressParcel.PRIORITY_FEES),
    "handling_class": FragileParcel.ALLOWED_HANDLING_CLASSES
}

CANCEL_WORD = "q"


# ----------------------------------------------------------------------
# Sample data
# ----------------------------------------------------------------------

def build_sample_shipments():
    """
    Creates the six shipments of the worked examples, covering every class
    and both branches of the bulk freight rule.
    Parameters: none.
    Returns: list of Shipment.
    """
    return [
        # SL-1001 is sent by a private individual, so it takes no discount.
        Shipment("SL-1001", "Keza Uwase", "A. Niyonsaba", "Kigali", 4, 1500),
        TrackedShipment("SL-2014", "Gasabo Pharmacy", "D. Habimana",
                        "Musanze", 6, 1500, 400000, 0.03),
        ExpressParcel("SL-3120", "Uwera Trading", "J. Mugisha", "Huye", 2.5,
                      1800, 250000, 0.02, "in transit", 12),
        FragileParcel("SL-4077", "Lake Glassworks", "C. Ingabire", "Rubavu",
                      8, 1600, 900000, 0.05, "received", "glass", 5000),
        # Priced on volume: 14 m3 x 25,000 beats 320 kg x 900.
        BulkFreight("SL-5003", "Nyagatare Feeds", "Depot 3", "Nyagatare",
                    320, 900, 6, 14),
        # Priced on weight: 500 kg x 900 beats 12 m3 x 25,000.
        BulkFreight("SL-5004", "Muhanga Cement", "Depot 7", "Muhanga", 500,
                    900, 4, 12)
    ]


def build_sample_system(with_invoices=False):
    """
    Builds a system holding the sample shipments and their scans.
    Parameters: with_invoices : bool, True to raise the September invoices.
    Returns: LogisticsMIS.
    """
    system = LogisticsMIS(corporate_accounts=SAMPLE_CORPORATE_ACCOUNTS)
    for shipment in build_sample_shipments():
        system.add_shipment(shipment)
    for tracking_id, timestamp, location, status in SAMPLE_SCANS:
        system.record_scan(tracking_id, timestamp, location, status)
    if with_invoices:
        system.raise_all_invoices(SAMPLE_BILLING_DATE)
    return system


# ----------------------------------------------------------------------
# Small helpers shared by the demonstration and the menu
# ----------------------------------------------------------------------

def display_path(path):
    """
    Returns a path relative to the project folder, for shorter messages.
    Parameters: path : str.
    Returns: str, using forward slashes when it is inside the project.
    """
    try:
        relative = os.path.relpath(path, BASE_FOLDER)
    except ValueError:
        # On Windows a path on another drive has no relative form.
        return path
    if relative.startswith(".."):
        return path
    return relative.replace(os.sep, "/")


def describe_contents(system):
    """
    Returns how many records a system holds, for confirmation messages.
    Parameters: system : LogisticsMIS.
    Returns: str.
    """
    return (f"{len(system)} shipments, {len(system.get_all_scans())} scan "
            f"events, {len(system.get_invoices())} invoices")


def indent(text, spaces=2):
    """
    Indents every line of a block of text.
    Parameters: text : str, spaces : int.
    Returns: str.
    """
    padding = " " * spaces
    return "\n".join(padding + line for line in text.splitlines())


def parse_number(text, whole_number=False):
    """
    Converts typed text to a number, allowing separators such as 1,500.
    Parameters: text : str, whole_number : bool.
    Returns: int when whole_number is True, otherwise float.
    Raises: ValueError, with a message saying what to type instead.
    """
    cleaned = text.replace(",", "").replace(" ", "")
    try:
        if whole_number:
            return int(cleaned)
        return float(cleaned)
    except ValueError:
        wanted = ("a whole number such as 4" if whole_number
                  else "a number such as 2.5")
        raise ValueError(f"'{text}' is not {wanted}") from None


def load_system(filename):
    """
    Loads the saved system, or starts an empty one when that fails.

    Parameters: filename : str.
    Returns: tuple (LogisticsMIS, list of str messages for the user).
    """
    system = LogisticsMIS()
    try:
        warnings = system.load(filename)
    except PersistenceError as error:
        return system, [
            f"Could not load the saved data: {error}.",
            "Starting with an empty system. Register a shipment with "
            "option 1, or load the sample data with option 20."
        ]
    messages = [f"Loaded {describe_contents(system)} from "
                f"{display_path(filename)}."]
    for warning in warnings:
        messages.append(f"Warning: {warning}")
    return system, messages


# ----------------------------------------------------------------------
# Keyboard input that survives bad answers
# ----------------------------------------------------------------------

class OperationCancelled(Exception):
    """Raised when the clerk types q at a prompt to abandon an operation."""


def ask_text(prompt, default=None):
    """
    Asks for a line of text until something is typed.

    Pressing Enter on an empty line accepts the default, when there is one.

    Parameters: prompt : str, default : str or None.
    Returns: str.
    Raises: OperationCancelled when the clerk types q.
    """
    if default is None:
        shown_prompt = f"  {prompt}: "
    else:
        shown_prompt = f"  {prompt} [{default}]: "
    while True:
        answer = input(shown_prompt).strip()
        if answer.lower() == CANCEL_WORD:
            raise OperationCancelled
        if answer:
            return answer
        if default is not None:
            return str(default)
        print("    Please type a value, or q to cancel.")


def ask_number(prompt, whole_number=False):
    """
    Asks for a number until one is typed; letters are refused politely.
    Parameters: prompt : str, whole_number : bool.
    Returns: int or float.
    Raises: OperationCancelled when the clerk types q.
    """
    while True:
        answer = ask_text(prompt)
        try:
            return parse_number(answer, whole_number)
        except ValueError as error:
            print(f"    {error}. Please try again, or type q to cancel.")


def ask_valid(prompt, check, default=None):
    """
    Asks until the answer passes a check supplied by one of the classes,
    so the rule is never written a second time in the interface.

    Parameters: prompt : str, check : function that raises ValueError to
    refuse an answer, default : str or None.
    Returns: str, the accepted answer.
    Raises: OperationCancelled when the clerk types q.
    """
    while True:
        answer = ask_text(prompt, default)
        try:
            check(answer)
        except ValueError as error:
            print(f"    {error}. Please try again, or type q to cancel.")
        else:
            return answer


def ask_choice(prompt, options, default=None, labels=None):
    """
    Asks the clerk to pick one option, by its number or by its name.

    Parameters: prompt : str, options : list of the values to choose from,
    default : one of the options or None, labels : list of str shown
    instead of the options, or None.
    Returns: the chosen option.
    Raises: OperationCancelled when the clerk types q.
    """
    for number, label in enumerate(labels or options, start=1):
        print(f"    {number}. {label}")
    while True:
        answer = ask_text(prompt, default)
        # An option typed in full wins, so "12" means 12 hours, not the
        # twelfth option.
        for option in options:
            if answer.lower() == str(option).lower():
                return option
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        print(f"    '{answer}' is not one of the options. Type a number "
              f"from 1 to {len(options)}, or q to cancel.")


def ask_yes_no(prompt, default=False):
    """
    Asks a yes-or-no question.
    Parameters: prompt : str, default : bool, used when Enter is pressed.
    Returns: bool.
    Raises: OperationCancelled when the clerk types q.
    """
    while True:
        answer = ask_text(f"{prompt} (y/n)", "y" if default else "n")
        if answer.lower() in ("y", "yes"):
            return True
        if answer.lower() in ("n", "no"):
            return False
        print("    Please answer y or n, or q to cancel.")


def ask_tracking_id(prompt="Tracking id (SL-0000)"):
    """
    Asks for a tracking id in the right format; lower case is accepted.
    Parameters: prompt : str.
    Returns: str, in upper case.
    Raises: OperationCancelled when the clerk types q.
    """
    while True:
        answer = ask_text(prompt).upper()
        if Shipment.is_valid_tracking_id(answer):
            return answer
        print(f"    '{answer}' is not a tracking id: use the form SL-0000, "
              "or type q to cancel.")


# ----------------------------------------------------------------------
# The menu-driven interface
# ----------------------------------------------------------------------

class ClerkConsole:
    """
    The menu-driven interface a depot clerk uses to operate the LMIS.

    Each menu option is a method. run() shows the menu, calls the chosen
    method and catches whatever the system raises, telling the clerk what
    went wrong and what to do next. An option returns True when it changed
    the data, so the console knows when there is something to save.

    Data members: _system, _data_file, _waybill_folder, _unsaved_changes,
    _options.
    Class variables: MENU_COLUMNS.
    """

    # How the options are grouped on screen: two columns of sections.
    MENU_COLUMNS = (
        (("CONSIGNMENTS", ("1", "2", "3", "4")),
         ("JOURNEY TRACKING", ("5", "6", "7", "8")),
         ("INVOICING", ("9", "10", "11"))),
        (("REPORTS", ("12", "13", "14", "15")),
         ("DATA AND SETTINGS", ("16", "17", "18", "19", "20", "0")))
    )

    def __init__(self, system, data_file=DATA_FILE,
                 waybill_folder=WAYBILL_FOLDER):
        """
        Creates the interface around a system.
        Parameters: system : LogisticsMIS, data_file : str,
        waybill_folder : str.
        Returns: None.
        """
        self._system = system
        self._data_file = data_file
        self._waybill_folder = waybill_folder
        self._unsaved_changes = False
        self._options = {
            "1": ("Register a shipment", self.register_shipment),
            "2": ("Look up a shipment", self.look_up_shipment),
            "3": ("Update a shipment", self.update_shipment),
            "4": ("Remove a shipment", self.remove_shipment),
            "5": ("Record a scan", self.record_scan),
            "6": ("Scan history of a shipment", self.show_scan_history),
            "7": ("Network scans for a day", self.show_scans_on_day),
            "8": ("Transit time of a shipment", self.show_transit_time),
            "9": ("Raise an invoice", self.raise_invoice),
            "10": ("Raise all outstanding invoices",
                   self.raise_all_invoices),
            "11": ("Show an invoice", self.show_invoice),
            "12": ("Consignment register", self.show_register),
            "13": ("Scan summary", self.show_scan_summary),
            "14": ("Revenue summary for a month", self.show_revenue),
            "15": ("Guarantee compliance", self.show_guarantee_report),
            "16": ("Save the system", self.save_system),
            "17": ("Load the saved system", self.load_saved_system),
            "18": ("Write all waybills", self.write_waybills),
            "19": ("Billing policy", self.manage_billing_policy),
            "20": ("Load the sample data", self.load_sample_data),
            "0": ("Exit", None)
        }

    # -- the menu loop -------------------------------------------------

    def run(self):
        """
        Shows the menu and carries out the clerk's choices until they exit.
        Parameters: none.
        Returns: None.
        """
        while True:
            self._print_menu()
            try:
                choice = input("Choose an option: ").strip()
                if choice == "0":
                    if self._confirm_exit():
                        return
                    continue
                if choice not in self._options:
                    print(f"  '{choice}' is not an option. Type one of the "
                          "numbers shown in the menu.")
                    continue
                label, action = self._options[choice]
                print(f"\n--- {label} ---  (type q at any prompt to cancel)")
                if self._run_action(action):
                    self._unsaved_changes = True
            except EOFError:
                # The input has ended (Ctrl+Z or Ctrl+D, or a piped file
                # ran out), so there is no one left to ask.
                print()
                if self._unsaved_changes:
                    print("Input ended; your unsaved changes were not saved.")
                return

    def _print_menu(self):
        """
        Prints the options in two columns, under a line of status.
        Parameters: none.
        Returns: None.
        """
        column_width = 38
        columns = []
        for sections in ClerkConsole.MENU_COLUMNS:
            lines = []
            for title, choices in sections:
                lines.append(f" {title}")
                for choice in choices:
                    lines.append(f"  {choice:>2}  {self._options[choice][0]}")
            columns.append(lines)
        state = ("UNSAVED CHANGES - choose 16 to save"
                 if self._unsaved_changes else "all changes saved")
        print()
        print("=" * 74)
        print(f" {LogisticsMIS.SYSTEM_NAME} | "
              f"{describe_contents(self._system)}")
        print(f" {state}")
        print("=" * 74)
        for left, right in zip_longest(*columns, fillvalue=""):
            print(f"{left:<{column_width}}{right}".rstrip())
        print("=" * 74)

    def _run_action(self, action):
        """
        Runs one menu option, turning every expected failure into advice.

        Each exception is caught by name, so a genuine programming error
        is never hidden behind a friendly message.

        Parameters: action : a method of this class.
        Returns: bool, True when the option changed the data.
        """
        try:
            return bool(action())
        except OperationCancelled:
            print("  Cancelled; nothing was changed.")
        except DuplicateTrackingIDError as error:
            print(f"  Rejected: {error}. Use a different tracking id, or "
                  "look the shipment up with option 2.")
        except ShipmentNotFoundError as error:
            print(f"  Rejected: {error}. Check the id, or list every "
                  "shipment with option 12.")
        except DuplicateInvoiceError as error:
            print(f"  Rejected: {error}. Show it with option 11; updating "
                  "the shipment (option 3) re-issues it automatically.")
        except InvoiceNotFoundError as error:
            print(f"  Not available: {error}. Raise it with option 9.")
        except NotDeliveredError as error:
            print(f"  Not available: {error}. Record a 'delivered' scan "
                  "with option 5 once it arrives.")
        except ScanSequenceError as error:
            print(f"  Rejected: {error}. Check the timestamp and the "
                  "status, then record the scan again.")
        except PersistenceError as error:
            print(f"  File problem: {error}. Check the file and folder "
                  "permissions; the data in memory is unchanged.")
        except LMISError as error:
            print(f"  Rejected: {error}.")
        except ValueError as error:
            print(f"  Rejected: {error}. Nothing was changed; please try "
                  "again with a valid value.")
        except KeyboardInterrupt:
            print("\n  Interrupted; back to the menu.")
        return False

    def _confirm_exit(self):
        """
        Offers to save unsaved changes before leaving.
        Parameters: none.
        Returns: bool, True when the program should end.
        """
        if self._unsaved_changes:
            try:
                wants_to_save = ask_yes_no("Save your changes before "
                                           "leaving?", default=True)
            except OperationCancelled:
                print("  Staying in the system.")
                return False
            if wants_to_save:
                self._run_action(self.save_system)
                if self._unsaved_changes:
                    print("  Nothing was saved. Fix the problem above, or "
                          "choose 0 again and answer n to leave anyway.")
                    return False
        print("Goodbye.")
        return True

    # -- consignments --------------------------------------------------

    def _ask_new_tracking_id(self):
        """
        Asks for a tracking id that is not yet registered.
        Parameters: none.
        Returns: str.
        """
        while True:
            tracking_id = ask_tracking_id()
            if tracking_id not in self._system:
                return tracking_id
            print(f"    {tracking_id} is already registered. Choose another "
                  "id, or type q to cancel.")

    def register_shipment(self):
        """
        Registers a new shipment, asking only for what its class needs.
        Parameters: none.
        Returns: bool, True once the shipment is registered.
        """
        service = ask_choice("Service", list(SHIPMENT_CLASSES))
        tracking_id = self._ask_new_tracking_id()
        details = [tracking_id,
                   ask_text("Sender name"),
                   ask_text("Recipient name"),
                   ask_text("Destination city"),
                   ask_number("Weight in kg (above 0, up to 1000)"),
                   ask_number("Base rate per kg in RWF (above 0)")]
        if service == "BulkFreight":
            details.append(ask_number("Pallet count (1 to 20)",
                                      whole_number=True))
            details.append(ask_number("Volume in m3 (above 0)"))
        elif service != "Shipment":
            details.append(ask_number("Declared value in RWF (0 or more)"))
            details.append(ask_number("Insurance rate (0 to 0.05, "
                                      "e.g. 0.02 for 2%)"))
            details.append(ask_choice("Current status",
                                      TrackedShipment.ALLOWED_STATUSES,
                                      default="received"))
            if service == "ExpressParcel":
                details.append(ask_choice(
                    "Guarantee in hours", FIELD_CHOICES["guaranteed_hours"]))
            elif service == "FragileParcel":
                details.append(ask_choice(
                    "Handling class", FIELD_CHOICES["handling_class"]))
                details.append(ask_number("Packaging fee in RWF "
                                          "(0 or more)"))

        # The constructor validates every value through its setters.
        shipment = SHIPMENT_CLASSES[service](*details)
        self._system.add_shipment(shipment)
        print(f"  Registered {tracking_id}:")
        print(indent(str(shipment), 4))
        print(f"    Transport charge: {shipment.calculate_cost():,.2f} RWF")
        return True

    def look_up_shipment(self):
        """
        Shows one shipment with its charge, status and invoice.
        Parameters: none.
        Returns: None.
        """
        tracking_id = ask_tracking_id()
        shipment = self._system.find_shipment(tracking_id)
        scan_count = len(self._system.get_scan_history(tracking_id))
        status = self._system.get_current_status(tracking_id)
        location = self._system.get_current_location(tracking_id)
        print(indent(str(shipment)))
        print(f"  Transport charge: {shipment.calculate_cost():,.2f} RWF")
        print(f"  Current status: {status} ({location}), {scan_count} scans")
        if self._system.has_invoice(tracking_id):
            invoice = self._system.get_invoice(tracking_id)
            print(f"  Invoice {invoice.get_invoice_number()} issued "
                  f"{invoice.get_issue_date()}: total "
                  f"{invoice.get_total():,.2f} RWF")
        else:
            print("  Not invoiced yet.")

    def _ask_new_value(self, field_name, value_type):
        """
        Asks for a new value of the right type for one field.
        Parameters: field_name : str, value_type : type (str, int, float).
        Returns: the value typed, converted to value_type.
        """
        prompt = f"New {field_name.replace('_', ' ')}"
        if field_name in FIELD_CHOICES:
            return ask_choice(prompt, FIELD_CHOICES[field_name])
        if value_type is str:
            return ask_text(prompt)
        return ask_number(prompt, whole_number=value_type is int)

    def update_shipment(self):
        """
        Corrects one editable detail of a shipment.
        Parameters: none.
        Returns: bool, True once the change is made.
        """
        tracking_id = ask_tracking_id()
        shipment = self._system.find_shipment(tracking_id)
        fields = shipment.get_editable_fields()
        current = shipment.to_dict()
        names = list(fields)
        field_name = ask_choice(
            "Field to change", names,
            labels=[f"{name} (now {current[name]})" for name in names])
        new_value = self._ask_new_value(field_name, fields[field_name])

        was_invoiced = self._system.has_invoice(tracking_id)
        if was_invoiced:
            old_total = self._system.get_invoice(tracking_id).get_total()
        self._system.update_shipment(tracking_id, **{field_name: new_value})
        print(f"  Updated {field_name} of {tracking_id} to "
              f"{shipment.to_dict()[field_name]}.")
        print(f"  Transport charge is now "
              f"{shipment.calculate_cost():,.2f} RWF.")
        if was_invoiced:
            new_total = self._system.get_invoice(tracking_id).get_total()
            print(f"  Its invoice was re-issued: total {old_total:,.2f} -> "
                  f"{new_total:,.2f} RWF.")
        return True

    def remove_shipment(self):
        """
        Removes a shipment with its scans and invoice, after confirmation.
        Parameters: none.
        Returns: bool, True once the shipment is removed.
        """
        tracking_id = ask_tracking_id()
        shipment = self._system.find_shipment(tracking_id)
        scan_count = len(self._system.get_scan_history(tracking_id))
        print(f"  {tracking_id}: {shipment.get_service_type()} to "
              f"{shipment.get_destination_city()}, {scan_count} scans.")
        if self._system.has_invoice(tracking_id):
            print("  It has been invoiced: removing it also removes the "
                  "invoice and its revenue from the reports.")
        if not ask_yes_no(f"Remove {tracking_id} with its scans and "
                          "invoice?"):
            print("  Kept; nothing was removed.")
            return False
        _, scans, invoice = self._system.remove_shipment(tracking_id)
        removed = f"  Removed {tracking_id} with {len(scans)} scan events"
        if invoice is not None:
            removed += f" and invoice {invoice.get_invoice_number()}"
        print(removed + ".")
        return True

    # -- journey tracking ----------------------------------------------

    def record_scan(self):
        """
        Records a scan of a shipment.
        Parameters: none.
        Returns: bool, True once the scan is recorded.
        """
        tracking_id = ask_tracking_id()
        # Refuse an unknown id before asking for the rest of the scan.
        self._system.find_shipment(tracking_id)
        now = datetime.now().strftime(ScanEvent.TIMESTAMP_FORMAT)
        timestamp = ask_valid("Timestamp (YYYY-MM-DD HH:MM)",
                              ScanEvent.parse_timestamp, default=now)
        location = ask_text("Location, for example Muhanga Hub")
        status = ask_choice("Status", ScanEvent.ALLOWED_STATUSES)
        scan = self._system.record_scan(tracking_id, timestamp, location,
                                        status)
        print(f"  Recorded: {scan}")
        if scan.is_delivery():
            hours = self._system.get_transit_hours(tracking_id)
            print(f"  Delivered: transit time {hours:.2f} hours.")
        return True

    def show_scan_history(self):
        """
        Shows one shipment's scans in order, with its transit time.
        Parameters: none.
        Returns: None.
        """
        print(self._system.format_scan_history(ask_tracking_id()))

    def show_scans_on_day(self):
        """
        Shows every scan recorded across the network on one day.
        Parameters: none.
        Returns: None.
        """
        today = datetime.now().strftime(ScanEvent.DATE_FORMAT)
        day = ask_valid("Date (YYYY-MM-DD)", ScanEvent.parse_date,
                        default=today)
        print(self._system.format_scans_on(day))

    def show_transit_time(self):
        """
        Shows how long a delivered shipment took.
        Parameters: none.
        Returns: None.
        """
        tracking_id = ask_tracking_id()
        hours = self._system.get_transit_hours(tracking_id)
        print(f"  {tracking_id} took {hours:.2f} hours from its first scan "
              "to delivery.")

    # -- invoicing -----------------------------------------------------

    def raise_invoice(self):
        """
        Raises, or re-issues, the invoice for one shipment.
        Parameters: none.
        Returns: bool, True once an invoice is raised.
        """
        tracking_id = ask_tracking_id()
        self._system.find_shipment(tracking_id)
        reissue = False
        if self._system.has_invoice(tracking_id):
            existing = self._system.get_invoice(tracking_id)
            print(f"  {tracking_id} already has invoice "
                  f"{existing.get_invoice_number()}, issued "
                  f"{existing.get_issue_date()}.")
            reissue = ask_yes_no("Re-issue it with the current details and "
                                 "billing policy?")
            if not reissue:
                print("  The existing invoice was kept.")
                return False
        today = datetime.now().strftime(Invoice.DATE_FORMAT)
        issue_date = ask_valid("Issue date (YYYY-MM-DD)", Invoice.parse_date,
                               default=today)
        invoice = self._system.raise_invoice(tracking_id, issue_date,
                                             reissue=reissue)
        print(indent(str(invoice)))
        return True

    def raise_all_invoices(self):
        """
        Raises an invoice for every shipment that does not have one yet.
        Parameters: none.
        Returns: bool, True when at least one invoice was raised.
        """
        today = datetime.now().strftime(Invoice.DATE_FORMAT)
        issue_date = ask_valid("Issue date (YYYY-MM-DD)", Invoice.parse_date,
                               default=today)
        raised = self._system.raise_all_invoices(issue_date)
        if not raised:
            print("  Every shipment already has an invoice; nothing to "
                  "raise.")
            return False
        print(f"  Raised {len(raised)} invoices dated {issue_date}.")
        print(self._system.format_invoice_summary())
        return True

    def show_invoice(self):
        """
        Shows one invoice broken down by component.
        Parameters: none.
        Returns: None.
        """
        invoice = self._system.get_invoice(ask_tracking_id())
        print(indent(str(invoice)))

    # -- reports -------------------------------------------------------

    def show_register(self):
        """
        Shows the consignment register.
        Parameters: none.
        Returns: None.
        """
        print(self._system.format_register())

    def show_scan_summary(self):
        """
        Shows how many scans each shipment has and where it is now.
        Parameters: none.
        Returns: None.
        """
        print(self._system.format_scan_summary())

    def show_revenue(self):
        """
        Shows the revenue summary of one month.
        Parameters: none.
        Returns: None.
        """
        this_month = datetime.now().strftime(Invoice.MONTH_FORMAT)
        month = ask_valid("Month (YYYY-MM)", Invoice.parse_month,
                          default=this_month)
        print(self._system.format_revenue_summary(month))

    def show_guarantee_report(self):
        """
        Shows whether each express parcel met its delivery guarantee.
        Parameters: none.
        Returns: None.
        """
        print(self._system.format_guarantee_report())

    # -- data and settings ---------------------------------------------

    def save_system(self):
        """
        Saves the whole system to the data file.
        Parameters: none.
        Returns: None.
        """
        self._system.save(self._data_file)
        self._unsaved_changes = False
        print(f"  Saved {describe_contents(self._system)} to "
              f"{display_path(self._data_file)}.")

    def load_saved_system(self):
        """
        Replaces the system in memory with the one in the data file.
        Parameters: none.
        Returns: None.
        """
        if self._unsaved_changes and not ask_yes_no(
                "Loading replaces your unsaved changes. Continue?"):
            print("  Load cancelled; your changes are still in memory.")
            return
        warnings = self._system.load(self._data_file)
        self._unsaved_changes = False
        print(f"  Loaded {describe_contents(self._system)} from "
              f"{display_path(self._data_file)}.")
        for warning in warnings:
            print(f"  Warning: {warning}")

    def write_waybills(self):
        """
        Writes one waybill text file per shipment.
        Parameters: none.
        Returns: None.
        """
        paths = self._system.write_all_waybills(self._waybill_folder)
        if not paths:
            print("  There are no shipments, so no waybills were written.")
            return
        names = ", ".join(os.path.basename(path) for path in paths)
        print(f"  Wrote {len(paths)} waybills to "
              f"{display_path(self._waybill_folder)}/: {names}")

    def manage_billing_policy(self):
        """
        Shows the remote districts and corporate accounts, and changes them.
        Parameters: none.
        Returns: bool, True when the policy changed.
        """
        districts = ", ".join(self._system.get_remote_districts()) or "none"
        accounts = ", ".join(self._system.get_corporate_accounts()) or "none"
        print(f"  Remote districts ({Invoice.REMOTE_AREA_SURCHARGE:,} RWF "
              f"surcharge): {districts}")
        print(f"  Corporate accounts "
              f"({Invoice.CORPORATE_DISCOUNT_RATE:.0%} discount): {accounts}")
        print("  Changes apply to invoices raised from now on; invoices "
              "already issued keep their terms.")
        changes = {
            "Add a remote district": self._system.add_remote_district,
            "Remove a remote district": self._system.remove_remote_district,
            "Add a corporate account": self._system.add_corporate_account,
            "Remove a corporate account":
                self._system.remove_corporate_account,
            "Back to the menu": None
        }
        choice = ask_choice("Change", list(changes),
                            default="Back to the menu")
        if changes[choice] is None:
            return False
        name = ask_text("Name")
        changes[choice](name)
        print(f"  Done: {choice.lower()} '{name}'.")
        return True

    def load_sample_data(self):
        """
        Replaces the system in memory with the six sample shipments, their
        scans and their September 2026 invoices.
        Parameters: none.
        Returns: bool, True once the sample data is in place.
        """
        if len(self._system) and not ask_yes_no(
                f"This replaces the {len(self._system)} shipments in memory. "
                "Continue?"):
            print("  Kept the current data.")
            return False
        self._system = build_sample_system(with_invoices=True)
        print(f"  Loaded the sample data: {describe_contents(self._system)}.")
        return True


# ----------------------------------------------------------------------
# The demonstration
# ----------------------------------------------------------------------

def print_section(title):
    """
    Prints a section heading of the demonstration.
    Parameters: title : str.
    Returns: None.
    """
    print()
    print(title)
    print("-" * len(title))


def demonstrate_tracking(system):
    """
    Shows scan histories, the scans of one day, transit times and the
    guarantee compliance report.
    Parameters: system : LogisticsMIS.
    Returns: None.
    """
    print_section("Journey tracking")
    print(system.format_scan_history("SL-3120"))
    print()
    print(system.format_scan_history("SL-2014"))
    print()
    print(system.format_scans_on("2026-09-15"))
    print()
    print(system.format_scan_summary())
    print()
    print(system.format_guarantee_report())


def demonstrate_invoicing(system):
    """
    Raises every invoice in one polymorphic operation and shows the figures.
    Parameters: system : LogisticsMIS.
    Returns: None.
    """
    print_section("Invoicing")
    # One call invoices a collection of five different classes; each
    # invoice's transport charge comes from that shipment's own
    # calculate_cost().
    raised = system.raise_all_invoices(SAMPLE_BILLING_DATE)
    print(f"Raised {len(raised)} invoices in one operation, dated "
          f"{SAMPLE_BILLING_DATE}.")
    print()
    print(system.get_invoice("SL-3120"))
    print()
    print(system.get_invoice("SL-5003"))
    print()
    print(system.format_invoice_summary())
    print()
    print(system.format_revenue_summary(SAMPLE_MONTH))


def demonstrate_management(system):
    """
    Updates a shipment, shows a refused update leaving it unchanged, and
    removes a shipment together with its scans and invoice.
    Parameters: system : LogisticsMIS.
    Returns: None.
    """
    print_section("Consignment management")
    system.update_shipment("SL-2014", recipient_name="Dieudonne Habimana")
    shipment = system.find_shipment("SL-2014")
    print(f"Updated SL-2014: recipient is now {shipment.get_recipient_name()}"
          "; its invoice was re-issued at "
          f"{system.get_invoice('SL-2014').get_total():,.2f} RWF.")

    try:
        system.update_shipment("SL-2014", destination_city="Rusizi",
                               weight_kg=5000)
    except ValueError as error:
        print(f"Rejected: {error}")
    print(f"  SL-2014 is unchanged: {shipment.get_weight_kg()} kg to "
          f"{shipment.get_destination_city()}.")

    system.add_shipment(Shipment("SL-6001", "Walk-in Customer", "B. Mutoni",
                                 "Kirehe", 1.5, 1500))
    system.record_scan("SL-6001", "2026-09-15 11:00", "Kigali Depot",
                       "received")
    system.raise_invoice("SL-6001", SAMPLE_BILLING_DATE)
    print(f"Registered SL-6001 for Kirehe (remote), scanned and invoiced: "
          f"revenue {system.get_total_revenue():,.2f}")
    _, scans, invoice = system.remove_shipment("SL-6001")
    print(f"Removed SL-6001 with {len(scans)} scan event and invoice "
          f"{invoice.get_invoice_number()}: revenue back to "
          f"{system.get_total_revenue():,.2f}")


def demonstrate_persistence(system, data_file, waybill_folder):
    """
    Saves the system, writes the waybills, reloads the saved state into a
    new system and proves that it behaves identically.
    Parameters: system : LogisticsMIS, data_file : str,
    waybill_folder : str.
    Returns: bool, True when the round trip reproduced every figure.
    """
    print_section("Persistence")
    try:
        system.save(data_file)
        print(f"State saved to {display_path(data_file)} "
              f"({describe_contents(system)})")
        paths = system.write_all_waybills(waybill_folder)
        print(f"{len(paths)} waybills written to "
              f"{display_path(waybill_folder)}/: "
              f"{', '.join(os.path.basename(path) for path in paths)}")
        reloaded = LogisticsMIS()
        warnings = reloaded.load(data_file)
    except PersistenceError as error:
        print(f"File problem: {error}. Check that the folder is writable.")
        return False

    print(f"State reloaded into a new system ({describe_contents(reloaded)}"
          f", {len(warnings)} warnings)")
    print("  Classes rebuilt from the type key: " + ", ".join(
        shipment.get_service_type() for shipment in reloaded.get_shipments()))

    original = system.get_total_revenue()
    from_saved_invoices = reloaded.get_total_revenue()
    verdict = "matches" if from_saved_invoices == original else "DIFFERS"
    print(f"  Revenue from the reloaded invoices: {from_saved_invoices:,.2f}"
          f"  -> {verdict}")
    # Re-issuing every invoice prices the reloaded shipments again from
    # scratch, which proves the shipments themselves survived the trip.
    for shipment in reloaded.get_shipments():
        reloaded.raise_invoice(shipment.get_tracking_id(),
                               SAMPLE_BILLING_DATE, reissue=True)
    recomputed = reloaded.get_total_revenue()
    verdict = "matches" if recomputed == original else "DIFFERS"
    print(f"  Revenue recomputed from the reloaded shipments: "
          f"{recomputed:,.2f}  -> {verdict}")
    transit = reloaded.get_transit_hours("SL-3120")
    print(f"  Transit time of SL-3120 after reloading: {transit:.2f} hours")
    return from_saved_invoices == original and recomputed == original


def demonstrate_error_handling(system):
    """
    Triggers each kind of failure once and shows how it is handled: the
    classes raise, and this calling code catches each exception by name.
    Parameters: system : LogisticsMIS.
    Returns: None.
    """
    print_section("Errors handled")
    try:
        system.add_shipment(ExpressParcel(
            "SL-3120", "Uwera Trading", "J. Mugisha", "Huye", 2.5, 1800,
            250000, 0.02, "received", 12))
    except DuplicateTrackingIDError as error:
        print(f"  Rejected: {error}")
    try:
        system.find_shipment("SL-9999")
    except ShipmentNotFoundError as error:
        print(f"  Rejected: {error}")
    try:
        system.record_scan("SL-2014", "14/09/2026", "Musanze Hub",
                           "in transit")
    except ValueError as error:
        print(f"  Rejected: {error}")
    try:
        system.record_scan("SL-2014", "2026-09-15 10:00", "Musanze Hub",
                           "lost")
    except ValueError as error:
        print(f"  Rejected: {error}")
    try:
        system.record_scan("SL-9999", "2026-09-15 10:00", "Huye Depot",
                           "received")
    except ShipmentNotFoundError as error:
        print(f"  Rejected scan: {error}")
    try:
        system.record_scan("SL-3120", "2026-09-15 09:00", "Huye Depot",
                           "in transit")
    except ScanSequenceError as error:
        print(f"  Rejected: {error}")
    try:
        system.get_transit_hours("SL-2014")
    except NotDeliveredError as error:
        print(f"  Not available: {error}")
    try:
        system.raise_invoice("SL-3120")
    except DuplicateInvoiceError as error:
        print(f"  Rejected: {error}")
    try:
        system.update_shipment("SL-3120", guaranteed_hours=36)
    except ValueError as error:
        print(f"  Rejected: {error}")
    try:
        system.format_revenue_summary("September 2026")
    except ValueError as error:
        print(f"  Rejected: {error}")
    try:
        parse_number("12kg")
    except ValueError as error:
        print(f"  Rejected typed input: {error}")

    # File failures are shown in a temporary folder, so the demonstration
    # never leaves stray files behind.
    with tempfile.TemporaryDirectory() as scratch_folder:
        missing_file = os.path.join(scratch_folder, "no_such_file.json")
        malformed_file = os.path.join(scratch_folder, "malformed.json")
        with open(malformed_file, "w", encoding="utf-8") as broken:
            broken.write('{"shipments": [ {"type": "Shipment", ')
        for label, path in (("missing", missing_file),
                            ("malformed", malformed_file)):
            try:
                system.load(path)
            except PersistenceError as error:
                message = str(error).replace(scratch_folder + os.sep, "")
                print(f"  Load refused ({label} file): {message}")
    print(f"  The system carried on unchanged: {describe_contents(system)}")


def run_demo(data_file=DATA_FILE, waybill_folder=WAYBILL_FOLDER):
    """
    Runs the whole demonstration from start to finish.
    Parameters: data_file : str, waybill_folder : str.
    Returns: bool, True when the persistence round trip matched.
    """
    print(f"=== {LogisticsMIS.SYSTEM_NAME} - demonstration ===")
    system = build_sample_system()
    print(f"Registered the sample consignment: {describe_contents(system)}")
    print(f"Remote districts: {', '.join(system.get_remote_districts())}")
    print(f"Corporate accounts: {', '.join(system.get_corporate_accounts())}")

    print_section("Consignment register")
    print(system.format_register())
    demonstrate_tracking(system)
    demonstrate_invoicing(system)
    demonstrate_management(system)
    round_trip_matched = demonstrate_persistence(system, data_file,
                                                 waybill_folder)
    demonstrate_error_handling(system)
    print()
    print("Demonstration complete.")
    return round_trip_matched


def main():
    """
    Starts the demonstration or the menu, depending on the command line.
    Parameters: none (reads sys.argv).
    Returns: None.
    """
    arguments = sys.argv[1:]
    if arguments == ["--demo"]:
        run_demo()
        return
    if arguments:
        print("Usage: python main.py          start the menu interface")
        print("       python main.py --demo   run the demonstration")
        return

    system, messages = load_system(DATA_FILE)
    print(f"Welcome to the {LogisticsMIS.SYSTEM_NAME}.")
    for message in messages:
        print(message)
    ClerkConsole(system).run()


if __name__ == "__main__":
    main()
