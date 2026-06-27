from datetime import date


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
    report_lines = ["NEW RARE BIRDS", ""]
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
