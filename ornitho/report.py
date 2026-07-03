from collections import OrderedDict
from datetime import date
import re


def build_report(all_results, errors):
    today = date.today().isoformat()
    total_records = sum(len(records) for _, records in all_results)

    report_lines = [f"Ornitho rare-bird report — today: {today}", ""]

    if total_records == 0 and not errors:
        report_lines.append("No rare records today.")
        report_lines.append("")

    for label, records in all_results:
        report_lines.append(f"[{label}]")

        if records:
            for r in records:
                report_lines.append(f"{r['species']} ({r['scientific']})")
                report_lines.append(f"{r['count']} — {r['location']}")
                report_lines.append(r["date"])
                if r["detail"]:
                    report_lines.append(f"Detail: {r['detail']}")
                report_lines.append("")
        else:
            report_lines.append("No rare records extracted.")
            report_lines.append("")

    if errors:
        report_lines.append("Errors:")
        for label, err_type, message in errors:
            report_lines.append(f"- {label}: {err_type}: {message}")
        report_lines.append("")

    return "\n".join(report_lines)


def build_notification_report(new_results, errors):
    report_lines = []
    total_records = sum(len(records) for _, records in new_results)

    if total_records == 0 and not errors:
        report_lines.append("No new rare records.")
        report_lines.append("")

    for label, records in new_results:
        if not records:
            continue

        report_lines.append(label)
        report_lines.append("")

        for record in records:
            report_lines.append(f"{record['species']} ({record['scientific']})")
            report_lines.append(f"{record['count']} - {record['location']}")
            report_lines.append(record["date"])
            if record["detail"]:
                report_lines.append(f"Detail: {record['detail']}")
            report_lines.append("")

    if errors:
        report_lines.append("Errors:")
        for label, err_type, message in errors:
            report_lines.append(f"- {label}: {err_type}: {message}")
        report_lines.append("")

    return "\n".join(report_lines)


def clean_subject_location(location):
    location = re.sub(r"\s*\[[^\]]*\]", "", location or "")
    location = re.sub(r"\s*\([^)]*\)", "", location)
    location = re.sub(r"\s*/\s*", " / ", location)
    location = re.sub(r"\s+", " ", location)
    return location.strip()


def build_notification_subject(new_results):
    records = [record for _, records in new_results for record in records]
    if not records:
        return "Ornitho Rare Bird Notification"

    if len(records) == 1:
        record = records[0]
        species = record.get("species", "Rare bird").strip() or "Rare bird"
        location = clean_subject_location(record.get("location", ""))
        if location:
            return f"{species} - {location}"
        return species

    species_counts = OrderedDict()
    for record in records:
        species = record.get("species", "Rare bird").strip() or "Rare bird"
        species_counts[species] = species_counts.get(species, 0) + 1

    subject_parts = [
        f"{species} ({count})" if count > 1 else species
        for species, count in species_counts.items()
    ]
    return ", ".join(subject_parts)
