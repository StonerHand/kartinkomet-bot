import unittest
from io import BytesIO

from PIL import Image

from bot.collage import CELL, GAP, build


def jpeg(size: tuple[int, int], color=(10, 120, 200)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "JPEG")
    return buffer.getvalue()


class CollageTest(unittest.TestCase):
    def test_duel_strip_and_tournament_grid(self) -> None:
        duel = Image.open(BytesIO(build([jpeg((1280, 720)), jpeg((500, 1280))])))
        self.assertEqual(duel.size, (2 * CELL + GAP, CELL))
        grid = Image.open(BytesIO(build([jpeg((100, 100))] * 4)))
        self.assertEqual(grid.size, (2 * CELL + GAP, 2 * CELL + GAP))

    def test_badges_are_drawn_in_slot_colours(self) -> None:
        image = Image.open(BytesIO(build([jpeg((640, 640), (0, 0, 0))] * 2)))
        red = image.getpixel((40, 78))
        blue = image.getpixel((CELL + GAP + 40, 78))
        self.assertGreater(red[0], 180)
        self.assertGreater(blue[2], 180)

    def test_rejects_wrong_count_and_garbage(self) -> None:
        with self.assertRaises(ValueError):
            build([jpeg((10, 10))] * 3)
        with self.assertRaises(Exception):
            build([b"garbage", jpeg((10, 10))])


if __name__ == "__main__":
    unittest.main()
