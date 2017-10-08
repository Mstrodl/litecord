import collections
import logging

import pymongo

from .base import LitecordObject
from ..snowflake import _snowflake
from .message import Message

log = logging.getLogger(__name__)


BareCategory = collections.namedtuple('BareCategory', 'id')


class BaseChannel(LitecordObject):
    """Base class for all channels.
    
    Attributes
    ----------
    id: int
        Channel ID.
    type: int
        Channel Type.
    """
    def __init__(self, raw):
        log.debug(raw)
        self.id = int(raw['channel_id'])
        self.type = raw['type']

    def __eq__(self, other):
        return isinstance(other, BaseChannel) and other.id == self.id


class BaseTextChannel(BaseChannel):
    """Base text channel."""
    def __init__(self, raw):
        super().__init__(raw)
        self.last_message_id = -1
        self._update(raw)

    def _update(self, raw):
        self._raw = raw
        self.name = raw['name']


class BaseVoiceChannel(BaseChannel):
    """Base voice channel."""
    def __init__(self, raw):
        super().__init__(raw)
        BaseVoiceChannel._update(self, raw)

    def _update(self, raw):
        super()._update(raw)
        self._raw = raw
        self.name = raw['name']

        self.bitrate = raw['bitrate']
        self.user_limit = raw['user_limit']


class BaseGuildChannel(BaseChannel):
    """Base guild channel.

    Provides abstractions to work with channels
    that have members in a guild.
    """
    def __init__(self, guild, parent, raw):
        super().__init__(raw)
        BaseGuildChannel._update(self, guild, parent, raw)

    def _update(self, guild, parent, raw):
        super()._update(raw)
        self._raw = raw
        self.name = raw['name']
        self.guild = guild
        self.parent = parent

        self.guild_id = raw['guild_id']
        self.parent_id = raw.get('parent_id')
        self.position = raw['position']
        self.perm_overwrites = raw.get('perm_overwrites', [])

    @property
    def watchers(self):
        """Yields all :class:`Member` who are online
        and can watch the channel."""
        for member in self.guild.online_members:
            # if member.channel_perms[self.id].READ_MESSAGES: yield member
            yield member

    async def dispatch(self, evt_name, evt_data):
        """Dispatch an event to all channel watchers."""
        dispatched = 0
        for member in self.guild.viewers:
            if (await member.dispatch(evt_name, evt_data)):
                dispatched += 1

        log.debug(f'Dispatched {evt_name} to {dispatched} channel watchers')

        return dispatched

    async def delete(self):
        """Delete a channel"""
        return await self.guild_man.delete_channel(self)

    @property
    def as_invite(self):
        return {
            'id': str(self.id),
            'name': self.name,
            'type': self.type,
        }


