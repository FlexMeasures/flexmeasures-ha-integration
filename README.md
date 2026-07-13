# FlexMeasures

The `flexmeasures` integration offers an integration for [HomeAssistant](https://www.home-assistant.io/) with [FlexMeasures](https://flexmeasures.io/) instances to schedule flexible energy assets.

FlexMeasures can be used to schedule batteries, EV's, heat storage, and other assets. The integration offers:

- A sensor for flexible asset schedules
- A service to retrieve a schedule
- A service to post measurements to a FlexMeasures instance
- A service to change an S2 control type



To add this integration the following configuration input is needed:

```yaml
# Example configuration.yaml entry
flexmeasures:
  host: "FLEXMEASURES_INSTANCE"
  username: "USERNAME"
  password: "PASSWORD"
  power_sensor: "POWER_SENSOR_ID"
  consumption_price_sensor: "CONSUMPTION_PRICE_SENSOR_ID"
  production_price_sensor: "PRODUCTION_PRICE_SENSOR_ID"
  soc_sensor: "STATE_OF_CHARGE_SENSOR_ID"
  rm_discharge_sensor: "RESOURCE_MANAGER_DISCHARGE_SENSOR_ID"
  schedule_duration: "SCHEDULE_DURATION"
  soc_unit: "STATE_OF_CHARGE_UNIT"
  soc_min: "STATE_OF_CHARGE_MINIMUM"
  soc_max: "STATE_OF_CHARGE_MAXIMUM"
```

{% configuration %}
host:
  description: URI of the FlexMeasures instance, for instance (flexmeasures.io)
  required: true
  type: string
username:
  description: The username associated with the FlexMeasures instance account.
  required: true
  type: string
password:
  description: The password with the FlexMeasures instance account.
  required: true
  type: string
power_sensor:
  description: The power sensor that will be scheduled to draw or supply power.
  required: true
  type: integer
consumption_price_sensor:
  description: The price sensor for the consumption of power to use for the optimization.
  required: true
  type: integer
production_price_sensor:
  description: The price sensor for the production of power to use for the optimization (this can be the same as the consumption price sensor).
  required: true
  type: integer
soc_sensor:
  description: The state of charge sensor of the flexible energy asset.
  required: true
  type: integer
rm_discharge_sensor:
  description: The resource manager discharge sensor.
  required: true
  type: integer
schedule_duration:
  description: The duration for which the schedules should be calculated in hours.
  required: true
  default: 24
  type: integer
soc_unit:
  description: The state of charge unit of energy.
  required: true
  default: kWh
  type: string
soc_min:
  description: The minimal state of charge that the flexible energy asset is allowed to reach.
  required: true
  type: float
soc_max:
  description: The maximum state of charge that the flexible energy asset is allowed to reach.
  required: true
  type: float
{% endconfiguration %}

{% include integrations/config_flow.md %}

## Schedule Sensor

The Flexmeasures Schedule sensor shows the values of the power draw or supply at the start of each interval. It contains a startdatetime, unit of measurement, and a device class as well. The schedule is automatically shifted up to be in line with the sensor resolution. 

```
schedule:
  - start: '2023-09-04T17:45:00+02:00'
    value: -0.5
  - start: '2023-09-04T18:00:00+02:00'
    value: -0.5
start: '2023-09-04T17:45:00+02:00'
unit_of_measurement: MWh
device_class: energy
friendly_name: FlexMeasures Schedule
```

## The scheduling service

For a schedule to be calculated a `soc_at_start` is required. All other variables needed to calculate a new schedule were provided in the configuration. The following `yaml` file will trigger a schedule and update the sensor:

```
action: flexmeasures_hacs.trigger_and_get_schedule
data:
  soc_at_start: "FLOAT_SOC_AT_START"
```

## Automate scheduling

The intended usage of FlexMeasures is letting the schedules and Home Assistant optimize the flexible energy assets without user interaction. Automations can be used to trigger new schedules when new information is available that would impact the schedule. Some examples of events that should trigger the request of new schedules are when the battery/asset is connected, when new prices are available, and periodically to match the executed schedule to the calculated schedule. The user will need to provide a Home Assistant entity as a `soc_at_start` to be used for triggering a schedule. This is an example `yaml` for the action set in the automations:

```
action: flexmeasures_hacs.trigger_and_get_schedule
data:
  soc_at_start: "\{\{ state_attr\('SENSOR_TYPE.SENSOR', 'SENSOR_ATTRIBUTES'\) \}\}"
```

## Which FlexMeasures server version you need

This integration ships flexmeasures-client 0.9.x, which posts and reads sensor data through endpoints that FlexMeasures serves from **0.28.0** on (triggering a schedule needs **0.27.0**). Against an older server, the integration still loads, but `post_measurements` and `get_measurements` fail when they are called. The integration logs a warning at startup when it finds a server that is too old.

Integration versions up to v0.3.6 shipped client 0.7.0, which still used the deprecated endpoints — so this is worth checking before upgrading from v0.3.6 or earlier.

## Several FlexMeasures servers

You can add the integration more than once, to talk to several FlexMeasures servers (or several accounts on one server) from the same Home Assistant. Each entry gets its own device, its own schedule sensor and its own S2 session.

With more than one entry configured, say which one an action is for:

```
action: flexmeasures_hacs.trigger_and_get_schedule
data:
  soc_at_start: "FLOAT_SOC_AT_START"
  entry_id: "THE_CONFIG_ENTRY_ID"
```

and connect a Resource Manager to the entry's own websocket endpoint, `/api/websocket_custom/<entry_id>`. With a single entry configured, both the `entry_id` field and the path suffix can be left out.

## Development

### Run the integration in a real Home Assistant (Docker)

The repo ships a Docker-based dev environment that runs a real Home Assistant
with the integration from your working tree mounted:

```
cd dev
docker compose up
```

Then open http://localhost:8123, complete onboarding, and add the
"FlexMeasures for HACS" integration. If your FlexMeasures server runs natively
on the host (port 5000), configure the integration with the URL
`http://host.docker.internal:5000`. After code changes, restart with
`docker compose restart homeassistant`.

If you have no FlexMeasures server, start one alongside Home Assistant:

```
docker compose --profile backend up
```

and use the URL `http://flexmeasures:5000` in the integration config. Seed the
backend with an account, user and sensors first, e.g.:

```
docker compose exec flexmeasures flexmeasures add toy-account
```

### Tests

Install the test requirements plus the integration requirements from the
manifest (tests must run against the exact versions Home Assistant installs
for users; `tests/test_manifest.py` guards this):

```
pip install -r requirements.test.txt
pip install $(python3 -c "import json; print(' '.join(json.load(open('custom_components/flexmeasures_hacs/manifest.json'))['requirements']))")
pytest
```

CI additionally runs a smoke test (`.github/workflows/smoke.yml`) that boots a
real Home Assistant container with a pre-seeded config entry and asserts the
integration migrates, sets up, and serves the S2 CEM handshake — this catches
manifest/requirement problems that in-process tests cannot.
