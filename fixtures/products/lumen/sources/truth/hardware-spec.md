---
title: Lumen Hub hardware specification
kind: living
updated: 2026-08-14
url: https://docs.example-lumen.test/hardware/specification
---

# Lumen Hub hardware specification

This page lists the physical and electrical specifications of the Lumen Hub controller and Lumen Sensors. All values apply to hardware revision C and firmware 3.4.

## Lumen Hub controller

### Physical

- The Lumen Hub controller measures 120 x 120 x 28 mm.
- The Lumen Hub controller weighs 310 g.
- The Lumen Hub controller has a 3.5-inch color touchscreen with a resolution of 480 x 480 pixels.
- The Lumen Hub controller operates between 0 °C and 45 °C ambient temperature.
- The Lumen Hub controller enclosure is rated IP20 and is intended for indoor use only.

### Power

The Lumen Hub controller is powered by 24 VAC from the HVAC system or by Power over Ethernet (IEEE 802.3af). The Lumen Hub controller draws a maximum of 6 W. The Lumen Hub controller does not include a battery backup.

### Connectivity

- The Lumen Hub controller connects to the internet over Wi-Fi (2.4 GHz and 5 GHz) or 100 Mbps Ethernet.
- The Lumen Hub controller communicates with Lumen Sensors over a sub-GHz radio.
- The sub-GHz radio uses 868 MHz in the EU model and 915 MHz in the North America model.
- Each Lumen Hub pairs with up to 64 wireless Lumen Sensors.

### Inputs and outputs

- The Lumen Hub controller has 8 relay outputs rated at 24 VAC and 1 A each.
- The Lumen Hub controller has 4 analog inputs that accept 0-10 V signals.
- The Lumen Hub controller has 2 dry-contact inputs for occupancy or alarm signals.

### Storage

Lumen Hub stores up to 30 days of sensor readings in local memory. When local memory is full, Lumen Hub overwrites the oldest readings first.

## Lumen Sensors

### Measurement accuracy

- Lumen Sensor temperature accuracy is ±0.2 °C between 15 °C and 30 °C.
- Lumen Sensor temperature accuracy is ±0.5 °C outside the 15 °C to 30 °C range.
- Lumen Sensor relative humidity accuracy is ±2% RH between 20% and 80% RH.
- Lumen Sensor CO2 accuracy is ±(40 ppm + 3% of reading) between 400 ppm and 5,000 ppm.
- Lumen Sensors require a 7-day self-calibration period after installation before CO2 readings reach the stated accuracy.

### Radio range

Lumen Sensors have a radio range of up to 150 meters in open line of sight. Typical indoor range through walls is about 40 meters. Range depends on wall materials and interference.

### Battery

Lumen Sensors use two AA lithium batteries. Lumen Sensor batteries last up to 5 years at the default 5-minute reporting interval. Shorter reporting intervals reduce battery life. The Lumen app sends a low-battery alert when a sensor battery falls below 15%.

### Reporting interval

The default Lumen Sensor reporting interval is 5 minutes. Administrators can set the reporting interval between 1 minute and 15 minutes.

## Regulatory

- The Lumen Hub controller carries CE marking for sale in the EU.
- The Lumen Hub controller complies with FCC Part 15 Class B for sale in the United States.
- Lumen Sensors carry the same regulatory markings as the Lumen Hub controller for their sales region.

## Warranty

Lumen Hub controller hardware includes a 3-year limited warranty. Lumen Sensors include a 2-year limited warranty. The warranty does not cover damage from incorrect wiring.
