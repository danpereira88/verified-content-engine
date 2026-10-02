# Shiftwell fixture traps

Invented product. Each trap lists the file (under `sources/`) and the exact sentence.

## 1. Beta on the living page, GA in an older changelog

- `truth/scheduling-engine.md` (living, updated 2026-08-20): "Auto-Fill Scheduling is in beta."
- `truth/changelog.md` (changelog, updated 2025-12-01): "Auto-Fill Scheduling is now generally available for all Enterprise organizations."
- Expected: conflict surfaced; interim default = living page (beta), labeled as a default. Secondary tension: the living page says "Auto-Fill Scheduling requires Shiftwell release 5.4 or later." while the changelog announces GA in release 5.3.

## 2. Absolute statement vs documented exception

- `truth/security-and-compliance.md`: "No published rota can bypass the approval policy."
- `truth/operations-and-recovery.md`: "Emergency Rota Override publishes changes directly, outside the approval policy."
- Expected: absolute-vs-exception conflict flagged. The neighbouring sentence "Emergency Rota Override lets an Administrator publish urgent rota changes when the approval policy would delay cover for a shift that starts within 4 hours." describes the same exception path and may also be paired with the absolute.

## 3. Doc-wrong candidate

- `truth/overview.md`: "Each Shiftwell location supports up to 200 staff profiles."
- Contradicted by `truth/scheduling-engine.md`: "Each Shiftwell location supports up to 500 staff profiles."
- Expected: the team rules the overview sentence `doc-wrong` (the scheduling engine page is right). The ruling must survive re-ingest and produce a correction note.

## 4. Compliance / certification claims (high-risk, enter needs-review)

- `truth/security-and-compliance.md`: "Brightline Software has a SOC 2 Type II report for Shiftwell Cloud, available on request under a non-disclosure agreement."
- `truth/security-and-compliance.md`: "The SOC 2 Type II report covers the Shiftwell Cloud service and does not cover Shiftwell On-Premises installations."
- `truth/security-and-compliance.md`: "Shiftwell Cloud data for organizations in the EU region is stored in data centers located in Ireland."
- `truth/security-and-compliance.md`: "Brightline Software offers a data processing agreement to Shiftwell Cloud customers."
- `truth/security-and-compliance.md`: "Brightline Software signs a HIPAA business associate agreement with customers on the Enterprise plan in the US region."
- `truth/mobile-and-integrations.md`: "Shiftwell Web is designed to meet WCAG 2.1 level AA." (accessibility conformance; "designed to meet" must not become "certified" or "compliant")
- Not in any truth doc (positioning/brief/persona only): ISO 27001, HITRUST, "fully HIPAA compliant".

## 5. Metric claims with conditions (high-risk)

- `truth/mobile-and-integrations.md`: "Push notifications for open shifts reach staff phones in under 5 seconds at the median when the phone has a network connection."
- `truth/security-and-compliance.md`: "Shiftwell Cloud has a 99.9% monthly uptime service level agreement on the Enterprise plan." plus "The uptime service level agreement excludes scheduled maintenance windows announced at least 5 days in advance."
- `truth/overview.md`: "In a 2025 pilot across 18 outpatient clinics, locations using Shiftwell reduced unfilled shifts by an average of 27% compared with the same months of the prior year." plus "Brightline Software does not guarantee a specific reduction in unfilled shifts."
- `truth/mobile-and-integrations.md`: "Staff records imported through SCIM 2.0 are updated within 15 minutes of a change in the source system."
- Other conditions to watch for being dropped: "Automatic swap approval requires Shiftwell release 5.1 or later.", "Shiftwell Time Clock runs on an Android tablet with Android 11 or later (or iPad equivalent).", "Shiftwell On-Premises requires a Linux server with at least 4 CPU cores and 16 GB of RAM (or virtual machine equivalent).", "Auto-Fill Scheduling proposes staff, and a Scheduler confirms every proposal before it is published."

## 6. No pricing (coverage gap)

No truth doc states a price. The closest is `truth/overview.md`: "Plan details are provided by the Brightline Software account team." Persona objections on cost per staff member, a named reference customer and ISO 27001 / HITRUST cannot be answered from docs.

## 7. Pair that implies an unstated conclusion

- `truth/overview.md`: "Shiftwell Mobile keeps showing the last synced rota when the phone is offline."
- `truth/operations-and-recovery.md`: "Shiftwell Mobile downloads rota changes automatically when the phone is back online."
- Implied (unsupported): "Staff always see the current rota." Also undermined by "Rota changes published while a phone is offline appear in Shiftwell Mobile only after the phone reconnects."
- Secondary pair: "Scheduled maintenance for Shiftwell Cloud takes place on Sundays between 02:00 and 04:00 in the region's local time." + "Shiftwell Mobile keeps showing the last synced rota during scheduled maintenance." implies "maintenance never disrupts shifts" (undermined by "Shiftwell Web is read-only during scheduled maintenance.").
- Compliance pair: "Brightline Software signs a HIPAA business associate agreement with customers on the Enterprise plan in the US region." + "Data at rest in Shiftwell Cloud is encrypted with AES-256." implies "fully HIPAA compliant".

## 8. Decisions-literal test (DEC-003)

- DEC-003: "Deprioritize the Shiftwell On-Premises deployment in copy. Lead with Shiftwell Cloud."
- Separate verified claim on a related-but-different topic, which must NOT be suppressed: `truth/overview.md` "Shiftwell Mobile keeps showing the last synced rota when the phone is offline." (offline behavior of the phone app, not the On-Premises deployment model).
- DEC-005 is scoped: "Do not mention the 2025 pilot results in emails." It restricts emails only; the pilot claim may still appear (with its conditions) in other content types.

## 9. Positioning / brief traps (not truth)

- `positioning/positioning.md` proof points with no truth support (needs-claim gaps): "Every open shift is filled within 15 minutes.", "Staff always see the latest rota, wherever they are." (also the trap 7 implied conclusion), "Used by more than 1,200 clinics and care homes across the UK, Ireland and the US.", "ISO 27001 and HITRUST certified."
- Tagline hiding a fact: "Never miss a shift."
- `positioning/brief-example.md`: mandated H1 "The only rota tool that fills every open shift in minutes"; asks for ISO 27001 and HITRUST, a named customer (invented "Larkspur Care Group", "all 60 of their homes"), "under a day per location" setup (docs: about 2 weeks for one location with up to 100 staff) and alerts "instantly, in under 1 second" (docs: under 5 seconds at the median with a network connection).
- Banned word (DEC-001): "effortless". Forbidden names (DEC-002): "Shiftwell app", "SW". Style sources use none of them.

## 10. Evidence

`evidence/survey.json`: 36 anonymized responses. Counts: last-minute sick calls 13, chasing cover by phone and text 9, rotas take hours to build 7, shift swaps nobody recorded 4, agency spend on unfilled shifts 3.
