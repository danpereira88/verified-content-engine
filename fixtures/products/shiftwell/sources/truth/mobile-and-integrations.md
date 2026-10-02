---
title: Shiftwell Mobile and integrations
kind: living
updated: 2026-08-20
url: https://docs.shiftwell.example.test/mobile/integrations
---

# Shiftwell Mobile and integrations

This page describes the features of Shiftwell Mobile and the systems Shiftwell can connect to.

## Shiftwell Mobile features

Shiftwell Mobile shows each staff member their upcoming shifts, open shifts and leave balance. Staff can add their Shiftwell shifts to a personal calendar through an iCalendar feed. The iCalendar feed refreshes every 30 minutes. Staff can message the Scheduler on duty from Shiftwell Mobile. Messages in Shiftwell Mobile are retained for 12 months.

## Notifications

Shiftwell Mobile sends push notifications for new open shifts, swap requests, rota changes and approved leave. Push notifications for open shifts reach staff phones in under 5 seconds at the median when the phone has a network connection. Notifications are delivered by push notification and email on all plans. SMS notifications are available on the Enterprise plan. Staff can mute notifications outside their working hours.

## Clocking in and out

Staff clock in and out in Shiftwell Mobile or at a Shiftwell Time Clock. Administrators can require staff to be within a geofence when they clock in from Shiftwell Mobile. A geofence radius can be set between 50 meters and 1,000 meters. Clock-in times are rounded according to the rounding rule set by an Administrator. Missed clock-outs are flagged on the timesheet for the Scheduler to correct.

## Timesheets

Shiftwell builds a timesheet for each staff member from clock-in and clock-out records. Schedulers approve timesheets in Shiftwell Web. Approved timesheets can be exported as CSV or XLSX. Shiftwell does not calculate wages, taxes or deductions.

## Users and roles

Shiftwell has three roles: Staff, Scheduler and Administrator. Staff can see their own shifts and the rota for their locations. Schedulers can build rotas, offer open shifts and approve swaps and timesheets. Administrators can manage users, locations, staffing rules and organization settings.

## Integrations

### HR system import

Shiftwell imports staff records from a CSV file on all plans. Shiftwell imports staff records through SCIM 2.0 on the Enterprise plan. Staff records imported through SCIM 2.0 are updated within 15 minutes of a change in the source system.

### Shiftwell API

The Shiftwell API is a REST API available on the Enterprise plan. The Shiftwell API allows reading rotas, shifts, timesheets and staff profiles. The Shiftwell API allows creating shifts and open shifts. The Shiftwell API is limited to 120 requests per minute per API key. The Shiftwell API authenticates requests with API keys created by an Administrator.

### Webhooks

Shiftwell sends webhooks for published rotas, sick calls, accepted open shifts and approved timesheets. Webhooks are signed with an HMAC-SHA256 signature. Failed webhook deliveries are retried up to 6 times over 2 hours.

### Calendar and messaging

Shiftwell posts open-shift alerts to a Microsoft Teams channel or a Slack channel on the Enterprise plan. The Microsoft Teams and Slack connections send alerts only and cannot assign shifts.

## Accessibility

Shiftwell Web is designed to meet WCAG 2.1 level AA. Shiftwell Mobile supports the screen readers built into iOS and Android.

## Supported languages

Shiftwell Web and Shiftwell Mobile are available in English, Welsh, Irish, Polish and Portuguese.
