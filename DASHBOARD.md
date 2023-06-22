# @UnifestBestellBot dynamic Dashboard
Additionally to the telegram-bot, there is a dashboard. Basically a
self-updating webpage showing currently open and WIP tickets for organizing
groups. For that we need two additional services:
- a mqtt broker (accessible from frontend) to forward information on new tickets and changes (moved to WIP or got closed, ...)
- a frontend page displaying updates from the mqtt broker

## MQTT Broker
First, we need to set a password, with which the bot can publish information at
the broker. Listening to updates does not require authentification.

```sh
$ mosquitto_passwd -c mosquitto_pass bot   # set a password
Password:
Reenter password:

$ cat <secrets-dir>/mqtt.json   # check configuration, so that the bot can connect later
{
  "host": "MOSQUITTO_HOST",
  "port": 8002,
  "user": "bot",
  "pass": "YOUR PASS"
}
$ mosquitto -c mosquitto.conf   # start the mqtt broker.
```
Ensure that the port is the same in both `mosquitto.conf` and `mqtt.json`.


## Frontend
We also need a frontend -- basically a small static webpage that gets updated dynamically by listening to the broker.
```sh
$ cd dashboard
$ npm install
...
$ npx parcel build index.html
...
$ npm run serve   # start frontend at `http://localhost:1234` (dev)
...
$ python3 -m http.server --directory dist 8003   # start frontend at `http://0.0.0.0:8003` (prod)
...
```

Alternatively you can just execute `nix-shell` in `dashboard`. This will run the prod setup.

## Usage
When all three are running (broker, bot, frontend), you can access the dashboard from e.g. `http://localhost:8003/#|localhost:8002`. Let me explain:
- `http://localhost:8003`  # where your frontend is hosted
- `/#[ORGA]`  # which updates to follow, e.g. `/#finanz` or `/#zentrale`, or `/#` for all of them.
- `|localhost:8002` where your mqtt broker is running

The frontend will automatically pull all open tickets from the bot, and get updates when tickets get opened, worked on, or closed.

## Misc
Soundfile used: https://pixabay.com/de/sound-effects/call-to-attention-123107/
