# ParemTech PTLevel

A Home Assistant custom integration that reads [ParemTech PTLevel](https://paremtech.com)
tank-level monitors straight from their WiFi receivers on your network. It needs
no ParemTech account, no API token and no internet connection.

> **Status: early development.** The first slice reads Version 1 receivers and
> reports the measured water column, battery, signal and report freshness. Tank
> level and volume, Version 2 receivers, and repair issues are still to come.

## How a PTLevel works

A PTLevel Long Range kit has two parts:

- A **transmitter** at the tank, connected by a thin air tube to a weighted
  pressure chamber resting on the tank floor. Water pressure squeezes the air
  trapped in the chamber, and the transmitter measures that air pressure.
- A **receiver** indoors on WiFi. The transmitter reports to it over 915 MHz
  LoRa, by default every 12 hours, or sooner when the level moves about 10%.

The receiver forwards each report to ParemTech's cloud, and also serves it on a
local status page. This integration reads only that page,
`http://<receiver>/config?json=true`, about once a minute.

## Supported hardware

| Receiver | How to tell | Supported |
| --- | --- | --- |
| Version 1, firmware 2xx (tested: hardware 4, firmware 214) | No button on the front | Yes |
| Version 2, firmware 4xx (spring 2024 and later) | Button on the front | Not yet: it serves a different local API |

The water column is computed only for transmitter **hardware 16**, whose pressure
scale has been checked. Older transmitters report a raw sensor voltage (zero
point near 60) that ParemTech says must be calibrated against a measured level;
for them the integration reports the raw reading and leaves the water column
unavailable.

ParemTech has said it will not ship further firmware for 2xx receivers, so the
local page this integration depends on is not expected to change.

## Installation

1. In **Settings → Marketplace**, add `https://github.com/nugget/paremtech-ptlevel`
   as a custom repository of type *Integration*. On Home Assistant older than
   2026.11, do the same in HACS.
2. Install **ParemTech PTLevel**. A first install needs no restart on 2026.11
   and later; updates, and installs through HACS, still do.
3. Give each receiver a DHCP reservation. Receivers do not announce themselves,
   and every unit sends the same DHCP hostname, `PTLevel-Wireless`.
4. Go to **Settings → Devices & services → Add integration → ParemTech PTLevel**
   and enter the receiver's address.

Each receiver is one entry, keyed by the receiver ID printed on its label (its
MAC address), so the same receiver cannot be added twice. If its address
changes, use **Reconfigure** on the entry.

## Entities

| Entity | Notes |
| --- | --- |
| Water column | Inches of water above the chamber's trapped air, from the last report. Transmitter hardware 16 only. |
| Transmitter status | *Awaiting first report*, *Reporting* or *Overdue*: where the transmitter stands. |
| Last report | When this integration first saw the current report. |
| Report overdue | Problem sensor: on when no new report has arrived for 13 hours. |
| Battery voltage | Transmitter battery pack; about 7 V is full. |
| Raw pressure reading | The transmitter's A/D count, for diagnosing leaks and calibration. |
| Transmitter signal | LoRa signal of the last report, in dBm. |
| Paired transmitter ID | The LoRa ID of the transmitter the receiver is paired with, known before it ever reports. |
| Failed transmissions | Receiver's count of failed reports; resets when it restarts. |
| Zero point | *Disabled by default.* The reading with the chamber out of the water. |
| Transmitter temperature | *Disabled by default.* An uncalibrated CPU temperature. |
| WiFi signal | *Disabled by default.* The receiver's WiFi signal, in dBm. |

### Reading the water column

The water column is the physical measurement: gauge pressure above the zero
point, at 100 counts per hectopascal and 2.4909 hPa per inch of water. It is
not yet the tank level:

- The chamber's air pocket sits a few inches above the tank floor, so the water
  column reads slightly less than the depth of water in the tank.
- It reads a little below zero when there is no pressure at all, with the
  chamber out of the water or the air tube leaking.
- The counts-per-inch scale comes from ParemTech's published pressure formula
  and has been checked against a one-foot dip. Check it against a measured
  depth before you rely on it.

### How freshness works

The receiver's status page has no timestamp. The integration treats any change
in the reading (pressure, zero point, battery, CPU temperature or LoRa signal)
as a new report and stamps it with the time it first saw it. A report that
arrives while Home Assistant is down is stamped when Home Assistant next sees
it.

Receivers keep reports only in memory, so a receiver restart blanks its status
page until the next report, which can be 12 hours away. The first report after
a blank page always counts as new, even if its values match the last one. The integration keeps
the last reading, and its timestamp, in Home Assistant storage, so the water
column stays available through receiver and Home Assistant restarts. Use
**Last report** and **Report overdue** to judge its age.

### Adding a receiver before its transmitter

You can add a receiver as soon as it is on WiFi, before its transmitter is in
the tank. Kits ship with the receiver already paired, so **Paired transmitter
ID** shows the transmitter's ID straight away, and **Transmitter status** reads
*Awaiting first report*. The transmitter's own entities (water column, battery,
signal, last report and report overdue) stay unavailable until the first
report arrives, because there is nothing to show yet. Pressing the button on the
side of the transmitter sends one; within a minute the status moves to
*Reporting* and the other entities fill in.

A receiver added while its status page is blank after a restart starts in the
same state, and leaves it with the transmitter's next report.

## Safety

The receiver's web pages link to `/disconnect`, `/reset_zero` and `/link`, and
a plain request to any of them acts immediately: it drops the receiver off
WiFi, overwrites the zero point, or starts transmitter pairing. The integration
can only build URLs for its read-only status path, and its tests enforce that.
The device's *Visit* link opens the receiver's status page, so take care what
you click there.

## Troubleshooting

- **Water column near zero, or slightly negative, with water in the tank:**
  no pressure is reaching the transmitter. Look for a leak or hole in the air
  tube, especially where it joins the transmitter, and a loose joint at the
  chamber.
- **Report overdue:** the transmitter has missed its scheduled report. Check
  **Transmitter signal** and **Failed transmissions**; a weak LoRa link (below
  about −120 dBm) causes missed reports. Press the button on the side of the
  transmitter to force a report.
- **"Not a supported PTLevel receiver":** the address answers, but not as a
  Version 1 receiver. Version 2 receivers are not supported yet.

Download diagnostics from the device page when reporting a problem. They carry
the receiver's status page with any credential-like keys redacted.

## License

Apache License 2.0. See [LICENSE](LICENSE).
