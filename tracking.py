# AndrewIDs: iizanyib, ualijuni, lirumvak
"""
Journey tracking for the SwiftLink Logistics MIS.

Defines ScanEvent: one scan of one shipment at one point in the depot
network. A scan refers to its shipment by tracking identifier rather than
holding the shipment object, so the LogisticsMIS stays the single owner of
every record.

Timestamps are stored as text in the form YYYY-MM-DD HH:MM and converted to
datetime objects only when arithmetic is needed. Nothing runs on import.
"""

from datetime import datetime

from shipments import Shipment, TrackedShipment, validate_text

# Column width used when a scan is printed as one line of a table.
LOCATION_WIDTH = 18


class ScanEvent:
    """
    One scan of a shipment: which shipment, when, where and in what status.

    A scan records something that has already happened, so it has getters
    but no setters. A wrong scan is dealt with by recording a new one, never
    by rewriting history.

    Data members: _tracking_id, _timestamp (text, YYYY-MM-DD HH:MM),
    _location, _status.
    Class variables: TIMESTAMP_FORMAT, DATE_FORMAT, ALLOWED_STATUSES,
    DELIVERED.
    """

    TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"
    DATE_FORMAT = "%Y-%m-%d"

    # The same four statuses a TrackedShipment may hold. Reusing the tuple
    # instead of copying it means the two lists can never disagree.
    ALLOWED_STATUSES = TrackedShipment.ALLOWED_STATUSES
    DELIVERED = "delivered"

    def __init__(self, tracking_id, timestamp, location, status):
        """
        Creates a scan after validating every value it is given.

        Parameters: tracking_id : str, timestamp : str in the form
        YYYY-MM-DD HH:MM, location : str, status : str.
        Returns: None.
        Raises: ValueError when the tracking id is malformed, the timestamp
        cannot be parsed, the location is blank or the status is not one of
        the four allowed values.
        """
        # The same format rule as the shipment it refers to, reused from
        # the Assignment 1 static method rather than written again.
        if not Shipment.is_valid_tracking_id(tracking_id):
            raise ValueError(
                f"a tracking id must look like SL-0000, got '{tracking_id}'"
            )
        # Parsing is the validation: strptime raises when the text is wrong.
        moment = ScanEvent.parse_timestamp(timestamp)
        location = validate_text(location, "a scan location")
        status = ScanEvent.normalise_status(status)

        self._tracking_id = tracking_id
        # Stored in one canonical form, so "2026-9-14 8:30" and
        # "2026-09-14 08:30" are saved and compared identically.
        self._timestamp = moment.strftime(ScanEvent.TIMESTAMP_FORMAT)
        self._location = location
        self._status = status

    @staticmethod
    def parse_timestamp(text):
        """
        Converts timestamp text in the form YYYY-MM-DD HH:MM to a datetime.
        Parameters: text : str.
        Returns: datetime.
        Raises: ValueError, with a message naming the expected format.
        """
        try:
            return datetime.strptime(str(text).strip(),
                                     ScanEvent.TIMESTAMP_FORMAT)
        except ValueError:
            # strptime's own message is cryptic, so a clearer one replaces
            # it; "from None" hides the original from the traceback.
            raise ValueError(
                f"'{text}' is not a valid timestamp, expected "
                "YYYY-MM-DD HH:MM"
            ) from None

    @staticmethod
    def parse_date(text):
        """
        Converts date text in the form YYYY-MM-DD to a date.
        Parameters: text : str.
        Returns: datetime.date.
        Raises: ValueError, with a message naming the expected format.
        """
        try:
            return datetime.strptime(str(text).strip(),
                                     ScanEvent.DATE_FORMAT).date()
        except ValueError:
            raise ValueError(
                f"'{text}' is not a valid date, expected YYYY-MM-DD"
            ) from None

    @staticmethod
    def normalise_status(status):
        """
        Checks a scan status against the permitted set, ignoring case.
        Parameters: status : str.
        Returns: str, the status in lower case.
        Raises: ValueError when the status is not one of the four allowed.
        """
        tidy_status = str(status).strip().lower()
        if tidy_status not in ScanEvent.ALLOWED_STATUSES:
            raise ValueError(
                "a scan status must be received, in transit, out for "
                f"delivery or delivered, got '{status}'"
            )
        return tidy_status

    def get_tracking_id(self):
        """
        Returns the tracking identifier of the shipment that was scanned.
        Parameters: none.
        Returns: str.
        """
        return self._tracking_id

    def get_timestamp(self):
        """
        Returns when the scan happened, as YYYY-MM-DD HH:MM text.
        Parameters: none.
        Returns: str.
        """
        return self._timestamp

    def get_location(self):
        """
        Returns where the shipment was scanned.
        Parameters: none.
        Returns: str.
        """
        return self._location

    def get_status(self):
        """
        Returns the status recorded by the scan.
        Parameters: none.
        Returns: str.
        """
        return self._status

    def get_datetime(self):
        """
        Returns the timestamp as a datetime object, ready for arithmetic,
        so other classes never have to parse the text themselves.
        Parameters: none.
        Returns: datetime.
        """
        return datetime.strptime(self._timestamp, ScanEvent.TIMESTAMP_FORMAT)

    def get_date(self):
        """
        Returns the calendar day on which the scan happened.
        Parameters: none.
        Returns: datetime.date.
        """
        return self.get_datetime().date()

    def is_delivery(self):
        """
        Reports whether this scan recorded the delivery of the shipment.
        Parameters: none.
        Returns: bool.
        """
        return self._status == ScanEvent.DELIVERED

    def format_line(self, show_tracking_id=True):
        """
        Returns the scan as one aligned line of a table.

        Parameters: show_tracking_id : bool, False when every line of the
        table belongs to the same shipment.
        Returns: str.
        """
        line = (f"{self._timestamp}  {self._location:<{LOCATION_WIDTH}}"
                f"{self._status}")
        if show_tracking_id:
            line = f"{self._tracking_id}  {line}"
        return line

    def __str__(self):
        """
        Returns a readable one-line summary of the scan.
        Parameters: none.
        Returns: str.
        """
        return self.format_line()

    def to_dict(self):
        """
        Returns the scan as a dictionary that json.dump can write.
        Parameters: none.
        Returns: dict.
        """
        # The "type" key follows the Assignment 1 convention, so a saved
        # record always says which class produced it.
        return {
            "type": self.__class__.__name__,
            "tracking_id": self._tracking_id,
            "timestamp": self._timestamp,
            "location": self._location,
            "status": self._status
        }

    @classmethod
    def from_dict(cls, record):
        """
        Rebuilds a scan from a dictionary written by to_dict().
        Parameters: record : dict.
        Returns: ScanEvent.
        Raises: KeyError when a field is missing, ValueError when the type
        key names another class or a value is invalid.
        """
        if record["type"] != cls.__name__:
            raise ValueError(
                f"expected a {cls.__name__} record, got '{record['type']}'"
            )
        return cls(record["tracking_id"], record["timestamp"],
                   record["location"], record["status"])
