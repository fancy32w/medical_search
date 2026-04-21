#!/usr/bin/env python3
"""
ClinicalTrials.gov search script.
Usage:
    python3 search_trials.py --term BMS-986278
    python3 search_trials.py --term BMS-986278 --days 60
    python3 search_trials.py --term "pembrolizumab" --days 30 --status RECRUITING
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta


def fetch_studies(term: str, days: int = None, status: str = None) -> list:
    params = {
        "query.term": term,
        "pageSize": "100",
        "countTotal": "true",
    }
    url = "https://clinicaltrials.gov/api/v2/studies?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)

    studies = data.get("studies", [])
    total = data.get("totalCount", len(studies))

    # Filter by last update date (only if --days specified)
    cutoff = date.today() - timedelta(days=days) if days else None
    results = []
    for s in studies:
        p = s.get("protocolSection", {})
        status_m = p.get("statusModule", {})

        if cutoff:
            last_update_str = status_m.get("lastUpdatePostDateStruct", {}).get("date", "")
            try:
                last_update = datetime.strptime(last_update_str, "%Y-%m-%d").date()
                if last_update < cutoff:
                    continue
            except ValueError:
                continue

        # Optional status filter
        if status:
            overall = status_m.get("overallStatus", "")
            if status.upper() not in overall.upper():
                continue

        results.append(s)

    return results, total


def format_study(s: dict) -> dict:
    p = s.get("protocolSection", {})
    id_m = p.get("identificationModule", {})
    status_m = p.get("statusModule", {})
    sponsor_m = p.get("sponsorCollaboratorsModule", {})
    desc_m = p.get("descriptionModule", {})
    design_m = p.get("designModule", {})
    resp_party = sponsor_m.get("responsibleParty", {})

    sponsor = sponsor_m.get("leadSponsor", {}).get("name", "N/A")
    resp_type = resp_party.get("type", "")
    resp_org = resp_party.get("organization", "")
    resp_inv = resp_party.get("investigatorFullName", "")

    if resp_type == "SPONSOR":
        info_provided = f"Sponsor ({sponsor})"
    elif resp_type == "PRINCIPAL_INVESTIGATOR":
        info_provided = f"Principal Investigator: {resp_inv}, {resp_org}"
    elif resp_type == "SPONSOR_INVESTIGATOR":
        info_provided = f"Sponsor-Investigator: {resp_inv}, {resp_org}"
    else:
        info_provided = resp_type or "N/A"

    phase_list = design_m.get("phaseList", {})
    phases = ", ".join(phase_list.get("phase", [])) if phase_list else "N/A"

    enrollment = design_m.get("enrollmentInfo", {}).get("count", "N/A")
    enroll_type = design_m.get("enrollmentInfo", {}).get("type", "")

    status_raw = status_m.get("overallStatus", "N/A")
    status_display = {
        "RECRUITING": "Recruiting",
        "NOT_YET_RECRUITING": "Not Yet Recruiting",
        "ACTIVE_NOT_RECRUITING": "Active, Not Recruiting",
        "COMPLETED": "Completed",
        "TERMINATED": "Terminated",
        "SUSPENDED": "Suspended",
        "WITHDRAWN": "Withdrawn",
        "ENROLLING_BY_INVITATION": "Enrolling by Invitation",
        "UNKNOWN": "Unknown",
    }.get(status_raw, status_raw)

    return {
        "nct_id": id_m.get("nctId", "N/A"),
        "title": id_m.get("briefTitle", "N/A"),
        "status": status_display,
        "sponsor": sponsor,
        "information_provided_by": info_provided,
        "last_update_posted": status_m.get("lastUpdatePostDateStruct", {}).get("date", "N/A"),
        "study_start": status_m.get("startDateStruct", {}).get("date", "N/A"),
        "primary_completion": status_m.get("primaryCompletionDateStruct", {}).get("date", "N/A"),
        "study_completion": status_m.get("completionDateStruct", {}).get("date", "N/A"),
        "enrollment": f"{enrollment} ({enroll_type})" if enroll_type else str(enrollment),
        "phase": phases,
        "study_overview": desc_m.get("briefSummary", "N/A"),
    }


def print_results(studies: list, term: str, days: int = None) -> None:
    if not studies:
        print(f"No studies found for '{term}'.")
        return

    time_label = f"近 {days} 天更新" if days else "全部"

    print(f"\n{'=' * 70}")
    print(f"ClinicalTrials.gov Search: '{term}'")
    print(f"Filter: {time_label}  |  Results: {len(studies)} studies")
    print(f"{'=' * 70}")

    for i, s in enumerate(studies, 1):
        f = format_study(s)
        print(f"\n[{i}] {f['nct_id']} — {f['status'].upper()}")
        print(f"Title: {f['title']}")
        print(f"Sponsor: {f['sponsor']}")
        print(f"Information Provided By: {f['information_provided_by']}")
        print(f"Last Update Posted: {f['last_update_posted']}")
        print(f"Study Start: {f['study_start']}")
        print(f"Primary Completion: {f['primary_completion']}")
        print(f"Study Completion: {f['study_completion']}")
        print(f"Enrollment: {f['enrollment']}")
        print(f"Phase: {f['phase']}")
        print(f"Study Overview:")
        overview = f["study_overview"]
        # Wrap at 80 chars
        import textwrap
        for line in textwrap.wrap(overview, width=78):
            print(f"  {line}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Search ClinicalTrials.gov")
    parser.add_argument("--term", required=True, help="Search term (drug name, condition, etc.)")
    parser.add_argument("--days", type=int, default=None, help="Filter: last update within N days (default: no limit)")
    parser.add_argument("--status", help="Filter by status (e.g. RECRUITING, COMPLETED)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    studies, total = fetch_studies(args.term, args.days, args.status)

    if args.json:
        output = [format_study(s) for s in studies]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_results(studies, args.term, args.days)


if __name__ == "__main__":
    main()
