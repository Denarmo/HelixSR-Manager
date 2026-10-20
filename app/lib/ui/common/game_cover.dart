import 'dart:io';

import 'package:flutter/material.dart';

import '../../engine/engine.dart';
import '../brutal/brutal.dart';

/// Steam cover art (local library cache first, then Steam's CDN) with a
/// hatched file-name placeholder when there is none or the network is down.
class GameCover extends StatelessWidget {
  const GameCover(
    this.game, {
    super.key,
    this.width,
    this.height,
    this.hero = false,
    this.border = true,
  });
  final GameInfo game;
  final double? width, height;
  final bool hero;
  final bool border;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    final local = hero ? game.localHeroPath : game.localCoverPath;
    final remote = hero ? game.remoteHeroUrl : game.remoteCoverUrl;
    Widget placeholder() => _Placeholder(game.name, hero: hero);
    Widget img;
    if (local != null && File(local).existsSync()) {
      img = Image.file(
        File(local),
        fit: BoxFit.cover,
        errorBuilder: (_, _, _) => placeholder(),
      );
    } else if (remote != null) {
      img = Image.network(
        remote,
        fit: BoxFit.cover,
        errorBuilder: (_, _, _) => placeholder(),
        loadingBuilder: (c, child, p) => p == null ? child : placeholder(),
      );
    } else {
      img = placeholder();
    }
    return Container(
      width: width,
      height: height,
      decoration: border
          ? BoxDecoration(
              border: Border.all(color: t.ink, width: t.border),
            )
          : null,
      child: ClipRect(child: SizedBox.expand(child: img)),
    );
  }
}

class _Placeholder extends StatelessWidget {
  const _Placeholder(this.name, {required this.hero});
  final String name;
  final bool hero;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    final initials = name
        .split(RegExp(r'[\s_\-:]+'))
        .where((w) => w.isNotEmpty)
        .take(3)
        .map((w) => w[0].toUpperCase())
        .join();
    return CustomPaint(
      painter: _HatchPainter(t.muted, t.panel),
      child: Center(
        child: Text(
          initials.isEmpty ? '?' : initials,
          style: t.displaySmall.copyWith(color: t.mutedText),
        ),
      ),
    );
  }
}

class _HatchPainter extends CustomPainter {
  _HatchPainter(this.line, this.bg);
  final Color line, bg;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = bg);
    final p = Paint()
      ..color = line
      ..strokeWidth = 2
      ..isAntiAlias = false;
    canvas.save();
    canvas.clipRect(Offset.zero & size);
    for (double x = -size.height; x < size.width; x += 10) {
      canvas.drawLine(Offset(x, size.height), Offset(x + size.height, 0), p);
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(_HatchPainter old) => old.line != line || old.bg != bg;
}
