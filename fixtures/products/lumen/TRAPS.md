# Lumen Hub fixture traps

Invented product. Each trap lists the file (under `sources/`) and the exact sentence.

## 1. Beta on the living page, GA in an older changelog

- `truth/app-and-integrations.md` (living, updated 2026-08-14): "Occupancy Forecasting is in beta."
- `truth/changelog.md` (changelog, updated 2025-11-20): "Occupancy Forecasting is now generally available for all Enterprise sites."
- Expected: conflict surfaced; interim default = living page (beta), labeled as a default. Secondary tension: the living page says "Occupancy Forecasting requires firmware 3.4 or later." while the changelog announces GA in firmware 3.3.

## 2. Absolute statement vs documented exception

- `truth/security-and-compliance.md`: "No configuration change can bypass the approval policy."
- `truth/operations-and-recovery.md`: "Emergency Site Recovery applies configuration changes directly to the Lumen Hub, outside the approval policy."
- Expected: absolute-vs-exception conflict flagged.

## 3. Doc-wrong candidate

- `truth/overview.md`: "Each Lumen Hub supports up to 32 wireless sensors."
- Contradicted by `truth/hardware-spec.md`: "Each Lumen Hub pairs with up to 64 wireless Lumen Sensors."
- Expected: the team rules the overview sentence `doc-wrong` (spec is right). The ruling must survive re-ingest and produce a correction note.

## 4. Compliance / certification claims (high-risk, enter needs-review)

- `truth/security-and-compliance.md`: "Northwind Devices has a SOC 2 Type II report for Lumen Cloud, available on request under a non-disclosure agreement."
- `truth/security-and-compliance.md`: "The SOC 2 Type II report covers the Lumen Cloud service and does not cover Lumen Edge Server installations."
- `truth/security-and-compliance.md`: "Lumen Cloud data for organizations in the EU region is stored in data centers located in Germany."
- `truth/security-and-compliance.md`: "Northwind Devices offers a data processing agreement to Lumen Cloud customers."
- `truth/hardware-spec.md`: "The Lumen Hub controller carries CE marking for sale in the EU." and "The Lumen Hub controller complies with FCC Part 15 Class B for sale in the United States."
- Not in any truth doc (positioning/brief only): ISO 27001.

## 5. Metric claims with conditions (high-risk)

- `truth/hardware-spec.md`: "Lumen Sensor temperature accuracy is ±0.2 °C between 15 °C and 30 °C."
- `truth/security-and-compliance.md`: "Lumen Cloud has a 99.9% monthly uptime service level agreement on the Enterprise plan." plus "The uptime service level agreement excludes scheduled maintenance windows announced at least 72 hours in advance."
- `truth/app-and-integrations.md`: "Setpoint changes made in the Lumen app reach the Lumen Hub in under 2 seconds at the median on a broadband connection."
- `truth/overview.md`: "In a 2025 pilot across 12 office buildings, sites using Lumen Hub reduced HVAC energy use by an average of 18% compared with the same months of the prior year."
- Other conditions to watch for being dropped: "BACnet/IP write support requires firmware 3.2 or later.", "Lumen Hub connects to BACnet MS/TP equipment through a BACnet MS/TP to IP router (or software equivalent).", "Lumen Edge Server requires a Linux server with at least 4 CPU cores and 8 GB of RAM (or virtual machine equivalent)."

## 6. No pricing (coverage gap)

No truth doc states a price. The closest is `truth/overview.md`: "Plan details are provided by the Northwind Devices account team." Persona objections on cost, references and ISO 27001 cannot be answered from docs.

## 7. Pair that implies an unstated conclusion

- `truth/hardware-spec.md`: "Lumen Hub stores up to 30 days of sensor readings in local memory."
- `truth/operations-and-recovery.md`: "Lumen Hub buffers sensor readings during an internet outage and uploads them when the connection returns."
- Implied (unsupported): "No data is lost in an internet outage shorter than 30 days." Also undermined by "Lumen Hub does not record sensor readings while the Lumen Hub controller has no power."
- Secondary pair: "Firmware updates install during the maintenance window set by a site Administrator." + "During a restart, connected HVAC equipment holds its last relay state." implies "updates never disrupt comfort".

## 8. Decisions-literal test (DEC-003)

- DEC-003: "Deprioritize the Lumen Edge Server deployment in copy. Lead with Lumen Cloud."
- Separate verified claim on a related-but-different topic, which must NOT be suppressed: `truth/overview.md` "Lumen Hub keeps running its last synchronized schedule during an internet outage." (on-device offline operation, not the Edge Server deployment model).

## 9. Positioning / brief traps (not truth)

- `positioning/positioning.md` proof points with no truth support (needs-claim gaps): "Trusted by more than 500 buildings across Europe and North America.", "ISO 27001 certified hardware and cloud.", "Lumen Hub has never lost a sensor reading at any customer site." (the last is also contradicted by the power-outage sentence).
- Tagline hiding a fact: "Never lose a reading."
- `positioning/brief-example.md`: mandated H1 "The only climate controller that cuts your heating bill in half"; asks for ISO 27001, a named customer (invented "Quillmere Estates"), "under 30 minutes per building" install (docs: about 3 hours for one Hub and 10 sensors) and "±0.1 °C" accuracy (docs: ±0.2 °C in range).
- Banned word (DEC-001): "smart". Style sources do not use it.

## 10. Evidence

`evidence/survey.json`: 36 anonymized responses. Counts: comfort complaints 13, no visibility into individual rooms 9, high heating and cooling bills 7, old equipment that is hard to integrate 4, slow and costly BMS changes 3.
