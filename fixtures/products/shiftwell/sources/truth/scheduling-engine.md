---
title: Shiftwell scheduling engine
kind: living
updated: 2026-08-20
url: https://docs.shiftwell.example.test/scheduling/engine
---

# Shiftwell scheduling engine

This page describes how Shiftwell builds rotas, applies staffing rules and fills open shifts. All behavior applies to Shiftwell release 5.4.

## Rotas

A rota in Shiftwell covers one location for a period of 1 to 8 weeks. Rota coordinators build a rota from shift templates. Each location supports up to 40 shift templates. A shift template stores a start time, an end time, a role and a break length. A draft rota is visible only to Schedulers and Administrators until it is published. Publishing a rota sends a notification to every staff member with a shift on that rota.

## Limits

- Each Shiftwell location supports up to 500 staff profiles.
- Each rota supports up to 3,000 shifts.
- Each shift supports up to 4 break periods.
- Rota history is kept for 36 months in Shiftwell Cloud.

## Staffing rules

Administrators can set a minimum number of staff for each role and each shift. Shiftwell Web marks a shift in red when it falls below the minimum staffing rule. Administrators can require a qualification, such as a registered nurse licence, for a role. Shiftwell does not assign a shift to a staff member whose required qualification has expired. Qualification expiry dates are entered by an Administrator. Shiftwell does not check qualifications against any external register.

## Working-time rules

Administrators can set a maximum number of hours per week for each staff member. Administrators can set a minimum rest period between two shifts. Shiftwell Web warns the Scheduler when a shift breaks a working-time rule. A Scheduler can publish a shift that breaks a working-time rule after entering a reason. Shiftwell sends an overtime alert to the Scheduler when a staff member is within 4 hours of their weekly maximum.

## Availability and leave

Staff record their availability in Shiftwell Mobile. Staff request annual leave in Shiftwell Mobile. Schedulers approve or decline leave requests in Shiftwell Web. Approved leave blocks a staff member from being assigned shifts on those days.

## Open shifts

An open shift is a published shift with no assigned staff member. Schedulers can offer an open shift to all eligible staff or to a chosen group. Eligible staff are staff with the required role, the required qualification and no conflicting shift. The first eligible staff member to accept an open shift is assigned to it. Schedulers can require approval before an accepted open shift is confirmed.

## Shift swaps

Staff can request a swap with another eligible staff member in Shiftwell Mobile. The other staff member must accept the swap request. A Scheduler must approve a swap before it takes effect, unless the location allows automatic swap approval. Automatic swap approval requires Shiftwell release 5.1 or later. Swap requests that are not answered within 48 hours expire.

## Sick calls

Staff report a sick call in Shiftwell Mobile. A sick call turns the staff member's shift into an open shift. Shiftwell notifies the Scheduler on duty when a sick call is reported. Sick calls reported less than 2 hours before a shift starts are marked as late sick calls in Shiftwell Web.

## Auto-Fill Scheduling

Auto-Fill Scheduling is in beta. Auto-Fill Scheduling proposes staff for open shifts from availability, qualifications, working-time rules and past shift patterns. Auto-Fill Scheduling proposes staff, and a Scheduler confirms every proposal before it is published. Auto-Fill Scheduling requires Shiftwell release 5.4 or later. Auto-Fill Scheduling is available on the Enterprise plan. Beta features are not covered by the uptime service level agreement.

## Rota approval

Rota approval is described in the security and compliance documentation. When rota approval is enabled, a Scheduler submits a rota and an Administrator publishes it.
