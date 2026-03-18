"""Pricing calculator tool — ported from ExtremoAmbiente A1 business rules."""

from __future__ import annotations

import json
import math

from langchain_core.tools import tool


CATALOG = {
    "jeeps": {"unit_price": 400, "capacity": 6, "time_block_hours": 4, "per_person": False},
    "walking": {"unit_price": 10, "capacity": None, "time_block_hours": 1, "per_person": True},
    "rzr": {"unit_price": 200, "capacity": 2, "time_block_hours": 2, "per_person": False},
    "food_experience": {"unit_price": 35, "capacity": None, "time_block_hours": None, "per_person": True},
    "cultural_tour": {"unit_price": 15, "capacity": None, "time_block_hours": None, "per_person": True},
    "entrance_fee": {"unit_price": 5, "capacity": None, "time_block_hours": None, "per_person": True},
}

GUIDE_FEE = 150  # flat per event
GROUP_DISCOUNT_THRESHOLD = 10
GROUP_DISCOUNT_RATE = 0.05


@tool
def calculate_pricing(
    activities_json: str,
    group_size: int,
    duration_hours: float = 8.0,
) -> str:
    """Calculate total event pricing based on selected activities and group size.

    Args:
        activities_json: JSON string of a list of activities. Each activity is an object
            with 'type' (one of: jeeps, walking, rzr, food_experience, cultural_tour,
            entrance_fee) and 'hours' (duration in hours). Example:
            '[{"type": "jeeps", "hours": 4}, {"type": "food_experience", "hours": 1.5}]'
        group_size: Total number of attendees
        duration_hours: Total event duration in hours
    """
    try:
        activities = json.loads(activities_json) if isinstance(activities_json, str) else activities_json
    except (json.JSONDecodeError, TypeError):
        return "Error: activities_json must be a valid JSON array of objects with 'type' and 'hours' keys"

    if not isinstance(activities, list):
        return "Error: activities must be a JSON array"

    if group_size < 1:
        return "Error: group_size must be at least 1"

    line_items = []

    for act in activities:
        act_type = act.get("type", "").lower()
        hours = act.get("hours", 1)
        cat = CATALOG.get(act_type)

        if not cat:
            line_items.append({
                "activity": act_type,
                "note": f"Unknown activity type '{act_type}' — skipped",
                "cost": 0,
            })
            continue

        if cat["per_person"]:
            if cat["time_block_hours"]:
                blocks = math.ceil(hours / cat["time_block_hours"])
                cost = cat["unit_price"] * group_size * blocks
                note = f"{group_size} pax × €{cat['unit_price']}/person × {blocks} block(s)"
            else:
                cost = cat["unit_price"] * group_size
                note = f"{group_size} pax × €{cat['unit_price']}/person"
        else:
            vehicles = math.ceil(group_size / cat["capacity"])
            blocks = math.ceil(hours / cat["time_block_hours"])
            cost = cat["unit_price"] * vehicles * blocks
            note = f"{vehicles} vehicle(s) × {blocks} block(s) × €{cat['unit_price']}"

        line_items.append({
            "activity": act_type,
            "cost": cost,
            "note": note,
        })

    subtotal = sum(item["cost"] for item in line_items)
    subtotal += GUIDE_FEE
    line_items.append({"activity": "guide_fee", "cost": GUIDE_FEE, "note": "Flat rate per event"})

    discount = 0
    if group_size > GROUP_DISCOUNT_THRESHOLD:
        discount = round(subtotal * GROUP_DISCOUNT_RATE, 2)

    total = subtotal - discount
    per_person = round(total / group_size, 2)

    return json.dumps({
        "line_items": line_items,
        "subtotal": subtotal,
        "group_discount": discount,
        "total": total,
        "per_person": per_person,
        "group_size": group_size,
    }, indent=2)
