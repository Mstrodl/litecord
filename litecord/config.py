import json


with open('litecord_config.json') as fp:
    locals().update(json.load(fp))
