/// Dense table: black header row, thin row dividers, mono cells. The
/// focused/hovered row is yellow with a blue `->` first cell. Virtualised.
library;

import 'package:flutter/material.dart';

import 'pressable.dart';
import 'tokens.dart';

class BrutalColumn {
  const BrutalColumn(
    this.title, {
    this.width,
    this.flex = 1,
    this.align = TextAlign.left,
    this.sortKey,
  });

  final String title;

  /// Fixed logical width; when null the column takes [flex] shares.
  final double? width;
  final int flex;
  final TextAlign align;

  /// Passed to [BrutalTable.onSort] when the header is pressed.
  final String? sortKey;
}

class BrutalTable<T> extends StatelessWidget {
  const BrutalTable({
    super.key,
    required this.columns,
    required this.items,
    required this.cellBuilder,
    this.onActivate,
    this.onSecondary,
    this.selected,
    this.onSort,
    this.sortKey,
    this.sortAscending = true,
    this.onFocusItem,
    this.autofocusFirst = false,
    this.controller,
  });

  final List<BrutalColumn> columns;
  final List<T> items;

  /// Returns the cell widget for [column] of [item]; cells get the row's
  /// foreground colour through DefaultTextStyle.
  final Widget Function(BuildContext context, T item, int index, int column)
  cellBuilder;
  final ValueChanged<T>? onActivate;
  final ValueChanged<T>? onSecondary;
  final T? selected;
  final ValueChanged<String>? onSort;
  final String? sortKey;
  final bool sortAscending;
  final ValueChanged<T>? onFocusItem;
  final bool autofocusFirst;
  final ScrollController? controller;

  Widget _cell(BrutalTokens t, int i, Widget child) {
    final col = columns[i];
    final padded = Padding(
      padding: EdgeInsets.symmetric(horizontal: t.s2),
      child: Align(
        alignment: switch (col.align) {
          TextAlign.right => Alignment.centerRight,
          TextAlign.center => Alignment.center,
          _ => Alignment.centerLeft,
        },
        child: child,
      ),
    );
    return col.width != null
        ? SizedBox(width: col.width! * t.scale, child: padded)
        : Expanded(flex: col.flex, child: padded);
  }

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Container(
      decoration: BoxDecoration(
        color: t.panel,
        border: Border.all(color: t.ink, width: t.border),
        boxShadow: [BoxShadow(color: t.shadow, offset: t.shadowOffsetLarge)],
      ),
      child: Column(
        children: [
          Container(
            height: t.rowHeight * 0.8,
            color: t.headerBar,
            child: Row(
              children: [
                for (var i = 0; i < columns.length; i++)
                  _cell(
                    t,
                    i,
                    columns[i].sortKey == null || onSort == null
                        ? Text(
                            columns[i].title.toUpperCase(),
                            style: t.label.copyWith(color: t.onHeaderBar),
                          )
                        : Pressable(
                            hoverFocus: false,
                            onPressed: () => onSort!(columns[i].sortKey!),
                            builder: (c, st) => Text(
                              '${columns[i].title.toUpperCase()}${sortKey == columns[i].sortKey ? (sortAscending ? ' ↓' : ' ↑') : ''}',
                              style: t.label.copyWith(
                                color: st.active ? t.focus : t.onHeaderBar,
                              ),
                            ),
                          ),
                  ),
              ],
            ),
          ),
          Expanded(
            child: ListView.builder(
              controller: controller,
              itemCount: items.length,
              itemExtent: t.rowHeight,
              itemBuilder: (context, index) {
                final item = items[index];
                return Pressable(
                  autofocus: autofocusFirst && index == 0,
                  onPressed: onActivate == null
                      ? () {}
                      : () => onActivate!(item),
                  onSecondaryPressed: onSecondary == null
                      ? null
                      : () => onSecondary!(item),
                  onFocusChange: (f) {
                    if (f) onFocusItem?.call(item);
                  },
                  builder: (c, st) {
                    final hot =
                        st.active || (selected != null && item == selected);
                    final fg = hot ? t.onFocus : t.ink;
                    return Container(
                      decoration: BoxDecoration(
                        color: hot ? t.focus : t.panel,
                        border: Border(
                          top: BorderSide(
                            color: hot ? t.ink : t.muted,
                            width: hot ? t.border : t.borderThin,
                          ),
                          bottom: hot
                              ? BorderSide(color: t.ink, width: t.border)
                              : BorderSide.none,
                        ),
                      ),
                      child: DefaultTextStyle(
                        style: t.row.copyWith(color: fg),
                        child: Row(
                          children: [
                            for (var i = 0; i < columns.length; i++)
                              if (i == 0 && st.active)
                                SizedBox(
                                  width: columns[0].width != null
                                      ? columns[0].width! * t.scale
                                      : null,
                                  child: Container(
                                    alignment: Alignment.center,
                                    color: t.primary,
                                    height: double.infinity,
                                    child: Text(
                                      '->',
                                      style: t.label.copyWith(
                                        color: t.onPrimary,
                                      ),
                                    ),
                                  ),
                                )
                              else
                                _cell(t, i, cellBuilder(c, item, index, i)),
                          ],
                        ),
                      ),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
