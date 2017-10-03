import datetime
import logging

from .base import LitecordObject

log = logging.getLogger(__name__)


class Invite(LitecordObject):
    """An invite object.

    Parameters
    ----------
    server: :class:`LitecordServer`
        Server instance.
    _raw: dict
        Raw invite data.

    Attributes
    ----------
    _raw: dict
        Raw invite object.
    code: str
        Invite code.
    channel_id: int
        Channel's ID being reffered in this invite.
    channel: :class:`Channel`
        Channel being reffered in ``channel_id``. Can be :py:const:`None`.
    inviter_id: int
        User's ID who made the invite.
    inviter: :class:`User`
        User who made the invite. Can be :py:const:`None`.
    temporary: bool
        Flag if this invite is temprary or not.
    uses: int
        Uses this invite has. If the invite is infinite, this becomes ``-1``.
    iso_timestamp: str
        A ISO 8601 formatted string.
    infinite: bool
        Flag if this invite is infinite or not.
    expiry_timestamp: `datetime.datetime`
        If the invite is not infinite, this is the date when the invite will
        expire and be invalid.
        If not, this becomes :py:const:`None`.
    """

    __slots__ = ('_raw', 'code', 'channel_id', 'channel', 'guild', 'inviter_id', 'inviter'
        'temporary', 'uses', 'iso_timestamp', 'infinite', 'expiry_timestamp')

    def __init__(self, server, raw):
        super().__init__(server)
        self._raw = raw

        self.code = self._raw['code']
        self.channel_id = int(self._raw['channel_id'])
        
        self._update(self._raw)

    def _update_detached(self, raw):
        self.temporary = raw.get('temporary', False)

        self.uses = raw.get('uses', -1)

        self.iso_timestamp = raw.get('timestamp', None)
        self.infinite = True
        self.expiry_timestamp = None

        if self.iso_timestamp is not None:
            self.infinite = False
            self.expiry_timestamp = datetime.datetime.strptime(self.iso_timestamp, \
                "%Y-%m-%dT%H:%M:%S.%f")

    def _update(self, raw):
        self.channel = self.server.guild_man.get_channel(self.channel_id)
        if self.channel is None:
            log.warning('Orphan invite (channel)')
            self._update_detached(raw)
            return

        self.guild = self.channel.guild

        self.inviter_id = int(raw['inviter_id'])
        self.inviter = self.guild.members.get(self.inviter_id)
        if self.inviter is None:
            log.warning('Orphan invite (inviter)')

        self._update_detached(raw)

    @property
    def valid(self):
        """Returns a boolean representing the validity of the invite"""
        if self.channel is None:
            return False

        if not self.infinite:
            now = datetime.datetime.now()

            if now.timestamp() > self.expiry_timestamp.timestamp():
                return False

        # check uses
        if self.uses == -1:
            return True

        if self.uses < 1:
            return False

        return True

    def use(self):
        """Returns a boolean on success/failure of using an invite"""
        if self.channel is None:
            return False

        if not self.infinite:
            now = datetime.datetime.now()

            if now.timestamp() > self.expiry_timestamp.timestamp():
                return False

        # check uses
        if self.uses == -1:
            return True

        if self.uses < 1:
            return False

        self.uses -= 1
        return True

    async def update(self):
        """Update an invite in the database."""
        res = await self.server.invite_coll.replace_one(
            {'code': self.code}, self.as_db)
        log.info(f"Updated {res.modified_count} invites")

    @property
    def sane(self):
        """Checks if an invite is sane."""
        return self.channel is not None

    @property
    def as_db(self):
        return {
            'code': self.code,
            'channel_id': str(self.channel_id),
            'timestamp': self.iso_timestamp,
            'uses': self.uses,
            'temporary': self.temporary,
            'unique': True,
        }

    @property
    def as_json(self):
        return {
            'code': self.code,
            'guild': self.channel.guild.as_invite,
            'channel': self.channel.as_invite,
            'inviter': self.inviter.as_invite,
        }


