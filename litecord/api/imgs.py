import logging
import base64

from aiohttp import web
from ..utils import _err, _json

log = logging.getLogger(__name__)


class ImageEndpoint:
    def __init__(self, server):
        self.server = server
        self.images = server.images

        self.register(server.app)

    def register(self, app):
        _r = app.router
        _r.add_get('/images/avatars/{user_id}/{avatar_hash}.{img_format}', self.h_get_user_avatar)
        #_r.add_get('/embed/avatars/{default_id}.{img_format}', self.h_get_default_avatar)
        _r.add_get('/images/{image_hash}/{filename}.{extension}', self.h_get_image)

    async def h_get_user_avatar(self, request):
        """`GET /images/avatars/{user_id}/{avatar_hash}.{img_format}`.

        Retrieve a user's avatar.
        """

        user_id = request.match_info['user_id']
        avatar_hash = request.match_info['avatar_hash']

        # TODO: convert image to img_format
        # img_format = request.match_info['img_format']

        user = self.server.get_user(user_id)
        if user is None:
            return _err(errno=10012)

        image = await self.images.avatar_retrieve(avatar_hash)
        if image is None:
            return _err('image not found')

        return web.Response(body=image)

    async def h_get_image(self, request):
        """`GET /images/{image_hash}/{name}.{ext}`.
        Fetch an image from the server.
        """
        image_hash = request.match_info['image_hash']
        i_name = request.match_info['name']
        i_ext = request.match_info['ext']
        i_fname = f'{i_name}.{i_ext}'

        log.info('[get_image] requesting filename %s hash %s',
                 i_fname, image_hash)
        image = await self.images.raw_image_get(i_fname, image_hash)
        if not image:
            return _err('image not found', status_code=404)

        log.info('image: %r %r', image, type(image['data']))
        log.info('decode: %r', base64.b64decode(image['data']))
        return web.Response(body=image['data'])
