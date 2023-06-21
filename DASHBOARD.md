  * Run `npx parcel build index.html` in dashboard subdir
  * Place files from `dashboard/dist/` on a public web server.
  * Run `mosquitto_passwd -c mosquitto_pass bot` ans set a password.
  * Create `mqtt.json` in secrets dir.

```json
{
    "host": "MOSQUITTO_HOST",
    "port": 9001,
    "user": "bot",
    "pass": "YOUR PASS"
}
```

  * Run `mosquitto -c mosquitto.conf` or similar
  * Deploy and send links like `http://web_host/#finanz|mqtt_host:9001` to user.

Soundfile used: https://pixabay.com/de/sound-effects/call-to-attention-123107/