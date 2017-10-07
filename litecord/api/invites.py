import logging

from voluptuous import Schema, Required, All, Range, REMOVE_EXTRA

from ..utils import _err, _json
from ..decorators import auth_route

log = logging.getLogger(__name__)

class InvitesEndpoint:
    def __init__(self, server):
        self.server = server
        self.guild_man = server.guild_man

        self.invite_create_schema = Schema({
            Required('max_age', default=86400): All(int, Range(min=10, max=86400)),
            Required('max_uses', default=0): All(int, Range(min=0, max=50)),
            Required('temporary', default=False): bool,
            Required('unique', default=True): bool,
        }, extra=REMOVE_EXTRA)

        self.register(server.app)

    def register(self, app):
        self.server.add_get('invites/{invite_code}', self.h_get_invite)
        self.server.add_post('invites/{invite_code}', self.h_accept_invite)
        self.server.add_delete('invites/{invite_code}', self.h_delete_invite)

        self.server.add_get('invite/{invite_code}', self.h_get_invite)
        self.server.add_post('invite/{invite_code}', self.h_accept_invite)
        self.server.add_delete('invite/{invite_code}', self.h_delete_invite)

        app.router.add_get('/i/{invite_code}', self.h_get_invite)

        self.server.add_post('channels/{channel_id}/invites', self.h_create_invite)

    async def h_get_invite(self, request):
        """`GET /invites/{invite_code}`."""

        invite_code = request.match_info['invite_code']
        invite = self.server.guild_man.get_invite(invite_code)

        if invite is None:
            return _err(errno=10006)

        if request.query.get('with_counts', False):
            invite_json = invite.as_json
            guild = invite.channel.guild

            invite_json['guild'].update({
                'text_channel_count': len(guild.channels),
                'voice_channel_count': 0,
            })

            invite_json.update({
                'approximate_presence_count': await self.server.presence.presence_count(guild.id),
                'approximate_member_count': len(guild.members),
            })

            return _json(invite_json)

        return _json(invite.as_json)

    @auth_route
    async def h_accept_invite(self, request, user):
        """`POST /invites/{invite_code}`.

        Accept an invite. Returns invite object.
        """

        invite_code = request.match_info['invite_code']

        invite = self.server.guild_man.get_invite(invite_code)
        if invite is None:
            return _err(errno=10006)

        if not invite.valid:
            return _err('Invalid invite')

        try:
            member = await self.guild_man.use_invite(user, invite)
            if member is None:
                return _err('Error adding to the guild')

            return _json(invite.as_json)
        except Exception as err:
            log.exception('Error while using invite')
            return _err(f'Error using the invite: {err!r}')

    @auth_route
    async def h_create_invite(self, request, user):
        """`POST /channels/{channel_id}/invites`.

        Creates an invite to a channel.
        Returns invite object.
        """

        channel_id = request.match_info['channel_id']
        channel = self.guild_man.get_channel(channel_id)
        if channel is None:
            return _err(errno=10003)

        try:
            payload = await request.json()
        except:
            return _err('error parsing JSON')

        try:
            payload['max_age'] = int(payload['max_age'])
        except (ValueError, TypeError):
            return _err('invalid max_age type')

        invite_payload = self.invite_create_schema(payload)

        invite = await self.guild_man.create_invite(channel,
                                                    user, invite_payload)
        if invite is None:
            return _err('error making invite')

        return _json(invite.as_json)

    @auth_route
    async def h_delete_invite(self, request, user):
        """`DELETE /invites/{invite_code}`.

        Delete an invite.
        """

        invite_code = request.match_info['invite_code']

        invite = self.server.guild_man.get_invite(invite_code)
        if invite is None:
            return _err(errno=10006)

        guild = invite.channel.guild

        if guild.owner.id != user.id:
            return _err(errno=40001)

        try:
            await self.guild_man.delete_invite(invite)
            return _json(invite.as_json)
        except:
            log.error(exc_info=True)
            return _err('Error deleting invite.')
