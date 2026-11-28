from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from bus_checker.dashboard.data import in_list

DAY_TYPES = ("Weekday", "Weekend", "Holiday")


@dataclass(frozen=True)
class Filters:
    start: date
    end: date
    modes: tuple[str, ...] = ()
    day_types: tuple[str, ...] = ()

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def previous(self) -> Filters:
        """The equal-length period immediately before this one."""
        return replace(
            self,
            start=self.start - timedelta(days=self.days),
            end=self.start - timedelta(days=1),
        )

    def where(
        self,
        alias: str = "",
        *,
        date_column: str = "service_date",
        route_column: str | None = "route_key",
        mode_column: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """SQL predicate and parameters for the period, modes and day types."""
        prefix = f"{alias}." if alias else ""
        clauses = [f"{prefix}{date_column} BETWEEN :start AND :end"]
        params: dict[str, Any] = {"start": self.start, "end": self.end}
        if self.modes and (mode_column or route_column):
            # Only bind parameters the statement uses: DuckDB rejects unused ones.
            slots, values = in_list("mode", self.modes)
            params.update(values)
            if mode_column:
                clauses.append(f"{prefix}{mode_column} IN {slots}")
            else:
                clauses.append(
                    f"{prefix}{route_column} IN (SELECT route_key FROM marts.dim_routes WHERE mode IN {slots})"
                )
        if self.day_types and set(self.day_types) != set(DAY_TYPES):
            slots, values = in_list("day", self.day_types)
            params.update(values)
            clauses.append(
                f"{prefix}{date_column} IN (SELECT service_date FROM marts.dim_dates WHERE day_type IN {slots})"
            )
        return " AND ".join(clauses), params
