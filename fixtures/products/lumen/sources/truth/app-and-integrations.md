---
title: Lumen app and integrations
kind: living
updated: 2026-08-14
url: https://docs.example-lumen.test/app/integrations
---

# Lumen app and integrations

This page describes the features of the Lumen app and the systems Lumen Hub can integrate with.

## Schedules and setpoints

The Lumen app lets Operators and Administrators create weekly schedules for each zone. Each schedule supports up to 8 time periods per day. Administrators can set minimum and maximum setpoint limits for each zone. Occupants who adjust the Lumen Hub touchscreen cannot move a setpoint outside the zone's limits.

Setpoint changes made in the Lumen app reach the Lumen Hub in under 2 seconds at the median on a broadband connection. Setpoint changes take longer on cellular or congested networks.

## Alerts

The Lumen app sends alerts for out-of-range temperature, high CO2, equipment faults, offline Hubs and low sensor batteries. Alerts are delivered by push notification and email on all plans. SMS alerts are available on the Enterprise plan.

## Energy reports

The Lumen app produces daily, weekly and monthly energy reports for each site. Energy reports estimate HVAC runtime per zone from relay activity. Energy reports can be exported as CSV or PDF. Energy reports are estimates and are not a substitute for metered utility data.

## Users and roles

The Lumen app has three roles: Viewer, Operator and Administrator. Viewers can see readings and reports. Operators can change setpoints and schedules. Administrators can manage users, equipment mappings and site settings. Single sign-on through SAML 2.0 is available on the Enterprise plan.

## Occupancy Forecasting

Occupancy Forecasting is in beta. Occupancy Forecasting predicts zone occupancy for the next 24 hours from CO2 readings, dry-contact occupancy inputs and schedules. Occupancy Forecasting can pre-heat or pre-cool a zone before predicted arrival. Occupancy Forecasting requires firmware 3.4 or later. Occupancy Forecasting is available on the Enterprise plan. Beta features are not covered by the uptime service level agreement.

## Integrations

### BACnet

Lumen Hub reads and writes BACnet/IP objects. BACnet/IP write support requires firmware 3.2 or later. Lumen Hub connects to BACnet MS/TP equipment through a BACnet MS/TP to IP router (or software equivalent).

### Modbus

Lumen Hub reads Modbus TCP registers from meters and variable-speed drives. Lumen Hub does not write Modbus registers.

### Demand response

Lumen Hub supports OpenADR 2.0b demand response events. During a demand response event, Lumen Hub can raise cooling setpoints or lower heating setpoints by up to 3 °C. Administrators can opt individual zones out of demand response events.

### Lumen API

The Lumen API is a REST API available on the Enterprise plan. The Lumen API allows reading sensor history, zone status and schedules. The Lumen API allows writing setpoints and schedules. The Lumen API is limited to 60 requests per minute per API key. The Lumen API authenticates requests with API keys created by an Administrator.

### Webhooks

Lumen Hub sends webhooks for alerts and configuration changes. Webhooks are signed with an HMAC-SHA256 signature. Failed webhook deliveries are retried up to 5 times over 1 hour.

## Supported languages

The Lumen app is available in English, German, French, Spanish and Dutch.
