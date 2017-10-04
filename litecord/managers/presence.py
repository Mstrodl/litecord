import collections
import logging
import time

from ..objects import Presence
from ..err import InconsistencyError

log = logging.getLogger(__name__)


class PresenceManager:
    """Manage presence objects/updates.
    """
    def __init__(self, server):
        self.server = server
        self.presence_coll = server.presence_coll

        self.presences = collections.defaultdict(dict)
        self.global_presences = {}

    def get_presence(self, guild_id: int, user_id: int) -> 'Presence':
        """Get a `Presence` object from a guild + user ID pair."""
        guild_id = int(guild_id)
        user_id = int(user_id)

        try:
            return self.presences[guild_id][user_id]
        except KeyError:
            log.warning(f"Presence not found for {user_id}")
            return None

    def get_glpresence(self, user_id: int):
        return self.global_presences.get(user_id)

    def offline(self, status='offline'):
        """Return a default status object for users"""
        return {
            'status': status,
            'type': 0,
            'name': None,
            'url': None,
        }

    async def presence_count(self, guild_id: int):
        """Count the approximate amount of presence objects for a guild.

        Parameters
        ----------
        guild_id: int
            ID of the guild to search.

        Returns
        -------
        int:
            Approximate amount of presence objects in a guild.
        """

        guild_id = int(guild_id)
        guild_presences = self.presences.get(guild_id, {})
        return len(guild_presences.keys())

    async def count_all(self) -> int:
        """Return a count for all available presence objects."""
        return sum([await self.presence_count(guild_id) for guild_id in
                    self.server.guild_man.guilds.keys()])

    async def status_update(self, guild, user, new_status=None):
        """Update a user's status in a guild.

        Dispatches PRESENCE_UPDATE events to relevant clients in the guild.

        Parameters
        ----------
        guild: :class:`Guild`
            The guild that we want to update our presence on.
        user: :class:`User`
            The user we want to update presence from.
        new_status: dict, optional
            New raw presence data.

        Returns
        -------
        ``None``

        """

        if new_status is None:
            new_status = {}

        if isinstance(new_status, Presence):
            new_status = new_status.game

        if new_status.get('status') == 'invisible':
            new_status['status'] = 'offline'
        elif new_status.get('status') == 'afk':
            new_status['status'] = 'idle'

        user_id = user.id
        guild_id = guild.id

        guild_presences = self.presences[guild_id]

        if user_id not in guild_presences:
            guild_presences[user_id] = Presence(guild, user, new_status)

        user_presence = guild_presences[user_id]

        s1 = set(user_presence.game.values())
        s2 = set(new_status.values())
        differences = s1 ^ s2
        log.debug(f"presence for {user!r} has {len(differences)} diffs")

        if len(differences) > 0:
            user_presence.game.update(new_status)
            log.info(f'[presence] {guild!r} -> {user_presence!r}, updating')

            # We use _dispatch instead of dispatch here
            # because when using disptch, it creates a task
            # for _dispatch, and that happens very quickly.
            # and the guild watch state is updated before properly
            # executing the task, making this event be sent
            # before READY
            await guild._dispatch('PRESENCE_UPDATE', user_presence.as_json)

    async def create_presence(self, guild, user):
        """Create a new presence for a user joining a new guild."""
        status = {}

        guilds = sum(1 for g in user.guilds)
        if guilds > 0:
            # To create our presence,
            # we get the 1st guild a user is in
            # NOTE: this might 'break' if the user
            # is a bot AND it is sharded.

            guild_pcopy = next(user.guilds)
            presence = self.get_presence(guild_pcopy.id, user.id)
            if not presence:
                raise InconsistencyError('A guild the user is in '
                                         'does not have a presence')
            status = presence.game
        else:
            # handle the case where its a new user to litecord
            # and the user doesnt have any fucking guilds
            status = self.global_presences[user.id].game

        await self.status_update(guild, user, status)

    async def global_update(self, conn, new_status=None):
        """Updates a user's status, globally.

        Dispatches PRESENCE_UPDATE to all guilds the user is in.

        Parameters
        ----------
        conn: :class:`Connection`
            Connection to have its presence updated
        new_status: dict, optional
            Raw presence object.
        """

        user = conn.state.user
        self.global_presences[user.id] = Presence(None, user, new_status)

        for gid in conn.state.guild_ids:
            guild = self.server.guild_man.get_guild(gid)
            await self.status_update(guild, user, new_status)

    async def typing_start(self, user_id, channel_id):
        """Dispatches a TYPING_START to relevant clients in the channel.

        Parameters
        ----------
        user_id: str
            User's snowflake ID.
        channel_id: str
            Channel's snowflake ID.
        """
        typing_timestamp = int(time.time())
        channel = self.server.guild_man.get_channel(channel_id)

        await channel.dispatch('TYPING_START', {
            'channel_id': channel_id,
            'user_id': user_id,
            'timestamp': typing_timestamp,
        })
