"""PDF proposal generator — renders a Quarto template to PDF."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
TEMPLATE_FILE = TEMPLATE_DIR / "proposal_template.qmd"

# Directory served by Next.js as static files
_UI_PUBLIC_PROPOSALS = Path(__file__).parent.parent.parent / "ui" / "public" / "proposals"


def generate_proposal_pdf(
    event_details: dict,
    optimized_route: list[dict],
    pricing: dict,
    google_maps_url: str,
    executive_summary: str = "",
) -> str:
    """Generate a PDF proposal from the Quarto template.

    Returns the path to the generated PDF file.
    """
    # Create a temporary working directory
    work_dir = Path(tempfile.mkdtemp(prefix="ea_proposal_"))

    # Copy assets
    assets_src = TEMPLATE_DIR / "assets"
    assets_dst = work_dir / "assets"
    if assets_src.exists():
        shutil.copytree(assets_src, assets_dst)

    # Build template values
    client_name = event_details.get("client_name", "Client")
    date = event_details.get("date", "TBD")
    group_size = event_details.get("group_size", "?")
    locations = event_details.get("locations", ["Porto"])
    location = ", ".join(locations) if isinstance(locations, list) else str(locations)
    start_time = event_details.get("start_time", "09:00")
    end_time = event_details.get("end_time", "17:00")
    duration_hours = event_details.get("duration_hours", 8)
    preferences = event_details.get("preferences", ["adventure"])
    preferences_str = ", ".join(preferences) if isinstance(preferences, list) else str(preferences)

    # Special requests
    special = event_details.get("special_requests", {})
    has_special = bool(special)
    if isinstance(special, dict) and special:
        special_text = "; ".join(f"{k}: {v}" for k, v in special.items())
    elif isinstance(special, str):
        special_text = special
    else:
        special_text = ""

    # Build itinerary table
    itinerary_rows = []
    for stop in optimized_route:
        types_str = ", ".join(stop.get("types", [])[:2]) if stop.get("types") else ""
        travel = f"+{stop['travel_to_next_min']}min travel" if stop.get("travel_to_next_min") else ""
        itinerary_rows.append(
            f"| {stop.get('time', '')} | {stop.get('name', '')} | "
            f"{stop.get('duration_min', '')}min | {types_str} | {travel} |"
        )

    itinerary_table = (
        "| Time | Activity | Duration | Type | Travel |\n"
        "|------|----------|----------|------|--------|\n"
        + "\n".join(itinerary_rows)
    )

    # Build pricing table
    line_items = pricing.get("line_items", [])
    pricing_rows = []
    for item in line_items:
        pricing_rows.append(
            f"| {item.get('activity', '').replace('_', ' ').title()} | "
            f"{item.get('note', '')} | EUR {item.get('cost', 0)} |"
        )

    pricing_table = (
        "| Activity | Details | Cost |\n"
        "|----------|---------|------|\n"
        + "\n".join(pricing_rows)
    )

    has_discount = pricing.get("group_discount", 0) > 0
    has_food = any(
        "food" in str(stop.get("types", [])).lower()
        for stop in optimized_route
    )

    total = pricing.get("total", 0)
    per_person = pricing.get("per_person", 0)

    # Default executive summary if not provided
    if not executive_summary:
        executive_summary = (
            f"We are delighted to present this exclusive corporate event proposal for "
            f"**{client_name}**. This carefully curated {duration_hours}-hour experience in "
            f"**{location}** has been designed for your group of **{group_size}** participants, "
            f"combining {preferences_str} activities into an unforgettable journey. "
            f"Each stop has been selected to deliver maximum engagement and memorable moments "
            f"for your team."
        )

    # Read and fill the template
    template_content = TEMPLATE_FILE.read_text()

    # Replace placeholders
    replacements = {
        "{{client_name}}": client_name,
        "{{date}}": str(date),
        "{{group_size}}": str(group_size),
        "{{location}}": location,
        "{{start_time}}": start_time,
        "{{end_time}}": end_time,
        "{{duration_hours}}": str(duration_hours),
        "{{preferences}}": preferences_str,
        "{{executive_summary}}": executive_summary,
        "{{itinerary_table}}": itinerary_table,
        "{{pricing_table}}": pricing_table,
        "{{total}}": str(total),
        "{{per_person}}": str(per_person),
        "{{google_maps_url}}": google_maps_url or "Route link not available",
        "{{special_requests_text}}": special_text,
    }

    for placeholder, value in replacements.items():
        template_content = template_content.replace(placeholder, value)

    # Handle conditional sections
    if has_special:
        template_content = template_content.replace("{{#special_requests}}", "")
        template_content = template_content.replace("{{/special_requests}}", "")
    else:
        # Remove the special requests section
        import re
        template_content = re.sub(
            r"\{\{#special_requests\}\}.*?\{\{/special_requests\}\}",
            "",
            template_content,
            flags=re.DOTALL,
        )

    if has_discount:
        template_content = template_content.replace("{{#has_discount}}", "")
        template_content = template_content.replace("{{/has_discount}}", "")
    else:
        import re
        template_content = re.sub(
            r"\{\{#has_discount\}\}.*?\{\{/has_discount\}\}",
            "",
            template_content,
            flags=re.DOTALL,
        )

    if has_food:
        template_content = template_content.replace("{{#has_food}}", "")
        template_content = template_content.replace("{{/has_food}}", "")
    else:
        import re
        template_content = re.sub(
            r"\{\{#has_food\}\}.*?\{\{/has_food\}\}",
            "",
            template_content,
            flags=re.DOTALL,
        )

    # Write the filled template
    qmd_path = work_dir / "proposal.qmd"
    qmd_path.write_text(template_content)

    # Render with Quarto
    pdf_path = work_dir / "proposal.pdf"

    try:
        result = subprocess.run(
            ["quarto", "render", str(qmd_path), "--to", "pdf"],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            # If quarto fails, try a simpler approach without the template
            return _fallback_pdf(work_dir, event_details, optimized_route, pricing, google_maps_url, executive_summary)

        if pdf_path.exists():
            return _publish_pdf(pdf_path)

        # Check if quarto put it somewhere else
        for f in work_dir.glob("*.pdf"):
            return _publish_pdf(f)

        return _fallback_pdf(work_dir, event_details, optimized_route, pricing, google_maps_url, executive_summary)

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return _fallback_pdf(work_dir, event_details, optimized_route, pricing, google_maps_url, executive_summary)


def _fallback_pdf(
    work_dir: Path,
    event_details: dict,
    optimized_route: list[dict],
    pricing: dict,
    google_maps_url: str,
    executive_summary: str,
) -> str:
    """Fallback: generate a simpler Quarto doc if the full template fails."""
    client_name = event_details.get("client_name", "Client")
    date = event_details.get("date", "TBD")
    group_size = event_details.get("group_size", "?")
    locations = event_details.get("locations", ["Porto"])
    location = ", ".join(locations) if isinstance(locations, list) else str(locations)

    # Build simple markdown
    itinerary_lines = []
    for stop in optimized_route:
        itinerary_lines.append(
            f"| {stop.get('time', '')} | {stop.get('name', '')} | "
            f"{stop.get('duration_min', '')}min |"
        )

    pricing_lines = []
    for item in pricing.get("line_items", []):
        pricing_lines.append(
            f"| {item.get('activity', '').replace('_', ' ').title()} | "
            f"EUR {item.get('cost', 0)} |"
        )

    itinerary_section = "\n".join(itinerary_lines)
    pricing_section = "\n".join(pricing_lines)

    simple_qmd = f"""---
