# Pawport for Home Assistant

Control a [Pawport](https://pawport.com) smart pet door from Home Assistant: lock and unlock it, hold it open, and watch its battery and connection.

> [!WARNING]
> Early development. This integration uses the same cloud API as the Pawport app, which Pawport does not document, and it has not yet been run against a real door. Expect rough edges, and please open an issue with diagnostics if something looks wrong.
>
> Not affiliated with or endorsed by Pawport.

## Supported devices

The Pawport Smart Pet Door. Every door on the account is added, and doors added to the account later appear on their own.

## What you get

For each door:

| Entity | Type | Notes |
| --- | --- | --- |
| Door | Lock | The same lock as the Pawport app. |
| Hold open | Switch | Holds the door open until turned off. |
| Battery | Sensor | Percent charge. |
| Charging | Binary sensor | |
| Plugged in | Binary sensor | Diagnostic. |
| Connectivity | Binary sensor | Diagnostic. Off while the Pawport cloud cannot reach the door. |

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

- Pet activity, tags, schedules, and door settings (open time, sensor range, LEDs, sound, weather locks) are not exposed yet.
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

Releases come from publishing a GitHub release; a workflow attaches `pawport.zip` with the version set from the tag.

## License

[MIT](LICENSE)
