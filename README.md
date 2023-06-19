# @UnifestBestellBot
Telegram bot for stalls to order supplies such as drinks, cups or change at the unifest


## Usage
Package management is done via poetry, so we need:
- (a virtual environment)
- `poetry`
- `poetry` to install dependencies
```sh
> # first, the virtual environment:
> virtualenv .venv -p 3.9
> source .venv/bin/activate.fish  # or what your shell needs
> # now, install poetry
> pip install poetry
> # install dependencies
> poetry install
```

after that, simply execute
```sh
> python main.py
```
to run the program. See `-h` for help on arguments.

## Dashboard

  * Run mosquitto broker.
  * Configure to only accept trusted ip of bot on port 1883 mqtt protocol.
  * Configure to accept anonymous read only via websocket on port 9001.
  * Run `npx parcel build index.html` in dashboard subdir
  * Deploy and send links like `http://web_host/#finanz|mqtt_host:mqtt_ws_port` to user.

Soundfile used: https://pixabay.com/de/sound-effects/call-to-attention-123107/

### Todo

  * Validate crash safety.
  * Validate consistency when resetting bot data.

## Config
see configuration options in `lib/config.py`.
What you absolutely need is a directory for secrets, e.g. the list of groups,
but also the bot token, and ids for a managed channel or to notify the
developer.

## Demo
image1 | image2 | image3
:---:|:---:|:---:
![](imgs/start.jpg)  |  ![](imgs/registration1.jpg) | ![](imgs/registration2.jpg)
![](imgs/status1.jpg) | ![](imgs/other-2.jpg) | ![](imgs/work2.jpg)
![](imgs/close1.jpg) | ![](imgs/close2.jpg) | ![](imgs/all.jpg)