class TextGuildChannel(BaseGuildChannel):
    """Represents a text channel.

    Attributes
    ----------
    topic: str
        Channel topic/description.
    last_message_id: int
        The last message created in the channel,
        it is only updated when you get the channel
        through :meth:`GuildManager.get_channel`.
    pins: list[int]
        List of message IDs that are pinned in the channel.
    """

    __slots__ = ('topic', 'last_message_id', 'pins')

    def __init__(self, server, parent, raw, guild=None):
        super().__init__(guild, parent, raw)
        self.server = server
        self.last_message_id = 0
        self._update(guild, parent, raw)

    def _update(self, guild, parent, raw):
        super()._update(guild, parent, raw)

        self.topic = raw['topic']
        self.pins = raw['pinned_ids']
        self.nsfw = raw.get('nsfw', False)

    def get_message(self, message_id):
        """Get a single message from a channel."""
        try:
            m = self.server.guild_man.get_message(message_id)
            if m.channel.id == self.id:
                return m
        except AttributeError:
            pass
        return None

    async def last_messages(self, limit=50):
        """Get the last messages from a text channel.

        Returns
        -------
        list: list of :class:`Message`
            Ordered(by time) list of message objects.
        """
        res = []
        cursor = self.server.message_coll.find({'channel_id': self.id}).sort('message_id', pymongo.DESCENDING)

        async for raw_message in cursor:
            if len(res) > limit:
                break

            m_id = raw_message['message_id']

            m = self.guild_man.get_message(m_id)
            if m:
                res.append(m)
            else:
                author = self.guild.members.get(raw_message['author_id'])
                m = Message(self.server, self, author, raw_message)
                self.guild_man.messages[m_id] = m
                res.append(m)

        log.debug('[tx_chan:last_messages] Got %d messages', len(res))
        return res

    async def add_pin(self, message_id: int):
        if message_id in self.pins:
            return
            
        before = len(self.pins)
        self.pins.append(message_id)

        result = await self.guild_man.channel_coll.update_one({'channel_id': self.id}, \
            {'$set': {'pinned_ids': self.pins}})
        
        log.info('Updated %d channel with %d to %d pins', \
                result.modified_count, before, len(self.pins))
        
        await self.guild_man.reload_channel(self)
        await self.dispatch('CHANNEL_PINS_UPDATE', {
            'channel_id': self.id
        })
        return

    async def remove_pin(self, message_id: int):
        if message_id not in self.pins:
            return

        before = len(self.pins)
        self.pins.remove(message_id)

        result = await self.guild_man.channel_coll.update_one({'channel_id': self.id}, \
            {'$set': {'pinned_ids': self.pins}})
        
        log.info('Updated %d channel with %d to %d pins', \
                result.modified_count, before, len(self.pins))
        
        await self.guild_man.reload_channel(self)
        await self.dispatch('CHANNEL_PINS_UPDATE', {
            'channel_id': self.id
        })
        return
 
    async def get_pins(self, limit=None):
        update = False
        pinned_messages = []

        cpy = self.pins[:limit]
        for message_id in cpy:
            m = self.guild_man.get_message(message_id)

            if m is None:
                self.pins.remove(m)
                update = True
                continue

            pinned_messages.append(m.as_json)

        if update:
            result = await self.guild_man.channel_coll.update_one({'channel_id': self.id}, \
                {'$set': {'pinned_ids': self.pins}})

            log.info('Updated %d channel with %d to %d pins', \
                result.modified_count, len(cpy), len(self.pins))

            await self.guild_man.reload_channel(self)

        return pinned_messages

    async def from_timestamp(self, timestamp):
        """Get all messages from the timestamp to latest"""
        # TODO: THIS IS INNEFICIENT. WE NEED TO YIELD IDFK HOW
        # BECAUSE THIS IS ASYNCIO AAAA

        # convert to millisecond timestamp
        timestamp *= 1000
        as_snowflake = _snowflake(timestamp)

        mc = self.server.message_coll
        cur = mc.find({'channel_id': self.id, 'message_id': {'$gt': as_snowflake}}).sort('message_id')
        return (await cur.to_list(length=None))

    async def delete_many(self, message_ids, bulk=False):
        """Delete many messages from a channel.
        
        Fires `MESSAGE_DELETE` for each deleted message.

        Parameters
        ----------
        message_ids: List[int]
            Message IDs to be deleted from the channel
        build: bool, optional
            If thie is going to fire a `MESSAGE_DELETE_BULK` instead of `MESSAGE_DELETE`.
            Defaults to :py:meth:`False`.

        Returns
        -------
        None
        """
        message_ids = sorted(message_ids, reverse=True)
        in_bulk = []

        for message_id in message_ids:
            r = await self.server.message_coll.delete_many({'channel_id': self.id, 'message_id': message_id})
            if r.deleted_count < 1:
                continue

            if not bulk:
                await self.dispatch('MESSAGE_DELETE', {
                    'channel_id': self.id,
                    'message_id': message_id,
                })
            else:
                in_bulk.append(message_id)

        if bulk:
            await self.dispatch('MESSAGE_DELETE_BULK', {
                'channel_id': self.id,
                'ids': in_bulk,
            })

    async def edit(self, payload: dict):
        """Edit a text channel with a text channel edit payload.
        
        Parameters
        ----------
        payload: dict
            Text channel edit payload.

        Returns
        -------
        A new :class:`TextChannel` object with the edited data
        """
        return await self.guild_man.edit_channel(self, payload)

    @property
    def as_json(self):
        return {
            'id': str(self.id),
            'guild_id': str(self.guild_id),
            'name': self.name,
            'type': self.type,
            'position': self.position,
            'permission_overwrites': [o.as_json for o in self.perm_overwrites],
            'topic': self.topic,
            'last_message_id': str(self.last_message_id),
            'nsfw': self.nsfw,
            'parent_id': str(self.parent_id),
        }

class GuildCategory(BaseGuildChannel):
    """A Guilg category for channels.
    
    *This is not fully implemented*.
    """
    def __init__(self, server, guild, raw):
        super().__init__(guild, None, raw)
        self.server = server
        self._update(guild, raw)

    def _update(self, guild, parent, raw):
        # We ignore parents
        # since categories cant be inside categories
        super()._update(guild, None, raw)
        self.nsfw = raw.get('nsfw', False)

    @property
    def as_json(self):
        return {
            'id': str(self.id),
            'guild_id': str(self.guild_id),
            'name': self.name,
            'position': self.position,
            'type': self.type,
            'permission_overwrites': self.perm_overwrites,
            'nsfw': self.nsfw,
            'parent_id': None,
        }

