---
title: Shiftwell operations and recovery
kind: living
updated: 2026-08-20
url: https://docs.shiftwell.example.test/operations
---

# Shiftwell operations and recovery

This page explains onboarding, releases, outages and recovery for Shiftwell organizations.

## Onboarding

A Brightline Software onboarding specialist sets up each new Shiftwell organization. A typical onboarding for one location with up to 100 staff takes about 2 weeks. The onboarding specialist imports staff records, roles and shift templates. The onboarding specialist runs one 60-minute training session for Schedulers at each location.

## Releases and maintenance

Brightline Software releases Shiftwell Cloud updates every two weeks. Scheduled maintenance for Shiftwell Cloud takes place on Sundays between 02:00 and 04:00 in the region's local time. Shiftwell Web is read-only during scheduled maintenance. Shiftwell Mobile keeps showing the last synced rota during scheduled maintenance. Brightline Software announces scheduled maintenance in Shiftwell Web at least 5 days in advance.

## Connection loss

Shiftwell Mobile downloads rota changes automatically when the phone is back online. Rota changes published while a phone is offline appear in Shiftwell Mobile only after the phone reconnects. Push notifications sent while a phone is offline are delivered when the phone reconnects. Shiftwell Time Clock stores up to 7 days of clock-in records when the tablet has no connection. Shiftwell Time Clock uploads stored clock-in records when the connection returns.

## Emergency Rota Override

Emergency Rota Override lets an Administrator publish urgent rota changes when the approval policy would delay cover for a shift that starts within 4 hours. Emergency Rota Override publishes changes directly, outside the approval policy. Emergency Rota Override requires the Administrator to enter a reason. Every Emergency Rota Override action is recorded in the Shiftwell audit log. Emergency Rota Override is available on the Enterprise plan.

## Backups

Shiftwell Cloud backs up customer data every hour. Shiftwell Cloud keeps backups for 35 days. Brightline Software restores a Shiftwell Cloud organization from backup within 8 hours of a confirmed request. Shiftwell On-Premises backups are the customer's responsibility.

## Account recovery

An Administrator can reset another user's multi-factor authentication after verifying the user's identity. If every Administrator in an organization is locked out, Brightline Software support restores access after a verification call with the organization owner.

## Support

Standard plan support is available by email during business hours in the customer's region. Enterprise plan support includes a 1-hour response target for critical incidents, 24 hours a day. Enterprise plan customers have a named customer success manager.

## Data export

Administrators can export rotas, timesheets and staff profiles as CSV at any time. Brightline Software provides a full data export within 10 business days of a request when an organization is closed.
