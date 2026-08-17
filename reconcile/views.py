import logging
from decimal import Decimal
from typing import Optional

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .compare import ALL_REASONS, disagreements_from_queryset
from .models import Location, SystemARecord, SystemBEntry

logger = logging.getLogger("reconcile.views")


def _decimal_to_json(value: Optional[Decimal]):
    """Serialize a ``Decimal`` as a string (or ``None``).

    Why a string and not a JSON number: JSON numbers are IEEE floats, which would
    reintroduce exactly the rounding error we used ``Decimal`` to avoid. Sending
    the value as a string preserves the precise amount end-to-end, and the plain
    table UI just renders it as text anyway.
    """
    if value is None:
        return None
    return str(value)


class OrgListView(APIView):
    """List the distinct orgs so the UI can populate its tenant switcher.

    Why derive orgs from ``Location`` rather than a hardcoded list: locations.csv
    is the single source of the org mapping, so the dropdown always reflects the
    data actually loaded. ``.distinct()`` collapses the many locations per org.
    """

    def get(self, request):
        orgs = (
            Location.objects.order_by("org_id")
            .values_list("org_id", flat=True)
            .distinct()
        )
        org_list = list(orgs)
        logger.debug("OrgListView: returning %d orgs", len(org_list))
        return Response([{"org_id": org_id} for org_id in org_list])


class DisagreementListView(APIView):
    """Serve the org-scoped, filterable, sortable list of disagreements.

    Why a plain ``APIView`` instead of a ``ModelViewSet``/serializer: a
    disagreement is a *computed* result, not a stored row, so there is no queryset
    to CRUD. Hand-shaping the response keeps the contract obvious and lets the
    computed dataclasses flow straight to JSON.
    """

    def get(self, request):
        # org_id is required (not optional with a default) so a caller can never
        # accidentally fetch across tenants. Missing it is a 400, not "all rows".
        org_id = request.query_params.get("org_id")
        logger.info(
            "DisagreementListView: org_id=%r reason=%r ordering=%r",
            org_id,
            request.query_params.get("reason"),
            request.query_params.get("ordering", "value"),
        )
        if not org_id:
            return Response(
                {"detail": "org_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = request.query_params.get("reason")
        if reason and reason not in ALL_REASONS:
            return Response(
                {
                    "detail": f"Unknown reason. Choose one of: {', '.join(ALL_REASONS)}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        ordering = request.query_params.get("ordering", "value")
        reverse = ordering.startswith("-")
        order_key = ordering.lstrip("-")
        if order_key not in ("value", "record_id", "reason", "location_id"):
            return Response(
                {"detail": "ordering must be value, record_id, reason, or location_id (prefix - for desc)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        disagreements = disagreements_from_queryset(
            SystemARecord.objects.all(),
            SystemBEntry.objects.all(),
            Location.objects.all(),
            org_id=org_id,
        )

        if reason:
            disagreements = [d for d in disagreements if d.reason == reason]

        def sort_key(d):
            """Build a sort key that keeps ``None`` from crashing comparisons.

            Why the ``(is_none, value)`` tuple shape: Python can't compare a
            ``Decimal`` against ``None``, and several disagreements (missing/orphan)
            legitimately lack one side's value. Sorting on ``(primary is None, ...)``
            pushes the null rows to the end while ordering the rest by amount.
            """
            if order_key == "value":
                # Prefer A value, fall back to B; None sorts last.
                primary = d.a_value if d.a_value is not None else d.b_value
                return (primary is None, primary if primary is not None else Decimal("0"))
            if order_key == "record_id":
                return (d.record_id is None, d.record_id or "")
            if order_key == "reason":
                return d.reason
            return d.location_id

        # Sorting happens in Python (not the DB) because disagreements are computed
        # in memory, not queried. Python's sort is stable, so ties keep the
        # deterministic order produced by the comparison.
        disagreements = sorted(disagreements, key=sort_key, reverse=reverse)
        logger.debug(
            "DisagreementListView: %d disagreements for org_id=%r (reason=%r)",
            len(disagreements),
            org_id,
            reason or "all",
        )

        payload = [
            {
                "reason": d.reason,
                "record_id": d.record_id,
                "location_id": d.location_id,
                "org_id": d.org_id,
                "a_value": _decimal_to_json(d.a_value),
                "a_value_raw": d.a_value_raw,
                "b_value": _decimal_to_json(d.b_value),
                "b_value_raw": d.b_value_raw,
                "b_entry_ids": list(d.b_entry_ids),
                "detail": d.detail,
            }
            for d in disagreements
        ]
        return Response({"count": len(payload), "results": payload})
