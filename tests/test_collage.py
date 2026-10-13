import unittest
from io import BytesIO

from PIL import Image

from bot.collage import BADGE_MARGIN, BADGE_SIZE, CELL_WIDTH, GAP, MAX_CELL_HEIGHT, build


def jpeg(size: tuple[int, int], color=(10, 120, 200)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "JPEG")
    return buffer.getvalue()


class CollageTest(unittest.TestCase):
    def test_rows_are_as_tall_as_their_tallest_pic(self) -> None:
        duel = Image.open(BytesIO(build([jpeg((1280, 640)), jpeg((1280, 720))])))
        self.assertEqual(duel.size, (2 * CELL_WIDTH + GAP, 360))
        tall = Image.open(BytesIO(build([jpeg((500, 2000)), jpeg((100, 100))])))
        self.assertEqual(tall.height, MAX_CELL_HEIGHT)
        grid = Image.open(BytesIO(build([jpeg((640, 640))] * 4)))
        self.assertEqual(grid.size, (2 * CELL_WIDTH + GAP, 2 * 640 + GAP))

    def test_badges_sit_on_the_pic_in_slot_colours(self) -> None:
        image = Image.open(BytesIO(build([jpeg((640, 640), (0, 0, 0))] * 2)))
        # Inside the circle, left of the letter.
        y = BADGE_MARGIN + BADGE_SIZE // 2
        red = image.getpixel((BADGE_MARGIN + 8, y))
        blue = image.getpixel((CELL_WIDTH + GAP + BADGE_MARGIN + 8, y))
        self.assertGreater(red[0], 180)
        self.assertGreater(blue[2], 180)

    def test_evolved_pics_get_a_frame(self) -> None:
        image = Image.open(BytesIO(build([jpeg((640, 640), (0, 0, 0))] * 2, stages=[3, 0]))).convert("RGB")
        dragon = image.getpixel((CELL_WIDTH // 2, 2))  # top edge of the left pic: gold frame
        plain = image.getpixel((CELL_WIDTH + GAP + CELL_WIDTH // 2, 2))
        self.assertGreater(dragon[0], 200)
        self.assertLess(plain[0], 40)

    def test_rejects_wrong_count_and_garbage(self) -> None:
        with self.assertRaises(ValueError):
            build([jpeg((10, 10))] * 3)
        with self.assertRaises(Exception):
            build([b"garbage", jpeg((10, 10))])


if __name__ == "__main__":
    unittest.main()
