from decimal import Decimal
from typing import Optional

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .compare import ALL_REASONS, disagreements_from_queryset
from .models import Location, SystemARecord, SystemBEntry


def _decimal_to_json(value: Optional[Decimal]):
    if value is None:
        return None
    return str(value)


class OrgListView(APIView):
    def get(self, request):
        orgs = (
            Location.objects.order_by("org_id")
            .values_list("org_id", flat=True)
            .distinct()
        )
        return Response([{"org_id": org_id} for org_id in orgs])


class DisagreementListView(APIView):
    def get(self, request):
        org_id = request.query_params.get("org_id")
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
            if order_key == "value":
                # Prefer A value, fall back to B; None sorts last.
                primary = d.a_value if d.a_value is not None else d.b_value
                return (primary is None, primary if primary is not None else Decimal("0"))
            if order_key == "record_id":
                return (d.record_id is None, d.record_id or "")
            if order_key == "reason":
                return d.reason
            return d.location_id

        disagreements = sorted(disagreements, key=sort_key, reverse=reverse)

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
