/// 9x9 pixel glyphs drawn as square cells (Dena.emu's icon style): no curves,
/// one-cell strokes. '#' is ink, '.' is empty.
library;

import 'package:flutter/widgets.dart';

enum PixelGlyph {
  play,
  gear,
  folder,
  search,
  refresh,
  trash,
  download,
  check,
  cross,
  arrowRight,
  arrowLeft,
  gamepad,
  monitor,
  star,
  bolt,
  chip,
  plus,
  up,
  down,
  info,
}

const Map<PixelGlyph, List<String>> _bitmaps = {
  PixelGlyph.play: [
    '.##......',
    '.####....',
    '.######..',
    '.########',
    '.########',
    '.########',
    '.######..',
    '.####....',
    '.##......',
  ],
  PixelGlyph.gear: [
    '....#....',
    '.##.#.##.',
    '.#######.',
    '..##.##..',
    '####.####',
    '..##.##..',
    '.#######.',
    '.##.#.##.',
    '....#....',
  ],
  PixelGlyph.folder: [
    '.........',
    '####.....',
    '#..######',
    '#........',
    '#........',
    '#........',
    '#........',
    '#########',
    '.........',
  ],
  PixelGlyph.search: [
    '..####...',
    '.#....#..',
    '#......#.',
    '#......#.',
    '#......#.',
    '.#....#..',
    '..####.#.',
    '......###',
    '.......##',
  ],
  PixelGlyph.refresh: [
    '..#####..',
    '.#....##.',
    '#.....###',
    '#......#.',
    '#........',
    '#......#.',
    '###.....#',
    '.##....#.',
    '..#####..',
  ],
  PixelGlyph.trash: [
    '..#####..',
    '#########',
    '.#.....#.',
    '.#.#.#.#.',
    '.#.#.#.#.',
    '.#.#.#.#.',
    '.#.#.#.#.',
    '.#.....#.',
    '.#######.',
  ],
  PixelGlyph.download: [
    '....#....',
    '....#....',
    '....#....',
    '..#.#.#..',
    '...###...',
    '....#....',
    '.........',
    '#########',
    '#########',
  ],
  PixelGlyph.check: [
    '.........',
    '.......##',
    '......##.',
    '.....##..',
    '#...##...',
    '##.##....',
    '.###.....',
    '..#......',
    '.........',
  ],
  PixelGlyph.cross: [
    '.........',
    '##.....##',
    '.##...##.',
    '..##.##..',
    '...###...',
    '..##.##..',
    '.##...##.',
    '##.....##',
    '.........',
  ],
  PixelGlyph.arrowRight: [
    '.........',
    '.....#...',
    '.....##..',
    '#########',
    '#########',
    '#########',
    '.....##..',
    '.....#...',
    '.........',
  ],
  PixelGlyph.arrowLeft: [
    '.........',
    '...#.....',
    '..##.....',
    '#########',
    '#########',
    '#########',
    '..##.....',
    '...#.....',
    '.........',
  ],
  PixelGlyph.gamepad: [
    '.........',
    '.#######.',
    '#########',
    '##.####.#',
    '#.#####.#',
    '##.###.##',
    '#########',
    '##.....##',
    '.#.....#.',
  ],
  PixelGlyph.monitor: [
    '#########',
    '#.......#',
    '#.......#',
    '#.......#',
    '#.......#',
    '#########',
    '...###...',
    '...###...',
    '.#######.',
  ],
  PixelGlyph.star: [
    '....#....',
    '....#....',
    '...###...',
    '#########',
    '.#######.',
    '..#####..',
    '..##.##..',
    '.##...##.',
    '.#.....#.',
  ],
  PixelGlyph.bolt: [
    '.....###.',
    '....###..',
    '...###...',
    '..######.',
    '....###..',
    '...###...',
    '..##.....',
    '.#.......',
    '.........',
  ],
  PixelGlyph.chip: [
    '..#.#.#..',
    '.#######.',
    '##.....##',
    '.#.###.#.',
    '##.###.##',
    '.#.###.#.',
    '##.....##',
    '.#######.',
    '..#.#.#..',
  ],
  PixelGlyph.plus: [
    '....#....',
    '....#....',
    '....#....',
    '....#....',
    '#########',
    '....#....',
    '....#....',
    '....#....',
    '....#....',
  ],
  PixelGlyph.up: [
    '....#....',
    '...###...',
    '..#####..',
    '.#######.',
    '....#....',
    '....#....',
    '....#....',
    '....#....',
    '.........',
  ],
  PixelGlyph.down: [
    '.........',
    '....#....',
    '....#....',
    '....#....',
    '....#....',
    '.#######.',
    '..#####..',
    '...###...',
    '....#....',
  ],
  PixelGlyph.info: [
    '..#####..',
    '.#######.',
    '####.####',
    '#########',
    '####.####',
    '####.####',
    '####.####',
    '.#######.',
    '..#####..',
  ],
};

class PixelIcon extends StatelessWidget {
  const PixelIcon(this.glyph, {super.key, required this.color, this.size = 18});

  final PixelGlyph glyph;
  final Color color;

  /// Rendered size; multiples of 9 keep every cell on whole pixels.
  final double size;

  @override
  Widget build(BuildContext context) => SizedBox.square(
    dimension: size,
    child: CustomPaint(painter: _PixelPainter(glyph, color)),
  );
}

class _PixelPainter extends CustomPainter {
  _PixelPainter(this.glyph, this.color);
  final PixelGlyph glyph;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final rows = _bitmaps[glyph]!;
    final cell = size.width / 9;
    final paint = Paint()
      ..color = color
      ..isAntiAlias = false;
    for (var y = 0; y < 9; y++) {
      for (var x = 0; x < 9; x++) {
        if (rows[y][x] == '#') {
          canvas.drawRect(
            Rect.fromLTWH(x * cell, y * cell, cell + 0.01, cell + 0.01),
            paint,
          );
        }
      }
    }
  }

  @override
  bool shouldRepaint(_PixelPainter old) =>
      old.glyph != glyph || old.color != color;
}
