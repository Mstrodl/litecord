import json
import logging
import asyncio
import base64
import os
import hashlib
import uuid

import sha3
import aiohttp

from random import randint
from aiohttp import web

log = logging.getLogger(__name__)

ERR_TRANSLATOR = {
    10001: 'Unknown Account',
    10002: 'Unknown Application',
    10003: 'Unknown Channel',
    10004: 'Unknown Guild',
    10005: 'Unknown Integration',
    10006: 'Unknown Invite',
    10007: 'Unknown Member',
    10008: 'Unknown Message',
    10009: 'Unknown Overwrite',
    10010: 'Unknown Provider',
    10011: 'Unknown Role',
    10012: 'Unknown Token',
    10013: 'Unknown User',
    20001: 'Bots cannot use this endpoint',
    20002: 'Only bots can use this endpoint',
    30001: 'Maximum number of guilds reached (100)',
    30002: 'Maximum number of friends reached (1000)',
    40001: 'Unauthorized',
    50001: 'Missing Access',
    50002: 'Invalid Account Type',
    50003: 'Cannot execute action on a DM channel',
    50004: 'Embed Disabled',
    50005: 'Cannot edit a message authored by another user',
    50006: 'Cannot send an empty message',
    50007: 'Cannot send messages to this user',
    50008: 'Cannot send messages in a voice channel',
    50009: 'Channel verification level is too high',
    50010: 'OAuth2 application does not have a bot',
    50011: 'OAuth2 application limit reached',
    50012: 'Invalid OAuth State',
    50013: 'Missing Permissions',
    50014: 'Invalid authentication token',
    50015: 'Note is too long',
    50016: 'Provided too few or too many messages to delete. Must provide at least 2 and fewer than 100 messages to delete.',
    50019: 'A message can only be pinned to the channel it was sent in',
    50034: 'A message provided was too old to bulk delete',
    90001: 'Reaction Blocked',
}

ERRNO_TO_HTTPERR = {
    40001: 403,
}


async def random_digits(n):
    """Returns `n` random digits"""
    range_start = 10**(n-1)
    range_end = (10**n)-1
    return randint(range_start, range_end)


async def get_random_salt(size=64):
    return base64.b64encode(os.urandom(size)).decode()


def pwd_hash(plain, salt):
    return hashlib.sha3_512(f'{plain}{salt}'.encode()).hexdigest()


def _err(msg='', errno=None, status_code=500):
    """Error object."""
    headers = {aiohttp.hdrs.CONTENT_TYPE: 'application/json'}

    status_code = ERRNO_TO_HTTPERR.get(errno, status_code)
    err_msg = ERR_TRANSLATOR.get(errno, None)

    log.debug(f"Erroring msg={msg!r} errno={errno!r} status={status_code!r} err_msg={err_msg!r}")

    if errno is not None:
        return web.Response(status=status_code, headers=headers, body=json.dumps({
            'code': errno,
            'message': err_msg
        }).encode())

    return web.Response(status=status_code, headers=headers, body=json.dumps({
        'code': 0,
        'message': msg
    }).encode())


def dt_to_json(dt):
    """Convert a `datetime.datetime` object to a JSON serializable string"""
    try:
        return dt.isoformat()
    except:
        return None


def _json(obj, **kwargs):
    """Return a JSON response"""
    headers = {aiohttp.hdrs.CONTENT_TYPE: 'application/json'}

    if kwargs.get('headers') is not None:
        headers.update(kwargs.get('headers'))
        kwargs.pop('headers')

    return web.Response(body=json.dumps(obj).encode(),
        text=None,
        charset=None,
        headers=headers,
        **kwargs
    )


# Modification of https://stackoverflow.com/questions/312443/how-do-you-split-a-list-into-evenly-sized-chunks
def chunk_list(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i:i + n]


def get(lst, **kwargs):
    """Get an object from a list that matches the search criteria in ``**kwargs``.

    Parameters
    ----------
    lst: list
        List to be searched.
    """

    for element in lst:
        for attr, val in kwargs.items():
            res = getattr(element, attr)
            if res == val:
                return element

    return


def delete(lst, **kwargs):
    """Delete an element from a list that matches the search criteria in ``**kwargs``

    Parameters
    ----------
    lst: list
        List to be searched.
    """

    for (idx, element) in enumerate(lst):
        for attr, val in kwargs.items():
            res = getattr(element, attr)
            if res == val:
                del lst[idx]
                return element

    return

async def maybe_coroutine(func):
    if asyncio.iscoroutine(func):
        return await func
    else:
        return func()

def random_sid():
    """Generate a new random Session ID."""
    return hashlib.md5(str(uuid.uuid4().fields[-1]).encode()).hexdigest()
