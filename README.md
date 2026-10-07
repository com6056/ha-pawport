# Pawport for Home Assistant

Control a [Pawport](https://pawport.com) smart pet door from Home Assistant. Lock it, hold it open, change its settings, and see where your pets are and when they last went through.

> [!WARNING]
> This is early! It uses the same cloud API as the Pawport app, which Pawport doesn't document, and it hasn't been run against a real door yet. Expect rough edges, and please open an issue with diagnostics if anything looks off.
>
> Not affiliated with or endorsed by Pawport.

## Supported devices

The Pawport Smart Pet Door and Smart Pet Tag.

## What you get

Each door, pet and Smart Pet Tag on the account becomes a device. New ones appear on their own, and ones removed from the account are cleaned up.

### Door

| Entity | Type | Notes |
| --- | --- | --- |
| Door | Lock | Same lock as in the Pawport app |
| Hold open | Switch | Holds the door open until you turn it off |
| Battery | Sensor | Percent charge |
| Charging | Binary sensor | |
| Plugged in | Binary sensor | |
| Connectivity | Binary sensor | Off while the Pawport cloud can't reach the door |
| Rain lock active, Lightning lock active | Binary sensor | On while a weather lock is holding the door shut |
| Firmware | Update | Shows when new firmware is out (install it from the Pawport app) |

Settings, with the same choices the Pawport app offers:

| Entity | Type | Range |
| --- | --- | --- |
| Sound, Lights, Rain lock, Lightning lock | Switch | On or off |
| Panel buttons | Switch | Off disables the buttons on the door |
| Volume, Light brightness | Number | 0 to 5 |
| Inside tag range, Outside tag range | Number | 1 to 5, about 1 to 5 feet |
| Time to close | Select | 5, 10, 15 or 30 seconds |
| Open angle | Select | 90° or 120° |

Schedules set up in the Pawport app:

| Entity | Type | Notes |
| --- | --- | --- |
| Schedule *name* | Switch | One per lock schedule, to turn it on or off. Its attributes show the days, the time window, and what it allows (in only, out only, or locked) |
| Light schedule | Switch | Turns the door's light schedule on or off |

### Pet

| Entity | Type | Notes |
| --- | --- | --- |
| Location | Sensor | Inside or outside, going by the last trip through a door |
| Last trip | Sensor | When the pet last went through a door |
| Trips outside today | Sensor | Resets at midnight in Home Assistant's time zone |
| Time outside today | Sensor | |

### Smart Pet Tag

| Entity | Type | Notes |
| --- | --- | --- |
| Battery | Sensor | |
| Connectivity | Binary sensor | |

## Installation

### HACS

1. In HACS, open the three-dot menu > **Custom repositories** and add `https://github.com/com6056/ha-pawport` as an **Integration**.
2. Install **Pawport** and restart Home Assistant.

### Manual

Copy `custom_components/pawport` from the [latest release](https://github.com/com6056/ha-pawport/releases/latest) into your `config/custom_components/` directory and restart Home Assistant.

## Setup

**Settings > Devices & services > Add integration > Pawport**, then enter your Pawport account's email and choose how to sign in:

- **Email me a sign-in code** (what the Pawport app does). If the session ever expires, Home Assistant asks you to sign in again.
- **Use my password**, if your account has one. The password is stored so the integration can sign in again on its own when the session expires.

Google and Apple sign-in won't work here, since their sign-in tokens only go to Pawport's own app. If your account uses one of them, try the emailed code.

To switch between a code and a password, change the stored password, or follow a change to the account's email, use **Reconfigure** from the integration's menu.

## Use cases

- Keep pets in when something makes the yard unsafe, like a gate left open, the pool cover off, or a delivery at the side door.
- Get a notification when a pet goes out or comes back, or hasn't come back after dark.
- Lock up when everyone leaves, or switch to a stricter lock schedule while you're away.
- Track how long each pet spends outside, with Home Assistant's history and statistics.

## Examples

Lock the door while the backyard gate is open, and unlock it once the gate has been closed for a minute:

```yaml
automation:
  - alias: Pet door follows the backyard gate
    triggers:
      - trigger: state
        entity_id: binary_sensor.backyard_gate
        to: "on"
        id: opened
      - trigger: state
        entity_id: binary_sensor.backyard_gate
        to: "off"
        for: "00:01:00"
        id: closed
    actions:
      - action: "lock.{{ 'lock' if trigger.id == 'opened' else 'unlock' }}"
        target:
          entity_id: lock.dog_door
```

Tell me when a pet comes in or goes out:

```yaml
automation:
  - alias: Pet came in or went out
    triggers:
      - trigger: state
        entity_id: sensor.biscuit_location
        to: [inside, outside]
    actions:
      - action: notify.mobile_app_my_phone
        data:
          message: "Biscuit is {{ trigger.to_state.state }}."
```

Remind me if the door has been locked for an hour:

```yaml
automation:
  - alias: Pet door still locked
    triggers:
      - trigger: state
        entity_id: lock.dog_door
        to: locked
        for: "01:00:00"
    actions:
      - action: notify.mobile_app_my_phone
        data:
          message: The pet door has been locked for an hour.
```

## How it updates

The integration polls the Pawport cloud every 30 seconds and right after every command. There's no local API, so it needs internet access.

## Known limitations

- Schedules can be turned on and off, but creating or editing them, light color, and per-pet door access stay in the Pawport app.
- Firmware updates are shown but not installed from Home Assistant.
- State can lag the door by up to 30 seconds when it changes outside Home Assistant.

## Troubleshooting

- **Download diagnostics** from the integration's menu. Tokens and your email are stripped out automatically.
- To enable debug logging:

  ```yaml
  logger:
    logs:
      custom_components.pawport: debug
  ```

## Removal

**Settings > Devices & services > Pawport > three dots > Delete**, then remove it from HACS if you installed it that way.

## Development

Needs [uv](https://docs.astral.sh/uv/).

```bash
scripts/setup     # install the dev environment
scripts/lint      # format, lint, type check
scripts/test      # tests with coverage
scripts/develop   # run Home Assistant at http://localhost:8123 with this integration
```

Release by pushing a tag, like `git tag v1.2.3 && git push origin v1.2.3` (a `-beta.N` suffix makes it a pre-release). A workflow creates the release with `pawport.zip` attached and the version set from the tag. Releases can't be changed once they're out.

## License

[MIT](LICENSE)
