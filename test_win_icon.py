import struct
import unittest

import win_icon


class IconTransparencyTests(unittest.TestCase):
    def test_blank_icon_marks_every_pixel_transparent_in_and_mask(self):
        size = 16
        rgba = win_icon.render_rgba('blank', size, (255, 70, 50))
        ico = win_icon.build_ico([(size, rgba)])
        image_offset = struct.unpack_from('<I', ico, 18)[0]
        mask_offset = image_offset + 40 + size * size * 4
        mask = ico[mask_offset:]
        self.assertEqual(len(mask), 4 * size)
        for row in range(size):
            self.assertEqual(mask[row * 4:row * 4 + 2], b'\xff\xff')
            self.assertEqual(mask[row * 4 + 2:row * 4 + 4], b'\x00\x00')


if __name__ == '__main__':
    unittest.main()
