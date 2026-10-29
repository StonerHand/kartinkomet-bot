import unittest
from io import BytesIO

from PIL import Image

from bot.media.collage import BODY_HEIGHT, CELL_WIDTH, GAP, INSET, PAD, STRIP, build


def jpeg(size: tuple[int, int], color=(10, 120, 200)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "JPEG")
    return buffer.getvalue()


def width() -> int:
    return 2 * PAD + 2 * CELL_WIDTH + GAP


class CollageTest(unittest.TestCase):
    def test_cards_are_one_size_whatever_the_pics(self) -> None:
        low, high = BODY_HEIGHT[2]
        wide = Image.open(BytesIO(build([jpeg((1280, 640)), jpeg((1280, 720))])))
        self.assertEqual(wide.size, (width(), 2 * PAD + STRIP + low))  # short pics: the minimum card
        tall = Image.open(BytesIO(build([jpeg((500, 2000)), jpeg((100, 100))])))
        self.assertEqual(tall.height, 2 * PAD + STRIP + high)  # tall pics shrink to the maximum
        grid = Image.open(BytesIO(build([jpeg((640, 640))] * 4)))
        body = BODY_HEIGHT[4][1]
        self.assertEqual(grid.size, (width(), 2 * PAD + 2 * (STRIP + body) + GAP))

    def test_labels_sit_on_strips_above_the_pics_not_on_them(self) -> None:
        image = Image.open(BytesIO(build([jpeg((640, 640), (0, 0, 0))] * 2))).convert("RGB")
        strip = PAD + STRIP // 2
        red = image.getpixel((PAD + 40, strip))
        blue = image.getpixel((PAD + CELL_WIDTH + GAP + 40, strip))
        self.assertGreater(red[0], 180)
        self.assertGreater(blue[2], 180)
        # The whole pic shows: its top left corner, where the old badge sat, is the pic's own black.
        corner = image.getpixel((PAD + (CELL_WIDTH - (BODY_HEIGHT[2][0] - 2 * INSET)) // 2 + 4, PAD + STRIP + INSET + 4))
        self.assertLess(max(corner), 40)

    def test_evolved_pics_get_a_frame(self) -> None:
        image = Image.open(BytesIO(build([jpeg((640, 640), (0, 0, 0))] * 2, stages=[3, 0]))).convert("RGB")
        middle = PAD + STRIP + 100
        dragon = image.getpixel((PAD + 2, middle))  # the left edge of the left card: gold frame
        plain = image.getpixel((PAD + CELL_WIDTH + GAP + 2, middle))
        self.assertGreater(dragon[0], 200)
        self.assertLess(plain[0], 60)

    def test_rejects_wrong_count_and_garbage(self) -> None:
        with self.assertRaises(ValueError):
            build([jpeg((10, 10))] * 3)
        with self.assertRaises(Exception):
            build([b"garbage", jpeg((10, 10))])


if __name__ == "__main__":
    unittest.main()
