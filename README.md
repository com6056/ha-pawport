# Pawport for Home Assistant

Control a [Pawport](https://pawport.com) smart pet door from Home Assistant: lock it, hold it open, change its settings, and see where your pets are and when they last went through.

> [!WARNING]
> Early development. This integration uses the same cloud API as the Pawport app, which Pawport does not document, and it has not yet been run against a real door. Expect rough edges, and please open an issue with diagnostics if something looks wrong.
>
> Not affiliated with or endorsed by Pawport.

## Supported devices

The Pawport Smart Pet Door and Smart Pet Tag.

## What you get

Each door, pet and Smart Pet Tag on the account becomes a device. New ones appear on their own, and ones removed from the account are cleaned up.

### Door

| Entity | Type | Notes |
| --- | --- | --- |
| Door | Lock | The same lock as the Pawport app. |
| Hold open | Switch | Holds the door open until turned off. |
| Battery | Sensor | Percent charge. |
| Charging | Binary sensor | |
| Rain lock active / Lightning lock active | Binary sensor | On while a weather lock is holding the door shut. |
| Plugged in, Connectivity | Binary sensor | Diagnostic. Connectivity is off while the Pawport cloud cannot reach the door. |
| Firmware | Update | Shows when newer firmware is available. Install it from the Pawport app. |

Settings, with the same choices the Pawport app offers:

| Entity | Type | Range |
| --- | --- | --- |
| Sound, Lights, Panel buttons, Rain lock, Lightning lock | Switch | On or off. Panel buttons off disables the buttons on the door. |
| Volume, Light brightness | Number | 0 to 5 |
| Inside tag range, Outside tag range | Number | 1 to 5, about 1 to 5 feet |
| Time to close | Select | 5, 10, 15 or 30 seconds |
| Open angle | Select | 90° or 120° |

### Pet

| Entity | Type | Notes |
| --- | --- | --- |
| Location | Sensor | Inside or outside, from the last trip through a door. |
| Last trip | Sensor | When the pet last went through a door. |
| Trips outside today | Sensor | Resets at midnight in Home Assistant's time zone. |
| Time outside today | Sensor | |

### Smart Pet Tag

| Entity | Type | Notes |
| --- | --- | --- |
| Battery | Sensor | Diagnostic. |
| Connectivity | Binary sensor | Diagnostic. |

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

Google and Apple sign-in can't be used: their sign-in tokens are only issued to Pawport's own app. If your account uses one of them, try the emailed code.

## How it updates

The integration polls the Pawport cloud every 30 seconds and right after every command. It needs internet access; there is no local API.

## Known limitations

- Lock and light schedules, light color, and per-pet door access are not exposed yet; manage them in the Pawport app.
- Firmware updates are shown but not installed from Home Assistant.
- State can lag the door by up to 30 seconds when it changes outside Home Assistant.

## Troubleshooting

- **Download diagnostics** from the integration's menu. Tokens and your email are removed automatically.
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

Release by pushing a tag (`git tag v1.2.3 && git push origin v1.2.3`; a `-beta.N` suffix makes a pre-release). A workflow creates the release with `pawport.zip` attached and the version set from the tag. Releases are immutable once published.

## License

[MIT](LICENSE)
