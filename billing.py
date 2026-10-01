# AndrewIDs: iizanyib, ualijuni, lirumvak
"""
Customer invoicing for the SwiftLink Logistics MIS.

Defines Invoice, which holds what one customer owes for one shipment,
broken down so the customer can see how the total was reached. Every
billing and taxation rule of the system lives here, as Invoice class
variables:

    FUEL_LEVY_RATE            6% of the transport charge
    REMOTE_AREA_SURCHARGE     flat 8,000 RWF to a remote district
    CORPORATE_DISCOUNT_RATE   10% of the transport charge, corporate only
    VAT_RATE                  18% of the subtotal, applied after discount

Which districts are remote and which senders are corporate accounts is
policy held by the LogisticsMIS, which tells each invoice when it is raised.

Nothing runs on import.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from shipments import Shipment, validate_number, validate_text

# Layout of an invoice line: a label, then the amount right-aligned.
LABEL_WIDTH = 34
AMOUNT_WIDTH = 16
RULE = "-" * (LABEL_WIDTH + AMOUNT_WIDTH)

CENT = Decimal("0.01")


def to_decimal(amount):
    """
    Converts an amount to a Decimal holding exactly the digits it prints as.

    Going through repr() matters: the float 0.18 is stored in binary as
    0.17999999999999999334, but its repr is '0.18', which is the rate the
    company actually means.

    Parameters: amount : int, float or Decimal.
    Returns: Decimal.
    """
    if isinstance(amount, Decimal):
        return amount
    return Decimal(repr(amount))


def round_money(amount):
    """
    Rounds an amount of money to the nearest cent, halves rounding up.

    Parameters: amount : int, float or Decimal.
    Returns: float, with at most two decimal places.
    """
    return float(to_decimal(amount).quantize(CENT, rounding=ROUND_HALF_UP))


def format_amount_line(label, amount):
    """
    Formats one line of a money breakdown: the label, then the amount.

    Shared by the invoice and by the revenue summary in lmis.py, so the two
    always line up the same way.

    Parameters: label : str, amount : float.
    Returns: str.
    """
    return f"  {label:<{LABEL_WIDTH}}{amount:>{AMOUNT_WIDTH},.2f}"


class Invoice:
    """
    What one customer owes for one shipment, broken down by component.

    The transport charge is taken from the shipment's own calculate_cost()
    when the invoice is raised and is never worked out here. Every other
    figure is derived from it and from two policy decisions made by the
    LogisticsMIS: whether the destination is remote and whether the sender
    is a corporate account. Like the priority fee in Assignment 1, the
    derived figures are computed when asked for, not stored.

    An invoice is a document that has been issued, so it has getters but no
    setters; a correction is made by raising the invoice again.

    Data members: _tracking_id, _customer_name, _issue_date (text,
    YYYY-MM-DD), _transport_charge, _is_remote, _is_corporate.
    Class variables: FUEL_LEVY_RATE, REMOTE_AREA_SURCHARGE,
    CORPORATE_DISCOUNT_RATE, VAT_RATE, DATE_FORMAT, MONTH_FORMAT.
    """

    # The billing and taxation rules. They are company policy and law, the
    # same for every invoice, so they belong to the class.
    FUEL_LEVY_RATE = 0.06
    REMOTE_AREA_SURCHARGE = 8000
    CORPORATE_DISCOUNT_RATE = 0.10
    VAT_RATE = 0.18

    DATE_FORMAT = "%Y-%m-%d"
    MONTH_FORMAT = "%Y-%m"

    def __init__(self, tracking_id, customer_name, issue_date,
                 transport_charge, is_remote, is_corporate):
        """
        Creates an invoice after validating every value it is given.

        Use Invoice.for_shipment() to raise an invoice for a shipment; this
        constructor also serves to rebuild a saved invoice.

        Parameters: tracking_id : str, customer_name : str,
        issue_date : str in the form YYYY-MM-DD, transport_charge : float,
        is_remote : bool, is_corporate : bool.
        Returns: None.
        Raises: ValueError when any value breaks its rule.
        """
        if not Shipment.is_valid_tracking_id(tracking_id):
            raise ValueError(
                f"a tracking id must look like SL-0000, got '{tracking_id}'"
            )
        customer_name = validate_text(customer_name, "a customer name")
        issue_date = Invoice.parse_date(issue_date)
        validate_number(transport_charge, "a transport charge")
        if transport_charge < 0:
            raise ValueError(
                "a transport charge must not be negative, got "
                f"{transport_charge}"
            )
        # A JSON file could hold "yes" or 1 here; only true or false is
        # a real answer to "does the surcharge apply?".
        for flag_name, flag in (("is_remote", is_remote),
                                ("is_corporate", is_corporate)):
            if not isinstance(flag, bool):
                raise ValueError(f"{flag_name} must be True or False, "
                                 f"got {flag!r}")

        self._tracking_id = tracking_id
        self._customer_name = customer_name
        self._issue_date = issue_date
        # Rounding to the cent is not recomputing: it records the charge in
        # the unit money is actually paid in.
        self._transport_charge = round_money(transport_charge)
        self._is_remote = is_remote
        self._is_corporate = is_corporate

    @classmethod
    def for_shipment(cls, shipment, is_remote, is_corporate,
                     issue_date=None):
        """
        Raises the invoice for a shipment.

        The transport charge comes from shipment.calculate_cost(). Whichever
        class the shipment belongs to, its own pricing rule runs, so one
        call prices a Shipment, an ExpressParcel or a BulkFreight correctly.

        Parameters: shipment : Shipment, is_remote : bool,
        is_corporate : bool, issue_date : str in the form YYYY-MM-DD, or
        None for today.
        Returns: Invoice.
        Raises: TypeError when shipment is not a Shipment, ValueError when
        the date or a flag is invalid.
        """
        if not isinstance(shipment, Shipment):
            raise TypeError("an invoice can only be raised for a Shipment, "
                            f"got {type(shipment).__name__}")
        if issue_date is None:
            issue_date = date.today().strftime(cls.DATE_FORMAT)
        # The invoice keeps the tracking id, not the shipment object.
        return cls(shipment.get_tracking_id(), shipment.get_sender_name(),
                   issue_date, shipment.calculate_cost(), is_remote,
                   is_corporate)

    @staticmethod
    def parse_date(text):
        """
        Checks date text in the form YYYY-MM-DD and returns it tidied.
        Parameters: text : str.
        Returns: str, the date as YYYY-MM-DD.
        Raises: ValueError, with a message naming the expected format.
        """
        try:
            parsed = datetime.strptime(str(text).strip(), Invoice.DATE_FORMAT)
        except ValueError:
            raise ValueError(
                f"'{text}' is not a valid date, expected YYYY-MM-DD"
            ) from None
        return parsed.strftime(Invoice.DATE_FORMAT)

    @staticmethod
    def parse_month(text):
        """
        Checks month text in the form YYYY-MM and returns it tidied.
        Parameters: text : str.
        Returns: str, the month as YYYY-MM.
        Raises: ValueError, with a message naming the expected format.
        """
        try:
            parsed = datetime.strptime(str(text).strip(),
                                       Invoice.MONTH_FORMAT)
        except ValueError:
            raise ValueError(
                f"'{text}' is not a valid month, expected YYYY-MM"
            ) from None
        return parsed.strftime(Invoice.MONTH_FORMAT)

    def get_tracking_id(self):
        """
        Returns the tracking identifier of the shipment this invoice bills.
        Parameters: none.
        Returns: str.
        """
        return self._tracking_id

    def get_invoice_number(self):
        """
        Returns the invoice number, derived from the tracking id.
        Parameters: none.
        Returns: str, for example "INV-3120".
        """
        # One invoice per shipment, so the tracking digits identify it.
        return "INV-" + self._tracking_id[3:]

    def get_customer_name(self):
        """
        Returns the name of the customer billed, the shipment's sender.
        Parameters: none.
        Returns: str.
        """
        return self._customer_name

    def get_issue_date(self):
        """
        Returns the date the invoice was issued, as YYYY-MM-DD text.
        Parameters: none.
        Returns: str.
        """
        return self._issue_date

    def get_billing_month(self):
        """
        Returns the month the invoice counts towards, as YYYY-MM text.
        Parameters: none.
        Returns: str.
        """
        return self._issue_date[:7]

    def is_remote(self):
        """
        Reports whether the remote area surcharge applies.
        Parameters: none.
        Returns: bool.
        """
        return self._is_remote

    def is_corporate(self):
        """
        Reports whether the corporate discount applies.
        Parameters: none.
        Returns: bool.
        """
        return self._is_corporate

    def get_transport_charge(self):
        """
        Returns the transport charge taken from the shipment, in RWF.
        Parameters: none.
        Returns: float.
        """
        return self._transport_charge

    def _share_of_transport(self, rate):
        """
        Returns a percentage of the transport charge, rounded to the cent.
        Parameters: rate : float, for example 0.06.
        Returns: float.
        """
        return round_money(to_decimal(self._transport_charge)
                           * to_decimal(rate))

    def get_fuel_levy(self):
        """
        Returns the fuel levy: 6% of the transport charge.
        Parameters: none.
        Returns: float.
        """
        return self._share_of_transport(Invoice.FUEL_LEVY_RATE)

    def get_remote_surcharge(self):
        """
        Returns the flat remote area surcharge, or 0 when it does not apply.
        Parameters: none.
        Returns: float.
        """
        if self._is_remote:
            return float(Invoice.REMOTE_AREA_SURCHARGE)
        return 0.0

    def get_corporate_discount(self):
        """
        Returns the corporate discount: 10% of the transport charge for a
        corporate account, otherwise 0.
        Parameters: none.
        Returns: float, a positive amount that is subtracted.
        """
        if self._is_corporate:
            return self._share_of_transport(Invoice.CORPORATE_DISCOUNT_RATE)
        return 0.0

    def get_subtotal(self):
        """
        Returns transport + fuel levy + surcharge - discount.
        Parameters: none.
        Returns: float.
        """
        subtotal = (to_decimal(self._transport_charge)
                    + to_decimal(self.get_fuel_levy())
                    + to_decimal(self.get_remote_surcharge())
                    - to_decimal(self.get_corporate_discount()))
        return round_money(subtotal)

    def get_vat(self):
        """
        Returns the VAT: 18% of the subtotal, so it applies after discount.
        Parameters: none.
        Returns: float.
        """
        return round_money(to_decimal(self.get_subtotal())
                           * to_decimal(Invoice.VAT_RATE))

    def get_total(self):
        """
        Returns the total payable: subtotal + VAT.
        Parameters: none.
        Returns: float.
        """
        return round_money(to_decimal(self.get_subtotal())
                           + to_decimal(self.get_vat()))

    def __str__(self):
        """
        Returns the invoice broken down by component, as the customer sees it.
        Parameters: none.
        Returns: str.
        """
        discount = self.get_corporate_discount()
        # A discount is shown as a deduction, but never as "-0.00".
        shown_discount = -discount if discount else 0.0
        lines = [
            f"Invoice {self.get_invoice_number()} for {self._tracking_id}",
            f"  Billed to {self._customer_name}, issued {self._issue_date}",
            format_amount_line("Transport charge", self._transport_charge),
            format_amount_line(f"Fuel levy ({Invoice.FUEL_LEVY_RATE:.0%})",
                               self.get_fuel_levy()),
            format_amount_line("Remote area surcharge",
                               self.get_remote_surcharge()),
            format_amount_line(
                f"Corporate discount ({Invoice.CORPORATE_DISCOUNT_RATE:.0%})",
                shown_discount),
            "  " + RULE,
            format_amount_line("Subtotal", self.get_subtotal()),
            format_amount_line(f"VAT ({Invoice.VAT_RATE:.0%})",
                               self.get_vat()),
            format_amount_line("Total payable (RWF)", self.get_total())
        ]
        return "\n".join(lines)

    def to_dict(self):
        """
        Returns the invoice as a dictionary that json.dump can write.
        Parameters: none.
        Returns: dict.
        """
        # Only what cannot be recomputed is saved. The levy, discount,
        # subtotal, VAT and total all follow from these values.
        return {
            "type": self.__class__.__name__,
            "tracking_id": self._tracking_id,
            "customer_name": self._customer_name,
            "issue_date": self._issue_date,
            "transport_charge": self._transport_charge,
            "is_remote": self._is_remote,
            "is_corporate": self._is_corporate
        }

    @classmethod
    def from_dict(cls, record):
        """
        Rebuilds an invoice from a dictionary written by to_dict().
        Parameters: record : dict.
        Returns: Invoice.
        Raises: KeyError when a field is missing, ValueError when the type
        key names another class or a value is invalid.
        """
        if record["type"] != cls.__name__:
            raise ValueError(
                f"expected an {cls.__name__} record, got '{record['type']}'"
            )
        return cls(record["tracking_id"], record["customer_name"],
                   record["issue_date"], record["transport_charge"],
                   record["is_remote"], record["is_corporate"])
