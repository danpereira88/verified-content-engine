---
title: Lumen operations and recovery
kind: living
updated: 2026-08-14
url: https://docs.example-lumen.test/operations
---

# Lumen operations and recovery

This page explains installation, firmware updates, outages and recovery for Lumen Hub sites.

## Installation

Lumen Hub must be installed by a Northwind Devices certified installer. A typical installation of one Lumen Hub controller and 10 Lumen Sensors takes about 3 hours. The installer maps each relay output and BACnet object to a zone in the Lumen app. Lumen Sensors pair with the Lumen Hub controller by pressing the pairing button for 3 seconds.

## Firmware updates

Northwind Devices releases Lumen Hub firmware updates over the air. Firmware updates install during the maintenance window set by a site Administrator. Lumen Hub restarts in under 90 seconds after a firmware update. During a restart, connected HVAC equipment holds its last relay state. Administrators can postpone a firmware update for up to 30 days. Security updates cannot be postponed for more than 7 days.

## Internet outages

Lumen Hub buffers sensor readings during an internet outage and uploads them when the connection returns. Lumen Hub keeps running its last synchronized schedule during an internet outage. Alerts generated during an internet outage are delivered when the connection returns. The Lumen app marks a Lumen Hub as offline after 10 minutes without contact.

## Power outages

Lumen Hub does not record sensor readings while the Lumen Hub controller has no power. After power returns, Lumen Hub resumes its schedule within 2 minutes. Lumen Sensors keep their pairing through a power outage.

## Emergency Site Recovery

Emergency Site Recovery lets a Northwind Devices support engineer restore a site's last known good configuration. Emergency Site Recovery is used when a configuration error leaves a site unable to heat or cool. Emergency Site Recovery applies configuration changes directly to the Lumen Hub, outside the approval policy. Emergency Site Recovery requires a request from the organization owner and a verification call. Every Emergency Site Recovery action is recorded in the Lumen audit log.

## Factory reset

Holding the Lumen Hub reset button for 10 seconds restores factory settings. A factory reset removes all local schedules and sensor pairings. A factory reset does not delete data already stored in Lumen Cloud.

## Support

Standard plan support is available by email during business hours in the customer's region. Enterprise plan support includes a 1-hour response target for critical incidents, 24 hours a day. Enterprise plan customers have a named customer success manager.

## Hardware replacement

Northwind Devices ships a replacement Lumen Hub controller within 2 business days for a warranty claim. A replacement Lumen Hub controller restores its configuration from Lumen Cloud after it is paired to the site.
