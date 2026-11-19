"""State shared by the demo setup and workflow functions."""

from dataclasses import dataclass, field
from typing import Any, NamedTuple


@dataclass
class ContextState:
    """Context records and runtime values for one demo build."""

    rng: Any = field(init=False)
    today: Any = field(init=False)
    admin: Any = field(init=False)
    root_env: Any = field(init=False)
    env: Any = field(init=False)
    company: Any = field(init=False)
    keep: Any = field(init=False)


@dataclass
class AccountingState:
    """Accounting records and runtime values for one demo build."""

    bank: Any = field(init=False)
    cash: Any = field(init=False)
    accounts: Any = field(init=False)
    main_wh: Any = field(init=False)
    misc: Any = field(init=False)
    asset_accounts: Any = field(init=False)


@dataclass
class PartnersState:
    """Partners records and runtime values for one demo build."""

    engineers: Any = field(init=False)
    owners: Any = field(init=False)
    consultants: Any = field(init=False)
    vendors: Any = field(init=False)
    subcontractors: Any = field(init=False)
    banks: Any = field(init=False)


@dataclass
class EquipmentState:
    """Equipment records and runtime values for one demo build."""

    machines_free: Any = field(init=False)
    machine_available: Any = field(init=False)
    machines: Any = field(init=False)
    rented: Any = field(init=False)
    rented_free: Any = field(init=False)
    rental_service: Any = field(init=False)
    products: Any = field(init=False)


@dataclass
class FleetState:
    """Fleet records and runtime values for one demo build."""

    drivers: Any = field(init=False)
    vehicles: Any = field(init=False)
    driver_employees: Any = field(init=False)


class ProjectSpec(NamedTuple):
    """An existing project specification, including its original tuple order."""

    name: str
    city: str
    template: str
    state: str
    months_ago: int
    duration: int
    scale: float
    owner_index: int
    from_tender: bool


class DateRange(NamedTuple):
    """Inclusive dates for one demo workflow period."""

    start: Any
    end: Any


class ProgressStep(NamedTuple):
    """Values shared by owner and subcontractor invoices for one progress step."""

    date: Any
    fraction: float
    full: bool
    last: bool
    number: int


class TripContext(NamedTuple):
    """Shared lookup records and date for one fleet trip sheet."""

    projects: Any
    transport_types: tuple
    date_from: Any
