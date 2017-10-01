import logging
import base64
import hashlib

from ..err import ImageError

log = logging.getLogger(__name__)

AVATAR_MIMETYPES = [
    'image/jpeg', 'image/jpg', 'image/png',
    'image/gif', 'image/txt',
]


def extract_uri(data):
    """Extract image data."""
    try:
        sp = data.split(',')
        data_string = sp[0]
        encoded_data = sp[1]
        mimetype = data_string.split(';')[0].split(':')[1]
    except:
        raise ImageError('error decoding image data')

    return encoded_data, mimetype


class Images:
    """Images - image manager.

    `Images` manages profile pictures and message attachments.
    """
    def __init__(self, server):
        self.server = server

        self.image_db = server.litecord_db['images']
        self.attach_db = server.litecord_db['attachments']

        self.cache = {}

    async def _load(self):
        self.cache = {}

    async def _unload(self):
        del self.cache

    async def raw_add_image(self, data, img_type='avatar', metadata={}):
        """Add an image.

        Returns a string, representing the image hash.
        The image hash can be used in `Images.image_retrieve` to get
        raw binary data.
        """

        try:
            encoded_data, mimetype = extract_uri(data)
        except ImageError as err:
            raise err

        try:
            AVATAR_MIMETYPES.index(mimetype)
        except:
            raise ImageError(f'Invalid MIME type {mimetype!r}')

        try:
            dec_data = base64.b64decode(encoded_data)
        except:
            log.exception('error decoding base64')
            raise ImageError('Error decoding Base64 data')

        data_hash = hashlib.sha256(dec_data).hexdigest()
        log.info(f'Inserting {len(dec_data)}-bytes image.')

        image = {
            'type': img_type,
            'hash': data_hash,
            'data': encoded_data.decode(),
            'metadata': metadata,
        }

        await self.image_db.insert_one(image)
        self.cache[data_hash] = image

        return data_hash

    async def avatar_register(self, avatar_data):
        """Registers an avatar in the avatar database."""
        return (await self.raw_add_image(avatar_data))

    async def add_attachment(self, data):
        return (await self.raw_add_image(data, 'attachment'))

    async def avatar_retrieve(self, avatar_hash):
        img = await self.image_db.find_one({'type': 'avatar',
                                            'hash': avatar_hash})
        try:
            return img.get('data')
        except:
            return None

    async def raw_image_get(self, img_hash):
        img = await self.image_db.find_one({'type': 'attachment',
                                            'hash': img_hash})
        if not img:
            return

        # TODO: remove hardcoding
        meta = img['metadata']
        meta['url'] = f'https://litecord.adryd.com/images/{img_hash}/{meta["filename"]}'
        return img

    def force_get_cache(self, img_hash):
        img = self.cache.get(img_hash)
        if not img:
            return

        # TODO: remove hardcoding
        meta = img['metadata']
        meta['url'] = f'https://litecord.adryd.com/images/{img_hash}/{meta["filename"]}'
        return img

    async def image_retrieve(self, img_hash):
        img = await self.raw_image_get(img_hash)
        try:
            return img.get('data')
        except:
            return None
