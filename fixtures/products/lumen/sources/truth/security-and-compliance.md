---
title: Lumen security and compliance
kind: living
updated: 2026-08-14
url: https://docs.example-lumen.test/security
---

# Lumen security and compliance

This page describes how Northwind Devices protects Lumen Hub, Lumen Sensors and Lumen Cloud.

## Change approval policy

Lumen Hub supports a change approval policy for site configuration. When the approval policy is enabled, changes to schedules, setpoint limits and equipment mappings require approval from a second Administrator. No configuration change can bypass the approval policy. Pending changes expire if they are not approved within 72 hours. The approval policy is available on the Enterprise plan.

## Audit log

The Lumen audit log records every configuration change with the user, the time and the previous value. The Lumen audit log is retained for 13 months. Administrators can export the Lumen audit log as CSV.

## Encryption

- Data in transit between the Lumen Hub controller, the Lumen app and Lumen Cloud is encrypted with TLS 1.2 or later.
- Data at rest in Lumen Cloud is encrypted with AES-256.
- Radio traffic between Lumen Sensors and the Lumen Hub controller is encrypted with AES-128.

## Device security

Lumen Hub installs only firmware images signed by Northwind Devices. Lumen Hub rejects firmware images with an invalid signature. Lumen Hub does not accept inbound connections from the internet. The Lumen Hub touchscreen can be locked with a 6-digit PIN.

## Identity and access

Lumen app accounts support multi-factor authentication with an authenticator app. Administrators can require multi-factor authentication for every user in an organization. Single sign-on through SAML 2.0 is available on the Enterprise plan.

## Compliance

Northwind Devices has a SOC 2 Type II report for Lumen Cloud, available on request under a non-disclosure agreement. The SOC 2 Type II report covers the Lumen Cloud service and does not cover Lumen Edge Server installations. An independent security firm performs a penetration test of Lumen Cloud once per year. Northwind Devices offers a data processing agreement to Lumen Cloud customers.

## Data residency

Lumen Cloud customers choose the US region or the EU region when an organization is created. Lumen Cloud data for organizations in the EU region is stored in data centers located in Germany. Lumen Cloud data for organizations in the US region is stored in data centers located in the United States. The region of an organization cannot be changed after creation.

## Data retention

Lumen Cloud retains sensor history for 25 months. Lumen Cloud deletes customer data within 30 days after an organization is closed.

## Availability

Lumen Cloud has a 99.9% monthly uptime service level agreement on the Enterprise plan. The uptime service level agreement excludes scheduled maintenance windows announced at least 72 hours in advance. The Standard plan does not include an uptime service level agreement.

## Personal data

Lumen Sensors do not include cameras or microphones. Lumen Hub does not identify individual occupants.
