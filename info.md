# ParemTech PTLevel

Local-only Home Assistant integration for ParemTech PTLevel tank-level
monitors. It reads each PTLevel WiFi receiver's status page on your network,
with no ParemTech account, token or internet connection.

## Highlights

- UI setup by receiver address, keyed by the receiver ID so a receiver cannot be
  added twice; reconfigure moves an entry to a new address.
- Water column above the pressure chamber, battery voltage, LoRa and WiFi
  signal, and failed-transmission count.
- Report freshness: a last-report timestamp and an overdue problem sensor,
  inferred from changes in the reading.
- The last reading survives receiver and Home Assistant restarts.
- Strictly read-only: the receiver's one-click action pages are unreachable by
  construction.

Supports Version 1 receivers (firmware 2xx). See the
[project README](https://github.com/nugget/paremtech-ptlevel#readme) for setup,
entities and limitations.
