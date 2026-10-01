# AndrewIDs: iizanyib, ualijuni, lirumvak
"""
The SwiftLink Logistics shipment hierarchy from Assignment 1, reused and
improved for the Logistics Management Information System of Assignment 2.

Classes: Shipment, TrackedShipment, ExpressParcel, FragileParcel and
BulkFreight. Every class prices itself through calculate_cost(), so a
single loop over a mixed list charges each shipment by its own rule.

Module-level functions:
    validate_number() and validate_text() hold the checks that several
    setters share, and are reused by the ScanEvent and Invoice classes.
    build_shipment() turns a saved dictionary back into an object of the
    right class by reading its "type" key.

Nothing runs when the module is imported, so other modules can reuse these
classes without side effects.
"""

import math


def validate_number(value, description):
    """
    Checks that a value is a real, finite number before a rule compares it.

    Booleans are refused even though Python treats True as 1, and so are
    NaN and infinity, which float() happily accepts from typed text.

    Parameters: value : any, description : str naming the value in the
    message, for example "a weight".
    Returns: the value, unchanged.
    Raises: ValueError when the value is not a finite int or float.
    """
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise ValueError(f"{description} must be a number, got {value!r}")
    return value


def validate_text(value, description):
    """
    Checks that a value is text that is not blank, and trims its spaces.

    Parameters: value : any, description : str naming the value in the
    message, for example "a destination city".
    Returns: str, the text without leading or trailing spaces.
    Raises: ValueError when the value is not a string or is blank.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{description} must be non-blank text, "
                         f"got {value!r}")
    return value.strip()


class Shipment:
    """
    A consignment carried by SwiftLink Logistics.

    Holds the details every shipment has, what service was bought, and
    prices a plain shipment as weight multiplied by the base rate.

    Data members: _tracking_id, _sender_name, _recipient_name,
    _destination_city, __weight_kg (private), _base_rate_per_kg.
    Class variables: company_name, shipment_count, EDITABLE_FIELDS.
    """

    # Shared by every shipment object.
    company_name = "SwiftLink Logistics"
    shipment_count = 0

    # The fields that may be edited after registration
    EDITABLE_FIELDS = {
        "sender_name": str,
        "recipient_name": str,
        "destination_city": str,
        "weight_kg": float,
        "base_rate_per_kg": float
    }

    def __init__(self, tracking_id, sender_name, recipient_name,
                 destination_city, weight_kg, base_rate_per_kg):
        """
        Creates a shipment after checking every value it is given.

        Parameters: tracking_id : str, sender_name : str,
        recipient_name : str, destination_city : str, weight_kg : float,
        base_rate_per_kg : float.

        Returns: None.
        Raises: ValueError when any invalid value is provided.
        """
        # The identifier is checked here because it has no setter: the
        # identity of a shipment cannot be changed once it exists.

        if not Shipment.is_valid_tracking_id(tracking_id):
            raise ValueError(
                f"a tracking id must look like SL-0000, got '{tracking_id}'"
            )
        self._tracking_id = tracking_id

        # The setters contain the validation rules, so they are reused here
        # and each rule is written only once.
        self.set_sender_name(sender_name)
        self.set_recipient_name(recipient_name)
        self.set_destination_city(destination_city)
        self.set_weight_kg(weight_kg)
        self.set_base_rate_per_kg(base_rate_per_kg)

        # Runs last, so a rejected shipment is never counted.
        # Added to the class, so all shipments share one count.
        Shipment.shipment_count += 1

    @classmethod
    def get_shipment_count(cls):
        """
        Returns how many shipment objects have been accepted so far.
        Parameters: none.
        Returns: int.
        """
        return cls.shipment_count

    @classmethod
    def get_editable_fields(cls):
        """
        Returns the fields a clerk may edit on this class of shipment.
        Parameters: none.
        Returns: dict mapping each field name to the type it expects.
        """
        # A copy, so a caller cannot change the class's own table.
        return dict(cls.EDITABLE_FIELDS)

    @staticmethod
    def is_valid_tracking_id(tracking_id):
        """
        Checks that an identifier follows the correct format: the letters
        SL, a hyphen and four digits.
        Parameters: tracking_id : str.
        Returns: bool.
        """
        if not isinstance(tracking_id, str):
            return False
        if len(tracking_id) != 7:
            return False
        if tracking_id[:3] != "SL-":
            return False
        for character in tracking_id[3:]:
            if character not in "0123456789":
                return False
        return True

    def get_tracking_id(self):
        """
        Returns the tracking identifier of the shipment.
        Parameters: none.
        Returns: str.
        """
        return self._tracking_id

    def get_service_type(self):
        """
        Returns the name of the service bought, which is the class name.
        Parameters: none.
        Returns: str, for example "ExpressParcel".
        """
        return self.__class__.__name__

    def get_sender_name(self):
        """
        Returns the name of the sender.
        Parameters: none.
        Returns: str.
        """
        return self._sender_name

    def set_sender_name(self, sender_name):
        """
        Updates the name of the sender, which must not be blank.
        Parameters: sender_name : str.
        Returns: None.
        """
        # The sender decides whether the corporate discount applies, so an
        # empty name would silently cost a corporate customer its discount.
        self._sender_name = validate_text(sender_name, "a sender name")

    def get_recipient_name(self):
        """
        Returns the name of the recipient.
        Parameters: none.
        Returns: str.
        """
        return self._recipient_name

    def set_recipient_name(self, recipient_name):
        """
        Updates the name of the recipient, which must not be blank.
        Parameters: recipient_name : str.
        Returns: None.
        """
        self._recipient_name = validate_text(recipient_name,
                                             "a recipient name")

    def get_destination_city(self):
        """
        Returns the city the shipment is going to.
        Parameters: none.
        Returns: str.
        """
        return self._destination_city

    def set_destination_city(self, destination_city):
        """
        Updates the destination city, which must not be blank.
        Parameters: destination_city : str.
        Returns: None.
        """
        # The destination decides whether the remote area surcharge applies.
        self._destination_city = validate_text(destination_city,
                                               "a destination city")

    def get_weight_kg(self):
        """
        Returns the weight of the shipment in kilograms.
        Parameters: none.
        Returns: float.
        """
        return self.__weight_kg

    def set_weight_kg(self, weight_kg):
        """
        Updates the weight after checking it is above 0 and not more
        than 1000 kg.
        Parameters: weight_kg : float.
        Returns: None.
        """
        validate_number(weight_kg, "a weight")
        if weight_kg <= 0 or weight_kg > 1000:
            raise ValueError(
                "a weight must be above 0 and not more than 1000 kg, got "
                f"{weight_kg}"
            )
        self.__weight_kg = weight_kg

    def get_base_rate_per_kg(self):
        """
        Returns the rate charged per kilogram in RWF.
        Parameters: none.
        Returns: float.
        """
        return self._base_rate_per_kg

    def set_base_rate_per_kg(self, base_rate_per_kg):
        """
        Updates the rate per kilogram after checking it is above zero.
        Parameters: base_rate_per_kg : float.
        Returns: None.
        """
        validate_number(base_rate_per_kg, "a base rate")
        if base_rate_per_kg <= 0:
            raise ValueError(
                "a base rate must be greater than zero, got "
                f"{base_rate_per_kg}"
            )
        self._base_rate_per_kg = base_rate_per_kg

    def update_details(self, changes):
        """
        Applies one or more edits through the validating setters.

        Either every change is applied or none is: if a setter refuses a
        value, the changes already made are put back before the error is
        passed on, so the shipment is never left half updated.

        Parameters: changes : dict mapping an editable field name to its
        new value, for example {"weight_kg": 3.0}.
        Returns: None.
        Raises: ValueError when no change is given, a field cannot be
        edited, or a setter refuses a value.
        """
        if not changes:
            raise ValueError("no field was given to update")
        for field_name in changes:
            if field_name not in self.EDITABLE_FIELDS:
                editable = ", ".join(self.EDITABLE_FIELDS)
                raise ValueError(
                    f"'{field_name}' can not be edited on a "
                    f"{self.get_service_type()}; the editable fields are "
                    f"{editable}"
                )

        applied = []
        try:
            for field_name, new_value in changes.items():
                # Every editable field has a getter and a setter whose name
                # contains the field name, so both can be looked up from it.
                old_value = getattr(self, "get_" + field_name)()
                getattr(self, "set_" + field_name)(new_value)
                applied.append((field_name, old_value))
        except ValueError:
            # The old values passed validation once, so restoring them
            # through the same setters cannot fail.
            for field_name, old_value in reversed(applied):
                getattr(self, "set_" + field_name)(old_value)
            raise

    def calculate_cost(self):
        """
        Returns the price of a plain shipment, weight * base rate.
        Parameters: none.
        Returns: float.
        """
        return self.get_weight_kg() * self._base_rate_per_kg

    def display_details(self):
        """
        Prints the shipment summary and its price on the console.
        Parameters: none.
        Returns: None.
        """
        # Written once here, but each subclass prints and prices itself
        # correctly because __str__ and calculate_cost() are overridden.
        print(self)
        print(f"  Cost: {self.calculate_cost():,.2f} RWF")

    def __str__(self):
        """
        Returns a readable summary of the shipment.
        Parameters: none.
        Returns: str.
        """
        return (f"{self.get_service_type()} {self._tracking_id}"
                f" ({Shipment.company_name})"
                f"\n  Route: {self._sender_name} -> {self._recipient_name},"
                f" {self._destination_city}"
                f"\n  Weight: {self.get_weight_kg()} kg at "
                f"{self._base_rate_per_kg:,.2f} RWF/kg")

    def to_dict(self):
        """
        Returns the shipment as a dictionary that json.dump can write.
        Parameters: none.
        Returns: dict.
        """
        # "type" records the real class name, so build_shipment can
        # rebuild the right class when the file is read back.
        return {
            "type": self.get_service_type(),
            "tracking_id": self._tracking_id,
            "sender_name": self._sender_name,
            "recipient_name": self._recipient_name,
            "destination_city": self._destination_city,
            "weight_kg": self.get_weight_kg(),
            "base_rate_per_kg": self._base_rate_per_kg
        }


class TrackedShipment(Shipment):
    """
    A shipment that is scanned along its journey and insured against loss.

    Adds the declared value, the insurance rate and the delivery status, and
    charges an insurance premium on top of the base transport charge.

    Data members: _declared_value, _insurance_rate, _current_status.
    Class variables: ALLOWED_STATUSES, EDITABLE_FIELDS.
    """

    # The four status values a tracked shipment may have.
    ALLOWED_STATUSES = ("received", "in transit", "out for delivery",
                        "delivered")

    # current_status is not editable by hand: in the LMIS it is moved on by
    # the scan events recorded along the journey.
    EDITABLE_FIELDS = dict(Shipment.EDITABLE_FIELDS,
                           declared_value=float,
                           insurance_rate=float)

    def __init__(self, tracking_id, sender_name, recipient_name,
                 destination_city, weight_kg, base_rate_per_kg,
                 declared_value, insurance_rate, current_status="received"):
        """
        Creates a tracked shipment and checks the insurance details.

        Parameters: tracking_id : str, sender_name : str,
        recipient_name : str, destination_city : str, weight_kg : float,
        base_rate_per_kg : float, declared_value : float,
        insurance_rate : float, current_status : str.
        Returns: None.
        """
        # The new values are validated using setter methods before super()
        # runs, so an invalid one stops construction before the base class
        # counts the shipment.
        self.set_declared_value(declared_value)
        self.set_insurance_rate(insurance_rate)
        self.set_current_status(current_status)
        super().__init__(tracking_id, sender_name, recipient_name,
                         destination_city, weight_kg, base_rate_per_kg)

    def get_declared_value(self):
        """
        Returns the value the customer declared for the contents in RWF.
        Parameters: none.
        Returns: float.
        """
        return self._declared_value

    def set_declared_value(self, declared_value):
        """
        Updates the declared value after checking it is not negative.
        Parameters: declared_value : float.
        Returns: None.
        """
        validate_number(declared_value, "a declared value")
        if declared_value < 0:
            raise ValueError(
                f"a declared value can not be negative, got {declared_value}"
            )
        self._declared_value = declared_value

    def get_insurance_rate(self):
        """
        Returns the proportion of the declared value charged as insurance.
        Parameters: none.
        Returns: float.
        """
        return self._insurance_rate

    def set_insurance_rate(self, insurance_rate):
        """
        Updates the insurance rate after checking it lies between 0 and 0.05.
        Parameters: insurance_rate : float.
        Returns: None.
        """
        validate_number(insurance_rate, "an insurance rate")
        if insurance_rate < 0 or insurance_rate > 0.05:
            raise ValueError(
                "an insurance rate must be between 0 and 0.05, got "
                f"{insurance_rate}"
            )
        self._insurance_rate = insurance_rate

    def get_current_status(self):
        """
        Returns the current delivery status.
        Parameters: none.
        Returns: str.
        """
        return self._current_status

    def set_current_status(self, current_status):
        """
        Updates the delivery status, accepting any capitalisation.
        Parameters: current_status : str.
        Returns: None.
        """
        # The depot types the status manually so the case is not reliable.
        # It is compared and stored in lower case to keep it consistent.
        tidy_status = str(current_status).strip().lower()
        if tidy_status not in TrackedShipment.ALLOWED_STATUSES:
            raise ValueError(
                "a status must be received, in transit, out for delivery or "
                f"delivered, got '{current_status}'"
            )
        self._current_status = tidy_status

    def calculate_cost(self):
        """
        Returns the base transport charge plus the insurance premium.
        Parameters: none.
        Returns: float.
        """
        # Extend the inherited cost by adding the insurance premium.
        insurance_premium = self._insurance_rate * self._declared_value
        return super().calculate_cost() + insurance_premium

    def __str__(self):
        """
        Returns the shipment summary with the tracking details.
        Parameters: none.
        Returns: str.
        """
        return (super().__str__()
                + f"\n  Insured: {self._declared_value:,.2f} RWF declared at "
                  f"{self._insurance_rate:.2%}"
                + f"\n  Status: {self._current_status}")

    def to_dict(self):
        """
        Returns the shipment dictionary with the tracking fields added.
        Parameters: none.
        Returns: dict.
        """
        record = super().to_dict()
        record.update({
            "declared_value": self._declared_value,
            "insurance_rate": self._insurance_rate,
            "current_status": self._current_status
        })
        return record


class ExpressParcel(TrackedShipment):
    """
    A tracked parcel with a guaranteed delivery time.

    The faster the guarantee, the higher the priority fee. The fee is never
    supplied by the caller; it is looked up from the guarantee.

    Data members: _guaranteed_hours.
    Class variables: PRIORITY_FEES, EDITABLE_FIELDS.
    """

    # Fee in RWF for each guarantee, shared by every express parcel.
    PRIORITY_FEES = {
        6: 20000,
        12: 12000,
        24: 6000,
        48: 3000
    }

    EDITABLE_FIELDS = dict(TrackedShipment.EDITABLE_FIELDS,
                           guaranteed_hours=int)

    def __init__(self, tracking_id, sender_name, recipient_name,
                 destination_city, weight_kg, base_rate_per_kg,
                 declared_value, insurance_rate, current_status,
                 guaranteed_hours):
        """
        Creates an express parcel and checks the delivery guarantee.

        The parameters follow the parent's order and then add this class's
        own, which is the order the Assignment 2 specification uses.

        Parameters: tracking_id : str, sender_name : str,
        recipient_name : str, destination_city : str, weight_kg : float,
        base_rate_per_kg : float, declared_value : float,
        insurance_rate : float, current_status : str,
        guaranteed_hours : int.
        Returns: None.
        """
        self.set_guaranteed_hours(guaranteed_hours)
        super().__init__(tracking_id, sender_name, recipient_name,
                         destination_city, weight_kg, base_rate_per_kg,
                         declared_value, insurance_rate, current_status)

    def get_guaranteed_hours(self):
        """
        Returns the delivery guarantee in hours.
        Parameters: none.
        Returns: int.
        """
        return self._guaranteed_hours

    def set_guaranteed_hours(self, guaranteed_hours):
        """
        Updates the guarantee, which must be one the fee table offers.
        Parameters: guaranteed_hours : int.
        Returns: None.
        """
        # True == 1 in Python, so a boolean is refused explicitly.
        if (isinstance(guaranteed_hours, bool)
                or guaranteed_hours not in ExpressParcel.PRIORITY_FEES):
            raise ValueError(
                "a guarantee must be 6, 12, 24 or 48 hours, got "
                f"{guaranteed_hours}"
            )
        # int() turns an accepted 12.0 into 12, so the saved file is tidy.
        self._guaranteed_hours = int(guaranteed_hours)

    def get_priority_fee(self):
        """
        Returns the priority fee derived from guaranteed time, in RWF.
        Parameters: none.
        Returns: int.
        """
        return ExpressParcel.PRIORITY_FEES[self._guaranteed_hours]

    def calculate_cost(self):
        """
        Returns the tracked shipment cost plus the priority fee.
        Parameters: none.
        Returns: float.
        """
        return super().calculate_cost() + self.get_priority_fee()

    def __str__(self):
        """
        Returns the tracked summary with the express details added.
        Parameters: none.
        Returns: str.
        """
        return (super().__str__()
                + f"\n  Guarantee: {self._guaranteed_hours} hours"
                  f" (priority fee {self.get_priority_fee():,.2f} RWF)")

    def to_dict(self):
        """
        Returns the tracked dictionary with the guarantee added.
        Parameters: none.
        Returns: dict.
        """
        record = super().to_dict()
        record["guaranteed_hours"] = self._guaranteed_hours
        return record


class FragileParcel(TrackedShipment):
    """
    A tracked parcel that needs careful handling and purpose-built packaging.

    Adds a handling surcharge of 15% of the base transport charge and a fixed
    packaging fee.

    Data members: _handling_class, _packaging_fee.
    Class variables: ALLOWED_HANDLING_CLASSES, HANDLING_SURCHARGE_RATE,
    EDITABLE_FIELDS.
    """

    ALLOWED_HANDLING_CLASSES = ("glass", "electronics", "artwork")
    HANDLING_SURCHARGE_RATE = 0.15

    EDITABLE_FIELDS = dict(TrackedShipment.EDITABLE_FIELDS,
                           handling_class=str,
                           packaging_fee=float)

    def __init__(self, tracking_id, sender_name, recipient_name,
                 destination_city, weight_kg, base_rate_per_kg,
                 declared_value, insurance_rate, current_status,
                 handling_class, packaging_fee):
        """
        Creates a fragile parcel and checks the handling and packaging values.

        The parameters follow the parent's order and then add this class's
        own, matching ExpressParcel.

        Parameters: tracking_id : str, sender_name : str,
        recipient_name : str, destination_city : str, weight_kg : float,
        base_rate_per_kg : float, declared_value : float,
        insurance_rate : float, current_status : str, handling_class : str,
        packaging_fee : float.
        Returns: None.
        """
        self.set_handling_class(handling_class)
        self.set_packaging_fee(packaging_fee)
        super().__init__(tracking_id, sender_name, recipient_name,
                         destination_city, weight_kg, base_rate_per_kg,
                         declared_value, insurance_rate, current_status)

    def get_handling_class(self):
        """
        Returns the handling class of the parcel.
        Parameters: none.
        Returns: str.
        """
        return self._handling_class

    def set_handling_class(self, handling_class):
        """
        Updates the handling class, accepting any capitalisation.
        Parameters: handling_class : str.
        Returns: None.
        """
        tidy_class = str(handling_class).strip().lower()
        if tidy_class not in FragileParcel.ALLOWED_HANDLING_CLASSES:
            raise ValueError(
                "a handling class must be glass, electronics or artwork, got "
                f"'{handling_class}'"
            )
        self._handling_class = tidy_class

    def get_packaging_fee(self):
        """
        Returns the fixed charge for the protective packaging in RWF.
        Parameters: none.
        Returns: float.
        """
        return self._packaging_fee

    def set_packaging_fee(self, packaging_fee):
        """
        Updates the packaging fee after checking it is not negative.
        Parameters: packaging_fee : float.
        Returns: None.
        """
        validate_number(packaging_fee, "a packaging fee")
        if packaging_fee < 0:
            raise ValueError(
                f"a packaging fee must not be negative, got {packaging_fee}"
            )
        self._packaging_fee = packaging_fee

    def calculate_cost(self):
        """
        Returns the tracked cost plus the handling surcharge and packaging.
        Parameters: none.
        Returns: float.
        """
        # The surcharge is 15% of the weight times the rate, not 15% of the
        # tracked cost, so the insurance premium is left out of it.
        base_transport_charge = (self.get_weight_kg()
                                 * self.get_base_rate_per_kg())
        handling_surcharge = (FragileParcel.HANDLING_SURCHARGE_RATE
                              * base_transport_charge)
        return (super().calculate_cost() + handling_surcharge
                + self._packaging_fee)

    def __str__(self):
        """
        Returns the tracked summary with the fragile details added.
        Parameters: none.
        Returns: str.
        """
        return (super().__str__()
                + f"\n  Handling: {self._handling_class}"
                  f" (packaging fee {self._packaging_fee:,.2f} RWF)")

    def to_dict(self):
        """
        Returns the tracked dictionary with the fragile fields added.
        Parameters: none.
        Returns: dict.
        """
        record = super().to_dict()
        record.update({
            "handling_class": self._handling_class,
            "packaging_fee": self._packaging_fee
        })
        return record


class BulkFreight(Shipment):
    """
    A palletised consignment priced on space as much as on weight.

    The customer pays whichever is greater, the weight charge or the volume
    charge, and a handling fee for every pallet.

    Data members: _pallet_count, _volume_m3.
    Class variables: VOLUMETRIC_RATE_PER_M3, PALLET_HANDLING_FEE,
    EDITABLE_FIELDS.
    """

    VOLUMETRIC_RATE_PER_M3 = 25000
    PALLET_HANDLING_FEE = 2000

    EDITABLE_FIELDS = dict(Shipment.EDITABLE_FIELDS,
                           pallet_count=int,
                           volume_m3=float)

    def __init__(self, tracking_id, sender_name, recipient_name,
                 destination_city, weight_kg, base_rate_per_kg, pallet_count,
                 volume_m3):
        """
        Creates a bulk consignment and checks the pallets and the volume.

        Parameters: tracking_id : str, sender_name : str,
        recipient_name : str, destination_city : str, weight_kg : float,
        base_rate_per_kg : float, pallet_count : int, volume_m3 : float.
        Returns: None.
        """
        self.set_pallet_count(pallet_count)
        self.set_volume_m3(volume_m3)
        super().__init__(tracking_id, sender_name, recipient_name,
                         destination_city, weight_kg, base_rate_per_kg)

    def get_pallet_count(self):
        """
        Returns the number of pallets in the consignment.
        Parameters: none.
        Returns: int.
        """
        return self._pallet_count

    def set_pallet_count(self, pallet_count):
        """
        Updates the pallet count, a whole number between 1 and 20 inclusive.
        Parameters: pallet_count : int.
        Returns: None.
        """
        validate_number(pallet_count, "a pallet count")
        if pallet_count != int(pallet_count):
            raise ValueError(
                f"a pallet count must be a whole number, got {pallet_count}"
            )
        if pallet_count < 1 or pallet_count > 20:
            raise ValueError(
                f"a pallet count must be between 1 and 20, got {pallet_count}"
            )
        self._pallet_count = int(pallet_count)

    def get_volume_m3(self):
        """
        Returns the space the consignment occupies in cubic metres.
        Parameters: none.
        Returns: float.
        """
        return self._volume_m3

    def set_volume_m3(self, volume_m3):
        """
        Updates the volume after checking it is greater than zero.
        Parameters: volume_m3 : float.
        Returns: None.
        """
        validate_number(volume_m3, "a volume")
        if volume_m3 <= 0:
            raise ValueError(
                f"a volume must be greater than zero, got {volume_m3}"
            )
        self._volume_m3 = volume_m3

    def calculate_cost(self):
        """
        Returns the greater of the weight and volume charges plus pallet fees.
        Parameters: none.
        Returns: float.
        """
        # This override replaces the inherited rule rather than extending it:
        # bulk freight is not priced by weight alone, so super() would give
        # only one of the two charges that have to be compared.
        weight_charge = self.get_weight_kg() * self.get_base_rate_per_kg()
        volume_charge = self._volume_m3 * BulkFreight.VOLUMETRIC_RATE_PER_M3
        pallet_charge = self._pallet_count * BulkFreight.PALLET_HANDLING_FEE
        return max(weight_charge, volume_charge) + pallet_charge

    def __str__(self):
        """
        Returns the shipment summary with the bulk freight details added.
        Parameters: none.
        Returns: str.
        """
        return (super().__str__()
                + f"\n  Load: {self._pallet_count} pallets,"
                  f" {self._volume_m3} m3")

    def to_dict(self):
        """
        Returns the shipment dictionary with the bulk freight fields added.
        Parameters: none.
        Returns: dict.
        """
        record = super().to_dict()
        record.update({
            "pallet_count": self._pallet_count,
            "volume_m3": self._volume_m3
        })
        return record


# Every class a saved "type" key may name. A new service only has to be
# added here to be saved and loaded like the others.
SHIPMENT_CLASSES = {
    "Shipment": Shipment,
    "TrackedShipment": TrackedShipment,
    "ExpressParcel": ExpressParcel,
    "FragileParcel": FragileParcel,
    "BulkFreight": BulkFreight
}


def build_shipment(record):
    """
    Rebuilds one shipment object from a dictionary written by to_dict().

    Parameters: record : dict containing a "type" key and the saved
    attributes.
    Returns: a Shipment object of the class named by "type".
    Raises: KeyError when "type" is missing, ValueError when the type is
    unknown or a value breaks its rule, TypeError when an attribute is
    missing or unexpected.
    """
    # The "type" key is what tells an ExpressParcel from a FragileParcel once
    # the objects have become plain dictionaries in a file.
    shipment_type = record["type"]
    if shipment_type not in SHIPMENT_CLASSES:
        raise ValueError(f"unknown shipment type '{shipment_type}'")

    # to_dict() uses the constructor's parameter names as its keys, so the
    # saved values can be passed back by keyword. Passing them by name
    # rather than by position means a change in parameter order can never
    # silently put a value into the wrong attribute.
    attributes = {key: value for key, value in record.items()
                  if key != "type"}
    return SHIPMENT_CLASSES[shipment_type](**attributes)
