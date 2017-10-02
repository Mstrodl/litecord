import logging
import hashlib
import io

import motor.motor_asyncio as motor
from PIL import Image

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
        # I hate myself for this
        mimetype = metadata['filename'].split('.')[-1]
        mimetype = f'image/{mimetype}'

        if img_type == 'avatar' and mimetype not in AVATAR_MIMETYPES:
            raise ImageError(f'Invalid mimetype {mimetype!r}')

        img_hash = hashlib.sha256(image_data).hexdigest()
        log.info('got %d bytes to insert, hash:%s',
                 len(image_data), img_hash)

        try:
            pil_image = Image.open(io.BytesIO(image_data))
            size = pil_image.size
            log.info('got image size: (%d, %d)', *size)
        except Exception:
            # oh uh u died
            log.exception('failed to process image, guess i\'ll just die (type: %s, metadata: %s):', img_type, metadata)
            return None, None

        image_metadata = {**{
            'hash': img_hash,
            'type': img_type,
            'dimensions': size,
            'mimetype': mimetype[0],
        }, **metadata}

        await self.fs.upload_from_stream(
            filename=image_metadata['filename'],
            source=io.BytesIO(image_data),
            metadata=image_metadata
        )

        return img_hash, image_metadata

    async def raw_image_get(self, image_filename, image_hash):
        log.debug('[image:raw_get] %s', image_hash)

        cur = self.fs.find({'filename': image_filename})
        async for filedata in cur:
            if filedata.metadata['hash'] != image_hash:
                continue

            log.info('[get_image] %s -> True', image_hash)
            image_data = await filedata.read()

            imageblock = {**{
                'data': image_data
            }, **filedata.metadata}

            # TODO: remove hardcoding
            imageblock.update({
                'url': f'https://litecord.adryd.com/images/{image_hash}/{filedata.filename}'
            })

            return imageblock

        log.info('[get_image] %s -> False', image_hash)
        return

    async def image_retrieve(self, img_hash):
        img = await self.raw_image_get(img_hashØ)
        try:
            return img.get('data')
        except:
            return None