title: "Event Proposal — {client_name}"
subtitle: "Extremo Ambiente | {date}"
format:
  pdf:
    documentclass: article
    geometry:
      - top=25mm
      - bottom=25mm
      - left=20mm
      - right=20mm
    fontsize: 11pt
    colorlinks: true
---

![](assets/logo.png){{width=3cm fig-align="center"}}

# Event Overview

- **Client:** {client_name}
- **Date:** {date}
- **Group Size:** {group_size} people
- **Location:** {location}

# Executive Summary

{executive_summary}

# Itinerary

| Time | Activity | Duration |
|------|----------|----------|
{itinerary_section}

# Pricing

| Activity | Cost |
|----------|------|
{pricing_section}

**Total: EUR {pricing.get('total', 0)}** | Per Person: EUR {pricing.get('per_person', 0)}

# Route

{google_maps_url or "Route link not available"}

---

*Extremo Ambiente | Adventure Tourism & Corporate Events | Porto, Portugal*
"""

    qmd_path = work_dir / "proposal_simple.qmd"
    qmd_path.write_text(simple_qmd)

    try:
        subprocess.run(
            ["quarto", "render", str(qmd_path), "--to", "pdf"],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )

        for f in work_dir.glob("*.pdf"):
            return _publish_pdf(f)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return ""


def _publish_pdf(src_path: Path) -> str:
    """Copy the PDF to ui/public/proposals/ and return the web-accessible URL path."""
    _UI_PUBLIC_PROPOSALS.mkdir(parents=True, exist_ok=True)

    filename = f"proposal_{int(time.time())}.pdf"
    dest = _UI_PUBLIC_PROPOSALS / filename
    shutil.copy2(src_path, dest)

    # Return the URL path that Next.js serves from /public
    return f"/proposals/{filename}"
