import logging
import base64
import hashlib

import motor.motor_asyncio as motor

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
        mimetype = (mimetype, mimetype.split('/')[1])
    except:
        raise ImageError('error decoding image data')

    return encoded_data, mimetype


class Images:
    """Images - image manager.

    `Images` manages profile pictures and message attachments.
    """
    def __init__(self, server):
        self.server = server
        self.fs = motor.AsyncIOMotorGridFSBucket(
            self.server.litecord_db)

    async def _load(self):
        self.cache = {}

    async def _unload(self):
        del self.cache

    async def raw_add_image(self, image_data, img_type='avatar', metadata={}):
        try:
            encoded_str, mimetype = extract_uri(image_data)
        except ImageError as err:
            raise err

        if img_type == 'avatar' and mimetype[0] not in AVATAR_MIMETYPES:
            raise ImageError(f'Invalid mimetype {mimetype!r}')

        # check for base64 validity of data
        try:
            raw_bytes = base64.b64decode(encoded_str)
        except:
            raise ImageError('Error decoding base64 data')

        img_hash = hashlib.sha256(raw_bytes).hexdigest()
        log.info('got %d bytes to insert, hash:%s',
                 len(raw_bytes), img_hash)

        image_metadata = {**{
            # img_hash is a str
            'hash': img_hash,

            # img_type is also a str
            'type': img_type,

            'mimetype': mimetype[0],
            'extension': mimetype[1],

        }, **metadata}

        await self.fs.upload_from_stream(
            filename=image_metadata['filename'],
            source=raw_bytes,
            metadata=image_metadata
        )

        return img_hash

    async def raw_image_get(self, image_hash):
        cur = self.fs.find({'hash': image_hash}, limit=1)
        async for filedata in cur:
            image_data = await filedata.read()

            imageblock = {**{
                'data': image_data
            }, **filedata.metadata}

            # TODO: remove hardcoding
            imageblock.update({
                'url': f'https://litecord.adryd.com/images/{image_hash}/{filedata.filename}'
            })

            return imageblock
        return

    async def image_retrieve(self, img_hash):
        img = await self.raw_image_get(img_hash)
        try:
            return img.get('data')
        except:
            return None
