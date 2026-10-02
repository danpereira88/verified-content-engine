---
title: Shiftwell security and compliance
kind: living
updated: 2026-08-20
url: https://docs.shiftwell.example.test/security
---

# Shiftwell security and compliance

This page describes how Brightline Software protects Shiftwell Web, Shiftwell Mobile and Shiftwell Cloud.

## Rota approval policy

Shiftwell supports a rota approval policy for each location. When the approval policy is enabled, a published rota and any change to a published rota require approval from an Administrator. No published rota can bypass the approval policy. Rota changes waiting for approval expire if they are not approved within 24 hours. The approval policy is available on the Enterprise plan.

## Audit log

The Shiftwell audit log records every rota change with the user, the time and the previous value. The Shiftwell audit log is retained for 24 months. Administrators can export the Shiftwell audit log as CSV.

## Encryption

- Data in transit between Shiftwell Mobile, Shiftwell Web and Shiftwell Cloud is encrypted with TLS 1.2 or later.
- Data at rest in Shiftwell Cloud is encrypted with AES-256.
- Shiftwell Mobile encrypts the rota stored on the phone with the phone's built-in keystore.

## Identity and access

Shiftwell accounts support multi-factor authentication with an authenticator app. Administrators can require multi-factor authentication for every Scheduler and Administrator in an organization. Single sign-on through SAML 2.0 is available on the Enterprise plan. Shiftwell signs a user out of Shiftwell Web after 30 minutes of inactivity.

## Compliance

Brightline Software has a SOC 2 Type II report for Shiftwell Cloud, available on request under a non-disclosure agreement. The SOC 2 Type II report covers the Shiftwell Cloud service and does not cover Shiftwell On-Premises installations. An independent security firm performs a penetration test of Shiftwell Cloud once per year. Brightline Software offers a data processing agreement to Shiftwell Cloud customers. Brightline Software signs a HIPAA business associate agreement with customers on the Enterprise plan in the US region.

## Data residency

Shiftwell Cloud customers choose the US region, the EU region or the UK region when an organization is created. Shiftwell Cloud data for organizations in the EU region is stored in data centers located in Ireland. Shiftwell Cloud data for organizations in the UK region is stored in data centers located in the United Kingdom. Shiftwell Cloud data for organizations in the US region is stored in data centers located in the United States. The region of an organization cannot be changed after creation.

## Data retention

Shiftwell Cloud retains timesheets for 7 years. Shiftwell Cloud deletes customer data within 30 days after an organization is closed.

## Availability

Shiftwell Cloud has a 99.9% monthly uptime service level agreement on the Enterprise plan. The uptime service level agreement excludes scheduled maintenance windows announced at least 5 days in advance. The Standard plan does not include an uptime service level agreement.

## Personal data

Shiftwell stores staff names, contact details, qualifications, availability and worked hours. Shiftwell does not store patient or resident medical records. Shift notes are free text and can contain patient or resident information entered by staff. Shiftwell Mobile collects the phone's location only at the moment of clock-in when a geofence is enabled.
