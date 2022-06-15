# UnifestBestellBot
Telegram Bot to order drinks for stalls at the unifest

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

## Config
see configuration options in `lib/config.py`.
What you absolutely need is a directory for secrets, e.g. the list of groups,
but also the bot token, and ids for a managed channel or to notify the
developer.
