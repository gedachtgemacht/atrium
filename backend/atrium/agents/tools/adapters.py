"""Interfaces to company systems, with mock implementations.

A real installation replaces the mocks with adapters to its own ERP, dispatch
and contract systems. Only these interfaces are part of V1.
"""

from dataclasses import dataclass
from typing import Protocol


def route_key(origin: str, destination: str) -> str:
    return f"{origin.strip().lower()}>{destination.strip().lower()}"


@dataclass
class RoutePrice:
    origin: str
    destination: str
    price: float | None  # last year's contract price per load, None for a new route
    distance_km: float
    rate_per_km: float


class ErpAdapter(Protocol):
    def prices(self, routes: list[tuple[str, str]], year: int) -> list[RoutePrice]: ...


class DispatchAdapter(Protocol):
    def free_slots(self, origin: str, destination: str, month: str) -> int: ...


@dataclass
class ContractTerms:
    customer: str
    contract: str
    year: int
    payment_days: int
    subcontractor_markup_pct: float
    routes: list[dict]  # [{"origin", "destination", "loads_per_month"}]


class ContractsAdapter(Protocol):
    def terms(self, customer: str) -> ContractTerms | None: ...


class MockErp:
    RATE_PER_KM = 3.47
    PRICES_2026 = {route_key("Dortmund", "Hamm"): 400.0, route_key("Dortmund", "Münster"): 454.0}
    DISTANCES = {"hamm": 35.0, "münster": 70.0, "munster": 70.0, "erfurt": 330.0}

    def prices(self, routes, year):
        out = []
        for origin, destination in routes:
            out.append(
                RoutePrice(
                    origin=origin, destination=destination,
                    price=self.PRICES_2026.get(route_key(origin, destination)),
                    distance_km=self.DISTANCES.get(destination.strip().lower(), 250.0),
                    rate_per_km=self.RATE_PER_KM,
                )
            )
        return out


class MockDispatch:
    def free_slots(self, origin, destination, month):
        if destination.strip().lower() == "erfurt":
            return 4
        return 40


class MockContracts:
    def terms(self, customer):
        if "hollmann" not in customer.lower():
            return None
        return ContractTerms(
            customer="Hollmann Bau GmbH", contract="Contract 2026", year=2026, payment_days=30, subcontractor_markup_pct=8.0,
            routes=[
                {"origin": "Dortmund", "destination": "Hamm", "loads_per_month": 18},
                {"origin": "Dortmund", "destination": "Münster", "loads_per_month": 14},
            ],
        )
