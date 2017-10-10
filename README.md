# Litecord
An open-source, (tries to be) functional implementation of a server that follows
the Discord API.

This has real shitty code, good luck

With litecord you can run your own "Discord", locally, by yourself, but with limitations
 * You can't use the official discord client with it, use [Atomic Discord](https://git.memework.org/heatingdevice/atomic-discord) instead.
 * Not very good code, expect the unexpected when running your server or accessing one.
 * Voice doesn't work nor is planned to be implemented into Litecord.
 * This is written in Python and it wasn't made to be resilient, don't DDoS a Litecord server
 * Ratelimits doesn't exist, yet.

## Installation

Make sure you have [MongoDB](https://www.mongodb.com/) installed and running.

```bash
# Clone the repo
git clone https://github.com/lnmds/litecord.git
cd litecord

# Create a virtual enviroment and install dependencies in it
# Make sure your python is 3.6+
python3 -m venv env/
env/bin/python3 -m pip install -r requirements.txt

# start the server
./run_litecord.sh
```

## Discord libraries

### Libraries that are known to work with Litecord
 - `discord.js`, used by Atomic Discord.
 - `discord.py`, both the `async` and `rewrite` branches.
  - Tip: edit `discord.http.Route.BASE` in `rewrite` to your litecord instance.
  - Example `discord.http.Route.BASE = 'http://0.0.0.0:8000/api'`
 - `Discordie`
  - Tip: `lib/Constants.js`, around lines 814 for API base,
    line 816 for cdn endpoint(`/images`)
 - `Eris`
  - Tip: `node_modules/eris/lib/rest/RequestHandler.js`, line 133

### Libraries that are known to not work with Litecord
 - `discord.io`

## Usage
When you start litecord it will fire up 3 servers by the default configuration:
 * Websocket used by the gateway at `:12000`
 * Websocket used by the voice gateway at `:6969`
 * A HTTP at `:8000`

## Updating
~~If you're braindead or smth~~
```bash
# pull
git pull
# profit
```

Restart the server to apply the changes. There isn't any way
of hot reloading.

## Folder structure
 * `/litecord` contains the actual litecord server code.
 * `/utils` has utilities to use within litecord code.
 * `/doc` has documentation on how the server actually does its stuff.
 * `/boilerplate_data`, [read this](https://git.memework.org/lnmds/litecord/src/master/boilerplate_data/README.md)
 * Depending on your installation, you might have a `/env` directory,
 **DON'T MESS WITH IT.**, don't install other libraries unless otherwise specified(pls don't break your server instance).

