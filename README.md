# Eway Solar Micro-Inverter for Home Assistant

Local telemetry from Eway **VN2T06/08/10EU** micro-inverters — sold under a
range of reseller badges (Solarsys and others) and monitored by the **Easy PV**
app from EasyCharging.

Per-panel power, voltage, current and temperature; grid voltage and frequency;
energy today and lifetime; WiFi signal, uptime and error code.

## Does this fit my inverter?

If your inverter is monitored by the **Easy PV** app (`com.eway.easy_pv`, by
**EasyCharging**), this is for you — whatever name is printed on the box.

**Model numbers:** `VN2T06EU` (600W), `VN2T08EU` (800W), `VN2T10EU` (1000W),
including suffixed variants such as `VN2T08EU-016212C`. The model and serial are
in the Easy PV app under *Equipment Details*.

**Sold as:** Eway, Solarsys, and various unbranded listings — these 600W/800W/
1000W dual-MPPT **balcony solar microinverters** are resold widely on Amazon and
AliExpress. One example is Amazon UK ASIN `B0H4Z3D1N9` ("Solarsys 800W Solar
Micro Inverter Kit"). If the listing says *WiFi app monitoring*, *IP67*, *dual
MPPT*, and ships with a **BC01** AC connector, it is very likely this family.

**Symptoms that led you here:** no local API, nothing open on any port,
no Modbus, no DTU, and no way to get the data out of the vendor cloud.

Only the 800W model has been tested end to end so far. The others are handled
by the same code path — reports welcome either way.

## Why this exists

These inverters have **no local API**. Not an undocumented one — none at all:
a full TCP scan of all 65,535 ports returns nothing open. They are pure MQTT
clients that connect outbound to the vendor's broker, and the app reads from
the cloud. The manual is explicit about it:

> "After Micro-inverter is connected to the user's router by WiFi, it
> communicates with the server through Internet access, and the background
> server communicates with the user's app."

However, **the inverter does not validate the broker's TLS certificate**. Point
its cloud hostname at a broker you control and it hands over the whole payload,
in plain, self-describing JSON. No reverse engineering required.

## What you have to do first

This integration consumes the telemetry. Getting the inverter to talk to your
broker is a one-off network change.

### 1. A TLS listener on your MQTT broker

The certificate's **CN must be the vendor hostname**:

```
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 3650 -nodes \
  -subj "/CN=inverter-mqtt-en.easycharging-tech.com" \
  -addext "subjectAltName=DNS:inverter-mqtt-en.easycharging-tech.com"
```

```
listener 8883
certfile /path/cert.pem
keyfile  /path/key.pem
require_certificate false
allow_anonymous true
```

> **Do not set `cafile`.** On the server side that asks for a *client*
> certificate, and the handshake dies with a bare
> `tlsv1 alert internal error`. This costs everyone an hour exactly once.

### 2. Redirect the vendor hostname to your broker

Override `inverter-mqtt-en.easycharging-tech.com` to your broker's IP:

- **OPNsense / pfSense** — Services → Unbound DNS → Overrides → add a host override
- **Pi-hole** — Local DNS → DNS Records
- **AdGuard Home** — Filters → DNS rewrites
- **OpenWRT** — `/etc/config/dhcp`: `list address '/inverter-mqtt-en.easycharging-tech.com/192.0.2.10'`

### 3. Make the inverter re-resolve

**It caches the resolved IP in RAM and will not look it up again on its own.**
Either power-cycle it, or drop its TCP state at the router
(`pfctl -k <inverter-ip>` on OPNsense/pfSense). It reconnects within seconds.

### 4. Add the integration

HACS → Custom repositories → this repo → Integration, then restart Home
Assistant.

Once the inverter reaches your broker it shows up under Settings → Devices &
Services → **Discovered**; confirm it there. Several inverters on one broker
each turn up on their own.

Settings → Devices & Services → Add Integration → **Eway Solar** works too: it
listens on `/+/+/data/post` and picks up the model and serial itself, skipping
inverters you have already added. If nothing turns up, the inverter is not
reaching your broker — revisit step 3.

## ⚠️ This stops the Easy PV app working

The vendor cloud is the app's only data source, so while the redirect is in
place the app shows nothing. Remove the DNS override to restore it.

Keeping both would need a transparent proxy that also forwards upstream, which
requires the device's MQTT password — mosquitto does not log it, so that needs
a small custom broker. Contributions welcome.

## The payload, for reference

```json
[{"sort":1,"rssi":-64,"inputVoltage":21.9,"InputCurrent":0.28,
  "gridVoltage":239.6,"gridFreq":50.1,"genPower":5.8,"genPowerToDay":3,
  "genPowerTotal":0.003,"temperature":28.9,"errCode":0,"duration":1857},
 {"sort":2, ...}]
```

One object per MPPT channel. `genPower` W, `genPowerToDay` Wh,
`genPowerTotal` kWh, `duration` seconds since start. Note `inputVoltage` but
`InputCurrent` — the capitalisation really is inconsistent.

The device also **subscribes** to `info/get`, `ota/get`, `function/get`,
`reset/get`, `property/get` and `ct/get`. Those are command channels and this
integration never writes to them. Publishing to `reset` or `function` blind
could reconfigure or factory-reset your inverter.

## Security note

The weakness exploited here is in the inverter's firmware, not in Home
Assistant, and it only lets you read your own device on your own network. It is
documented so owners can get their own data out of hardware that otherwise
holds it hostage.

## Licence

MIT.
