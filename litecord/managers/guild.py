import logging
import asyncio
import datetime
import time

from collections import defaultdict

from ..objects import Guild, TextGuildChannel, VoiceGuildChannel, \
    Message, Invite, Role, BareGuild, BareCategory, BaseTextChannel, \
    BaseGuildChannel, GuildCategory
from ..snowflake import get_snowflake, get_invite_code
from ..utils import get
from ..enums import ChannelType
from ..iterators import AsyncIteratorWrapper

log = logging.getLogger(__name__)


class GuildManager:
    """Manager class for guilds, channels, roles, messages and invites.

    Attributes
    ----------
    server: :class:`LitecordServer`
        Server instance.

    raw_members : list[dict]
        Raw member cache.
    roles : list[:class:`Role`]
        Role cache.
    channels : list[:class:`GuildTextChannel` or :class:`GuildVoiceChannel`]
        Channel cache.
    guilds : list[:class:`Guild`]
        Guild cache.
    invites : list[:class:`Invite`]
        Invite cache.
    messages : list[:class:`Message`]
        Message cache.
    """
    def __init__(self, server):
        self.server = server

        self.role_coll = server.role_coll
        self.channel_coll = server.channel_coll
        self.guild_coll = server.guild_coll
        self.invite_coll = server.invite_coll
        self.message_coll = server.message_coll
        self.member_coll = server.member_coll

        self.raw_members = defaultdict(dict)
        self.roles = []
        self.channels = []
        self.guilds = []
        self.invites = []
        self.messages = []

    async def _load(self):
        await self.init()

    def get_guild(self, guild_id):
        """Get a :class:`Guild` object by its ID."""
        try:
            guild_id = int(guild_id)
        except ValueError:
            return
        return get(self.guilds, id=guild_id)

    def get_channel(self, channel_id):
        """Get a :class:`Channel` object by its ID."""
        try:
            channel_id = int(channel_id)
        except (ValueError, TypeError):
            return

        channel = get(self.channels, id=channel_id)
        if channel is None:
            return

        async def _updater():
            if not isinstance(channel, BaseTextChannel):
                return

            mlist = await channel.last_messages(1)
            try:
                m_id = mlist[0].id
            except:
                m_id = None
            channel.last_message_id = m_id

        asyncio.ensure_future(_updater())
        return channel

    def get_role(self, role_id: int):
        """Get a :class:`Role` by its ID."""
        try:
            role_id = int(role_id)
        except (ValueError, TypeError):
            return
        r = get(self.roles, id=role_id)
        log.debug('[get_role] %d -> %r', role_id, r)
        return r

    def get_message(self, message_id):
        """Get a :class:`Message` object by its ID."""
        try:
            message_id = int(message_id)
        except (ValueError, TypeError):
            return
        m = get(self.messages, id=message_id)
        log.debug('[get_message] %d -> %r', message_id, m)
        return m

    def get_invite(self, invite_code: str):
        """Get an :class:`Invite` object.

        Parameters
        ----------
        invite_code: str
            Invite code to search on

        Returns
        -------
        :class:`Invite` or :py:meth:`None`
        """
        return get(self.invites, code=invite_code)

    def get_raw_member(self, guild_id: int, user_id: int) -> dict:
        """Get a raw member.

        guild_id: int
            Guild ID from the member.
        user_id: int
            User ID that references the member.

        Returns
        -------
        dict
            Raw member.
        """
        try:
            guild_id = int(guild_id)
            user_id = int(user_id)
        except:
            return

        try:
            raw_guild_members = self.raw_members[guild_id]
        except:
            return

        try:
            return raw_guild_members[user_id]
        except:
            return

    def yield_guilds(self, user_id: int) -> AsyncIteratorWrapper:
        """Yield all guilds the user is in asynchronously.

        Parameters
        ----------
        user_id: int
            User ID to search.

        Yields
        ------
        :class:`Guild`
            A guild this user is in.
        """
        guilds = filter(lambda g: user_id in g.member_ids, self.guilds)
        return AsyncIteratorWrapper(guilds)

    def all_guilds(self):
        """Yield all available guilds."""
        for guild in self.guilds:
            yield guild

    async def new_message(self, channel, author_user, raw):
        """Create a new message and put it in the database.

        Dispatches MESSAGE_CREATE events to respective clients.

        Parameters
        ----------
        channel: :class:`Channel`
            The channel where to put the new message.
        author: :class:`User`
            The author of the message.
        raw: dict
            Raw message object.

        Returns
        -------
        :class:`Message`
            The created message.
        """

        author = channel.guild.members.get(author_user.id)
        message = Message(self.server, channel, author, raw)
        result = await self.message_coll.insert_one(raw)
        if not result.acknowledged:
            log.warning('[mcoll:insert] not acknowledged')

        self.messages.append(message)
        log.info(f'Adding message with id {message.id}')

        await channel.dispatch('MESSAGE_CREATE', message.as_json)
        return message

    async def delete_message(self, message) -> 'None':
        """Delete a message.

        Dispatches MESSAGE_DELETE events to respective clients.

        Parameters
        ----------
        message: :class:`Message`
            Message to delete.

        """

        result = await self.message_coll.delete_one({'message_id': message.id})
        log.info(f"Deleted {result.deleted_count} messages")

        await self.reload_message(message)

        await message.channel.dispatch('MESSAGE_DELETE', {
            'id': str(message.id),
            'channel_id': str(message.channel.id),
        })

    async def edit_message(self, message, payload) -> 'None':
        """Edit a message.

        Dispatches MESSAGE_UPDATE events to respective clients.

        Parameters
        ----------
        message: :class:`Message`
            Message to edit.
        payload: dict
            Message edit payload.
        """

        result = await self.message_coll.update_one({'message_id': message.id},
                                                    {'$set': payload})
        log.info(f"Updated {result.modified_count} messages")

        message = await self.reload_message(message)

        await message.channel.dispatch('MESSAGE_UPDATE', message.as_json)

    async def reload_guild(self, guild):
        """Update a guild.

        Retrieves the raw guild from the database,
        and updates the received guild with the new data.

        Since usually :meth:`GuildManager.get_guild`, which
        is the usual method to retrieve guild objects, very
        probably the received guild in this function
        is already a guild from the cache, meaning that
        updating the received guild means the guild in the
        cache is updated as well.

        Parameters
        ----------
        guild : :class:`Guild`
            The guild object to be updated with new data

        Returns
        -------
        :class:`Guild`
            The updated guild object, it is the same object
            as the received guild.
        :py:meth:`None`
            If the guild doesn't exist anymore.
            The guild gets removed from the cache.
        """

        # The strategy here is to query the database
        # with the guild id and check if it exists or not
        # and do the appropiate actions

        assert isinstance(guild, Guild)

        query = {'guild_id': guild.id}
        raw_guild = await self.guild_coll.find_one(query)
        if raw_guild is None:
            log.info('[guild:reload] Guild not found, deleting from cache')
            try:
                self.guilds.remove(guild)
            except ValueError:
                pass

            for channel in guild.channels:
                try:
                    self.channels.remove(channel)
                except ValueError:
                    pass

            for role in guild.roles:
                try:
                    self.roles.remove(role)
                except ValueError:
                    pass

            del guild
            return

        guild._raw.update(raw_guild)
        guild._update(guild._raw)
        return guild

    async def reload_channel(self, channel):
        """Reload one channel.

        Merges the raw channel the channel object refernces
        with the new data from the database.

        Follows the same strategies as :meth:`GuildManager.reload_guild`.
        """

        query = {'channel_id': channel.id}
        raw_channel = await self.channel_coll.find_one(query)
        if raw_channel is None:
            log.info('[channel:reload] chid=%d not found, deleting from cache',
                     channel.id)
            try:
                if isinstance(channel, BaseGuildChannel):
                    channel.guild.channels.pop(channel.id)
            except ValueError:
                pass

            try:
                self.channels.remove(channel)
            except ValueError:
                pass

            del channel
            return

        channel._raw.update(raw_channel)

        if isinstance(channel, BaseGuildChannel):
            channel._update(channel.guild, channel.parent, channel._raw)
        elif isinstance(channel, GroupDMChannel):
            channel._update(channel.owner, channel._raw)
        elif isinstance(channel, DMChannel):
            channel._update(channel._raw)

        return channel

    async def reload_role(self, role):
        """Reload a :class:`Role` object with new data from
        the role collection.

        Follows the same strategies as :meth:`GuildManager.reload_guild`
        """
        query = {'role_id': role.id}
        raw_role = await self.role_coll.find_one(query)
        if raw_role is None:
            log.info('[role:reload] rid=%d not found', role.id)
            try:
                role.guild.roles.remove(role)
            except ValueError:
                pass

            for channel in role.guild.channels:
                if role in channel.overwrites:
                    channel.overwrites.remove(role)

            try:
                self.roles.remove(channel)
            except ValueError:
                pass

            del role
            return

        role._raw.update(raw_role)
        role._update(role.guild, role._raw)
        return role

    async def reload_invite(self, invite):
        """Reload a :class:`Invite` object with
        new data from the invite collection.

        Follows the same strategies as :meth:`GuildManager.reload_guild`
        """
        query = {'invite_code': invite.code}
        raw_invite = await self.invite_coll.find_one(query)
        if raw_invite is None:
            log.info('[invite:reload] i_code=%s not found', invite.code)
            try:
                self.invites.remove(invite)
            except ValueError:
                pass

            try:
                invite.guild.invites.remove(invite)
            except ValueError:
                pass

            del invite
            return

        invite._raw.update(raw_invite)
        invite._update(invite.guild, invite._raw)
        return invite

    async def reload_message(self, message):
        """Reload a :class:`Message` object with
        new data from the message collection.

        Follows the same strategies as :meth:`GuildManager.reload_guild`
        """
        query = {'message_id': message.id}
        raw_message = await self.message_coll.find_one(query)
        if raw_message is None:
            log.info('[message:reload] mid=%s not found', message.id)
            try:
                self.messages.remove(message)
            except ValueError:
                pass

            del message
            return

        message._raw.update(raw_message)
        message._update(message.channel, message.author, message._raw)
        return message

    async def new_guild(self, owner, payload):
        """Create a Guild.

        Dispatches GUILD_CREATE event to the owner of the new guild.

        Parameters
        ----------
        owner: :class:`User`
            The owner of the guild to be created
        payload: dict
            guild payload::
                {
                "name": "Name of the guild",
                "region": "guild voice region, ignored",
                "verification_level": TODO,
                "default_message_notifications": TODO,
                "icon": "base64 128x128 jpeg image for the guild icon",
                }

        Returns
        -------
        :class:`Guild`
        """

        # For this to work:
        #  - Create a raw guild
        #  - Create two default channels
        #   - Named "General", one is text, other is voice
        #  - Create the default role, "@everyone"
        #  - Create raw member object for the owner

        guild_id = get_snowflake()
        raw_guild = {
            'guild_id': guild_id,
            'name': payload['name'],
            'owner_id': owner.id,
            'region': 'local',
            'features': [],
            'icon': payload['icon'],
            'channel_ids': [guild_id],
            'role_ids': [guild_id],
            'member_ids': [owner.id],
            'bans': [],
        }

        raw_default_channel = {
            'channel_id': guild_id,
            'guild_id': guild_id,
            'name': 'general',
            'type': ChannelType.GUILD_TEXT,
            'position': 0,
            'topic': '',
            'pinned_ids': [],
        }

        raw_default_role = {
            'role_id': guild_id,
            'guild_id': guild_id,
            'permissions': 104188929,
            'position': 0,
        }

        raw_member_owner = {
            'guild_id': guild_id,
            'user_id': owner.id,
            'nick': '',
            'joined': datetime.datetime.now().isoformat(),
            'deaf': False,
            'mute': False,
        }

        bg = BareGuild(guild_id)

        await self.member_coll.insert_one(raw_member_owner)
        self.raw_members[guild_id][owner.id] = raw_member_owner

        default_role = Role(self.server, bg, raw_default_role)
        await self.role_coll.insert_one(raw_default_role)
        self.roles.append(default_role)

        default_channel = TextGuildChannel(self.server, None,
                                           raw_default_channel, bg)
        await self.channel_coll.insert_one(raw_default_channel)
        self.channels.append(default_channel)

        guild = Guild(self.server, raw_guild)
        await self.guild_coll.insert_one(raw_guild)
        self.guilds.append(guild)

        log.info('[new_guild] Created guild %r', guild)

        guild.mark_watcher(owner.id)
        await self.server.presence.status_update(guild, owner)
        await guild.dispatch('GUILD_CREATE', guild.as_json)
        await owner.dispatch('USER_GUILD_SETTINGS_UPDATE',
                             guild.default_settings)

        return guild

    async def edit_guild(self, guild, guild_edit_payload):
        """Edit a guild.

        Dispatches GUILD_UPDATE events to relevant clients.

        Parameters
        ----------
        guild: :class:`Guild`
            Guild that is going to be updated with new data.
        guild_edit_payload: dict
            New guild data, has 9, all optional, fields. ``name, region,
             verification_level, default_message_notifications, afk_channel_id,
             afk_timeout, icon, owner_id, splash``.

        Returns
        -------
        The edited :class:`Guild`.
        """

        await self.guild_coll.update_one({'guild_id': str(guild.id)},
                                         {'$set': guild_edit_payload})

        guild = await self.reload_guild(guild)

        await guild.dispatch('GUILD_UPDATE', guild.as_json)
        return guild

    async def delete_guild(self, guild):
        """Delete a guild.

        Dispatches GUILD_DELETE to all guild members.

        Returns
        -------
        None
        """
        guild_id = guild.id
        res = await self.guild_coll.delete_many({'guild_id': guild_id})

        if res.deleted_count == 0:
            log.warning('[guild_delete] THINGS ARE WEIRD (deleted_doc == 0)')
            return

        if res.deleted_count > 1:
            log.warning('[guild_delete] THINGS ARE WRONG (deleted_doc > 1)')

        result = await self.member_coll.delete_many({'guild_id': guild_id})
        log.info(f'[guild_delete] Deleted {result.deleted_count} raw members')

        del self.raw_guilds[guild_id]

        await guild.dispatch('GUILD_DELETE', {
            'id': str(guild_id),
            'unavailable': False
        })

        return await self.reload_guild(guild)

    async def add_member(self, guild, user):
        """Adds a user to a guild.
        Doesn't add if the user is banned from the guild.

        Dispatches GUILD_MEMBER_ADD to relevant clients.

        Parameters
        ----------
        guild: :class:`Guild`
            The guild to add the user to.
        user: :class:`User`
            The user that is going to be added to the guild.

        Returns
        -------
        :class:`Member`
            The new member object.
        """

        raw_guild = guild._data

        if str(user.id) in guild.bans:
            raise Exception('User is banned')

        raw_guild['members'].append(str(user.id))

        result = await self.guild_coll.replace_one({'guild_id': guild.id},
                                                   raw_guild)
        log.info('Updated %d guilds', result.modified_count)

        raw_member = {
            'guild_id': guild.id,
            'user_id': user.id,
            'nick': None,
            'joined': datetime.datetime.now().isoformat(),
            'deaf': False,
            'mute': False,
        }
        result = await self.member_coll.insert_one(raw_member)
        self.raw_members[guild.id][user.id] = raw_member

        guild = await self.reload_guild(guild)

        new_member = guild.members.get(user.id)
        if new_member is None:
            raise Exception('New member as raw not found')

        to_add = {'guild_id': str(guild.id)}
        payload = {**new_member.as_json, **to_add}

        await guild.dispatch('GUILD_MEMBER_ADD', payload)
        await new_member.dispatch('GUILD_CREATE', guild.as_json)
        await user.dispatch('USER_GUILD_SETTINGS_UPDATE',
                            guild.default_settings)

        return new_member

    async def edit_member(self, member, new_data):
        """Edit a member.

        Dispatches GUILD_MEMBER_UPDATE to relevant clients.

        Parameters
        ----------
        member: :class:`Member`
            Member to edit data.
        new_data: dict
            Raw member data.
        """

        guild = member.guild
        user = member.user

        await self.member_coll.update_one({'guild_id': guild.id,
                                           'user_id': user.id},
                                          {'$set': new_data})

        raw_member = {**member._raw, **new_data}
        member._update(raw_member)

        # update in cache
        self.raw_members[guild.id][user.id] = raw_member

        await guild.dispatch('GUILD_MEMBER_UPDATE', {
            'guild_id': str(member.guild.id),
            'roles': member.iter_json(member.roles),
            'user': member.user.as_json,
            'nick': member.nick
        })

    async def remove_member(self, guild, user):
        """Remove a user from a guild.

        Dispatches GUILD_MEMBER_REMOVE to relevant clients.
        Dispatches GUILD_DELETE to the user being removed from the guild.

        Parameters
        ----------
        guild: :class:`Guild`
            Guild to remove the user from.
        user: :class:`User`
            User to remove from the guild.
        """
        raw_guild = guild._raw
        user_id = user.id
        try:
            raw_guild['member_ids'].remove(user_id)
        except ValueError:
            raise Exception('Member not found')

        await self.guild_coll.update_one({'guild_id': guild.id},
                                         {'$set': raw_guild})

        result = await self.member_coll.delete_many({'guild_id': guild.id,
                                                     'user_id': user.id})
        log.info(f'Deleted {result.deleted_count} member objects')

        del self.raw_members[guild.id][user.id]

        guild = await self.reload_guild(guild)
        await guild.dispatch('GUILD_MEMBER_REMOVE', {
            'guild_id': str(guild.id),
            'user': user.as_json,
        })

        await user.dispatch('GUILD_DELETE', {
            'id': str(guild.id),
            'unavailable': False,
        })

    async def _ban_clean(self, guild, user, delete_days):
        """Delete all messages made by a user.
        (use as a background `asyncio.Task`)."""
        for channel in guild.text_channels:
            days_ago = time.time() - (delete_days * 24 * 60 * 60)
            messages = await channel.from_timestamp(days_ago)
            message_ids = [message.id for message in messages if
                           message.author.id == user.id]
            await channel.delete_many(message_ids, bulk=True)

    async def ban_user(self, guild, user, delete_days=None):
        """Ban a user from a guild.

        Dispatches GUILD_BAN_ADD and GUILD_MEMBER_REMOVE to relevant clients.
        Dispatches MESSAGE_DELETE_BULK if `delete_days` is specified.

        Parameters
        ---------
        guild: :meth:`Guild`
            Guild that the user is going to be banned from.
        user: :meth:`User`
            User to be banned.
        delete_days: int or None:
            The amount of days worth of messages to be removed using
            :meth:`TextGuildChannel.delete_many`.
        """

        bans = guild.banned_ids

        try:
            bans.index(user.id)
            raise Exception("User already banned")
        except ValueError:
            bans.append(user.id)

        await self.guild_coll.update_one({'guild_id': guild.id},
                                         {'$set': {'bans': bans}})

        guild = await self.reload_guild(guild)

        await guild.dispatch('GUILD_BAN_ADD',
                             {**user.as_json, **{'guild_id': str(guild.id)}})

        try:
            guild.member_ids.index(user.id)
            await self.remove_member(guild, user)
        except ValueError:
            pass

        if delete_days is not None:
            self.loop.create_task(self._ban_clean(guild, user, delete_days))

    async def unban_user(self, guild, user):
        """Unban a user from a guild.

        Dispatches GUILD_BAN_REMOVE to relevant clients.
        """

        try:
            guild.banned_ids.remove(user.id)
        except ValueError:
            raise Exception('User not banned')

        await self.guild_coll.update_one({'guild_id': guild.id},
                                         {'$set': {'bans': guild.banned_ids}})

        guild = await self.reload_guild(guild)
        await guild.dispatch('GUILD_BAN_REMOVE',
                             {**user.as_json, **{'guild_id': str(guild.id)}})

    async def kick_member(self, member):
        """Kick a member from a guild.

        Dispatches GUILD_MEMBER_REMOVE to relevant clients.

        Parameters
        ----------
        member: :class:`Member`
            The member to kick.
        """

        guild = member.guild
        try:
            await self.remove_member(guild, member.user)
            return True
        except:
            log.error("Error kicking member.", exc_info=True)
            return False

    async def create_channel(self, guild, payload):
        """Create a channel in a guild.

        Dispatches CHANNEL_CREATE to relevant clients.

        Parameters
        ----------
        guild: :class:`Guild`
            The guild that is going to have a new channel
        payload: dict
            Channel create payload. It is a raw channel with
            some optional fields, see :meth:`GuildsEndpoint.h_create_channel`.

        Returns
        -------
        :class:`Channel`
            The newly created channel.
        """

        if payload['type'] not in (ChannelType.GUILD_TEXT,
                                   ChannelType.GUILD_VOICE,
                                   ChannelType.GUILD_CATEGORY):
            raise Exception('Invalid channel type')

        raw_channel = {**payload, **{
            'channel_id': get_snowflake(),
            'guild_id': guild.id,

            'position': len(guild.channels) + 1,

            # text channel specific
            'topic': '',
            'pinned_ids': [],
            'nsfw': False,

            # TODO: do the guild category thing
            'parent_id': None,
        }}

        result = await self.channel_coll.insert_one(raw_channel)

        # I'm proud of this stuff.
        guild._raw['channel_ids'].append(raw_channel['channel_id'])

        result = await self.guild_coll.update_one(
            {'guild_id': guild.id},
            {'$set': {'channel_ids':
                      guild._raw['channel_ids']}})

        log.info('Updated %d guilds', result.modified_count)

        ch_type = raw_channel['type']

        if ch_type == ChannelType.GUILD_TEXT:
            channel = TextGuildChannel(self.server, None, raw_channel, guild)

        elif ch_type == ChannelType.GUILD_VOICE:
            channel = VoiceGuildChannel(self.server, None, raw_channel, guild)

        elif ch_type == ChannelType.GUILD_CATEGORY:
            channel = GuildCategory(self.server, guild, raw_channel)

        self.channels.append(channel)

        guild = await self.reload_guild(guild)

        await guild.dispatch('CHANNEL_CREATE', channel.as_json)
        return channel

    async def edit_channel(self, channel, payload):
        """Edits a channel in a guild.

        Dispatches CHANNEL_UPDATE to relevant clients.

        Parameters
        ----------
        channel: :class:`Channel`
            The channel to be updated.
        payload: dict
            Raw channel with any combination of fields.

        Returns
        -------
        :class:`Channel`
            The updated channel
        """

        channel._raw.update(payload)

        await self.channel_coll.update_one({'channel_id': channel.id},
                                           {'$set': channel._raw})

        channel = await self.reload_channel(channel)
        await channel.guild.dispatch('CHANNEL_UPDATE', channel.as_json)
        return channel

    async def delete_channel(self, channel):
        """Deletes a channel from a guild.

        Dispatches CHANNEL_DELETE to relevant clients

        Returns
        -------
        None
        """
        guild = channel.guild
        guild._raw['channel_ids'].remove(channel.id)

        await self.guild_coll.update_one({'guild_id': channel.guild.id},
                                         {'$set': {'channel_ids':
                                                   guild._raw['channel_ids']}})

        await self.channel_coll.delete_many({'channel_id': channel.id})
        await self.reload_channel(channel)
        await guild.dispatch('CHANNEL_DELETE', channel.as_json)
        del channel

        return

    async def make_invite_code(self):
        """Generate an unique invite code.

        This uses `snowflake.get_invite_code` and checks if the
        invite code already exists in the database.
        """

        invi_code = get_invite_code()
        raw_invite = await self.invite_coll.find_one({'code': invi_code})

        while raw_invite is not None:
            invi_code = get_invite_code()
            raw_invite = await self.invite_coll.find_one({'code': invi_code})

        return invi_code

    async def create_invite(self, channel, inviter, invite_payload):
        """Create an invite to a channel.

        Parameters
        ----------
        channel: :class:`Channel`
            The channel to make the invite refer to.
        inviter: :class:`User`
            The user that made the invite.
        invite_payload: dict
            Invite payload.

        Returns
        -------
        :class:`Invite`
        """
        # TODO: something something permissions
        #  if not channel.guild.permissions(user, MAKE_INVITE):
        #   return None

        age = invite_payload['max_age']
        iso_timestamp = None
        if age > 0:
            now = datetime.datetime.now().timestamp()
            expiry_timestamp = datetime.datetime.fromtimestamp(now + age)
            iso_timestamp = expiry_timestamp.isoformat()

        uses = invite_payload.get('max_uses', -1)
        if uses == 0:
            uses = -1

        invite_code = await self.make_invite_code()
        raw_invite = {
            'code': invite_code,
            'channel_id': channel.id,
            'inviter_id': inviter.id,
            'timestamp': iso_timestamp,
            'uses': uses,
            'temporary': False,
            'unique': True,
        }

        await self.invite_coll.insert_one(raw_invite)

        invite = Invite(self.server, raw_invite)
        if invite.valid:
            self.invites.append(invite)

        return invite

    async def use_invite(self, user, invite):
        """Uses an invite.

        Adds a user to a guild.

        Parameters
        ----------
        user: :class:`User`
            The user that is going to use the invite.
        invite: :class:`Invite`
            Invite object to be used.

        Returns
        -------
        :class:`Member` or ``None``
        """

        if not invite.sane:
            log.warning(f'Insane invite {invite!r} to {invite.guild!r}')
            return False

        if not invite.use():
            return False

        await invite.update()

        guild = invite.channel.guild
        member = await self.add_member(guild, user)

        if member is None:
            return False

        return member

    async def delete_invite(self, invite):
        """Deletes an invite.

        Removes it from database and cache.
        """

        res = await self.invite_coll.delete_one({'code': invite.code})
        log.info(f'Removed {res.deleted_count} invites')

        await self.reload_invite(invite)

    async def create_role(self, guild, role_payload):
        """Create a role in a guild.

        Dispatches respective events.
        """

        role = Role(guild, role_payload)

        await guild.dispatch('GUILD_ROLE_CREATE', {
            'guild_id': str(guild.id),
            'role': role.as_json,
        })

    async def edit_role(self, role, new_role_data):
        pass

    async def delete_role(self, role):
        """Delete a role from a guild.

        Dispatches events to respective clients.

        Parameters
        ----------
        role: :class:`Role`
            The role to be deleted.
        """
        res = await self.role_coll.delete_one({'role_id': role.id})
        log.info('Deleted %d roles', res.deleted_count)

        await self.reload_role(role)
        await role.dispatch('ROLE_DELETE', {
            'role_id': str(role.id),
            'guild_id': str(role.guild_id),
        })

    async def add_role(self, member, role):
        """Add a role to a member.

        Dispatches events to respective clients.
        """
        pass

    async def remove_role(self, member, role):
        """Remove a role from a member.

        Dispatches events to respective clients.
        """
        pass

    async def guild_count(self, user) -> int:
        """Get the guild count for a user"""
        return await self.member_coll.count({'user_id': user.id})

    async def shard_count(self, user):
        """Give the shard count for a user.
        The value changes with the user joining/leaving guilds.

        This function allocates around 1200 guilds for each shard.

        Parameters
        ----------
        user: :class:`User`
            The user to get a shard count from.

        Returns
        -------
        int
            The recommended amount of shards to start the connection.
        """
        return max((await self.guild_count(user)) / 1200, 1)

    def get_shard(self, guild_id: int, shard_count: int) -> int:
        """Get a shard number for a guild ID."""
        # Discord uses a MAGIC of 22, but we aren't Discord.
        magic = 0
        return (guild_id << magic) % shard_count

    async def init_members(self):
        """Load raw member data from the member collection into
        the :attr:`GuildManager.raw_members`
        """

        cursor = self.member_coll.find()
        member_count = 0
        async for raw_m in cursor:
            raw_m.pop('_id')
            self.raw_members[raw_m['guild_id']][raw_m['user_id']] = raw_m
            member_count += 1

        log.info('[guild] loaded %d members', member_count)
        log.debug('raw_members: %r', self.raw_members)

    async def init_roles(self):
        """Load raw role data as role objects
        and fill :attr:`GuildManager` with it.
        """

        cursor = self.role_coll.find()
        role_count = 0
        async for raw_role in cursor:
            bg = BareGuild(raw_role['guild_id'])
            log.debug(f'[role:load] Loading role {raw_role["role_id"]}')
            role = Role(self.server, bg, raw_role)
            self.roles.append(role)
            role_count += 1

        log.info('[guild] loaded %d roles', role_count)

    async def init_channels(self):
        """Load channel data into :attr:`GuildManager.channels`"""

        cursor = self.channel_coll.find()
        chan_count = 0
        async for raw_channel in cursor:
            ch_type = raw_channel['type']
            channel = None

            log.debug('[chan:load] Loading channel %d',
                      raw_channel['channel_id'])

            bg = BareGuild(raw_channel['guild_id'])

            parent_id = raw_channel.get('parent_id')
            parent = self.get_channel(parent_id)

            if not parent:
                parent = BareCategory(parent_id)

            if ch_type == ChannelType.GUILD_TEXT:
                channel = TextGuildChannel(self.server, parent,
                                           raw_channel, bg)
            elif ch_type == ChannelType.GUILD_VOICE:
                channel = VoiceGuildChannel(self.server, parent,
                                            raw_channel, bg)

            elif ch_type == ChannelType.GUILD_CATEGORY:
                channel = GuildCategory(self.server, bg, raw_channel)
            else:
                raise RuntimeError(f'Invalid type for channel: {ch_type}')

            self.channels.append(channel)
            chan_count += 1

        log.info('[guild] loaded %d channels', chan_count)

    async def init_guilds(self):
        """Load guild data into :attr:`GuildManager.guilds`.

        This creates raw member objects if the member
        the guild is being loaded doesn't exist(in the raw member cache).
        """

        cursor = self.guild_coll.find()
        guild_count = 0
        async for raw_guild in cursor:
            guild_id = raw_guild['guild_id']

            log.debug(f'[guild:load] Loading guild {guild_id}')

            raw_guild_members = self.raw_members.get(int(guild_id), {})

            # This loads raw members into mongo if they don't exist
            for user_id in raw_guild['member_ids']:
                if user_id in raw_guild_members:
                    continue

                raw_member = {
                    'guild_id': guild_id,
                    'user_id': user_id,
                    'nick': None,
                    'joined': datetime.datetime.now().isoformat(),
                    'deaf': False,
                    'mute': False,
                }

                await self.member_coll.insert_one(raw_member)
                self.raw_members[guild_id][user_id] = raw_member
                log.debug('Inserting raw member gid=%r uid=%r',
                          guild_id, user_id)

            guild = Guild(self.server, raw_guild)
            if guild._needs_update:
                r = await self.guild_coll.update_one({'guild_id': guild.id},
                                                     {'$set': guild._raw})
                log.info('Updated %d from guild request', r.modified_count)

            self.guilds.append(guild)

            for channel in guild.channels:
                channel.guild = guild

            guild_count += 1

        log.info('[guild] Loaded %d guilds', guild_count)

    async def init_invites(self):
        """Load invite data into the :class:`GuildManager`."""

        cursor = self.invite_coll.find()
        invite_count, valid_invites = 0, 0

        for raw_invite in (await cursor.to_list(length=None)):
            log.debug(f'[invite:load] Loading invite {raw_invite["code"]}')
            invite = Invite(self.server, raw_invite)

            if invite.valid:
                self.invites.append(invite)
                valid_invites += 1
            else:
                await self.delete_invite(invite)

            invite_count += 1

        log.info('[guild] %d valid out of %d invites',
                 valid_invites, invite_count)

    async def init_messages(self):
        """Load message data into the :class:`GuildManager`."""

        cursor = self.message_coll.find().sort('message_id')
        message_count = 0

        async for raw_message in cursor:
            channel = self.get_channel(raw_message['channel_id'])
            if channel is None:
                log.info('mid=%d has no channel cid=%d found',
                         raw_message['message_id'], raw_message['channel_id'])

                # We delete all messages referencing the non-existant channel
                # to be faster than deleting all per ID
                r = await self.message_coll.delete_many(
                    {'channel_id': raw_message['channel_id']}
                )
                log.info('Deleted %d messages from channel not found',
                         r.deleted_count)
                continue

            author = channel.guild.members.get(raw_message['author_id'])

            m = Message(self.server, channel, author, raw_message)
            self.messages.append(m)
            message_count += 1

        log.info(f'[guild] Loaded %d messages', message_count)

    async def init(self):
        """Initialize the GuildManager.

        Loads, in order:
         - Members
         - Roles
         - Channels
         - Guilds
         - Invites
         - Messages
        """

        await self.init_members()
        await self.init_roles()
        await self.init_channels()
        await self.init_guilds()
        await self.init_invites()
        await self.init_messages()
