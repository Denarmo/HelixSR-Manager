import 'dart:io';

import 'package:flutter/material.dart';

import '../../engine/engine.dart';
import '../brutal/brutal.dart';

/// Cover art with a hatched initials placeholder while it loads or when no
/// source has any. Local files show at once; otherwise [resolveArtwork]
/// finds the Steam app (by name for non-Steam games), downloads the image
/// once and caches it.
class GameCover extends StatefulWidget {
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
  State<GameCover> createState() => _GameCoverState();
}

class _GameCoverState extends State<GameCover> {
  String? _path;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(GameCover old) {
    super.didUpdateWidget(old);
    if (old.game.id != widget.game.id || old.hero != widget.hero) {
      _path = null;
      _load();
    }
  }

  void _load() {
    final g = widget.game;
    final local = widget.hero ? g.localHeroPath : g.localCoverPath;
    if (local != null && File(local).existsSync()) {
      _path = local;
      return;
    }
    final id = g.id;
    final hero = widget.hero;
    resolveArtwork(g, hero: hero).then((path) {
      if (!mounted || path == null) return;
      if (widget.game.id != id || widget.hero != hero) return;
      setState(() => _path = path);
    });
  }

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    Widget placeholder() => _Placeholder(widget.game.name, hero: widget.hero);
    final path = _path;
    final img = path == null
        ? placeholder()
        : Image.file(
            File(path),
            fit: BoxFit.cover,
            errorBuilder: (_, _, _) => placeholder(),
          );
    return Container(
      width: widget.width,
      height: widget.height,
      decoration: widget.border
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
