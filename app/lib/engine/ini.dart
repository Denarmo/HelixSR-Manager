/// INI text helpers: OptiScaler.ini ("Key = Value") and Unreal Engine
/// config files ("Key=Value"). Ports of SetIniValue and the *UeIniValue
/// functions in src/Engine.cs.
library;

String setIniValue(String text, String key, String value, String? section) {
  final keyRe = RegExp(
    '^(${RegExp.escape(key)})[ \\t]*=[ \\t]*([^\\r\\n]*?)[ \\t]*(?=\\r?\$)',
    multiLine: true,
  );
  if (keyRe.hasMatch(text)) {
    return text.replaceFirstMapped(keyRe, (_) => '$key = $value');
  }
  if (section != null && section.isNotEmpty) {
    final secRe = RegExp(
      '^\\[${RegExp.escape(section)}\\][ \\t]*(\\r?\\n)',
      multiLine: true,
    );
    final m = secRe.firstMatch(text);
    if (m != null) {
      final idx = m.end;
      return '${text.substring(0, idx)}$key = $value\r\n${text.substring(idx)}';
    }
    return '$text\r\n[$section]\r\n$key = $value\r\n';
  }
  return '$text\r\n$key = $value\r\n';
}

/// Reads "Key = Value" from [text]; null when absent.
String? getIniValue(String text, String key) {
  final m = RegExp(
    '^${RegExp.escape(key)}[ \\t]*=[ \\t]*([^\\r\\n]*?)[ \\t]*\\r?\$',
    multiLine: true,
  ).firstMatch(text);
  return m?.group(1);
}

RegExpMatch? _ueSection(String text, String section) => RegExp(
  '^\\[${RegExp.escape(section)}\\][ \\t]*\\r?\\n(.*?)(?=^\\[|(?![\\s\\S]))',
  multiLine: true,
  dotAll: true,
).firstMatch(text);

String? getUeIniValue(String text, String section, String key) {
  final sec = _ueSection(text, section);
  if (sec == null) return null;
  final m = RegExp(
    '^${RegExp.escape(key)}[ \\t]*=[ \\t]*([^\\r\\n]*?)[ \\t]*\\r?\$',
    multiLine: true,
  ).firstMatch(sec.group(1)!);
  return m?.group(1);
}

/// Section scoped "Key=Value" setter (no spaces around '=').
String setUeIniValue(String text, String section, String key, String value) {
  final line = '$key=$value';
  final sec = _ueSection(text, section);
  if (sec == null) {
    final sep = text.isEmpty || text.endsWith('\n') ? '' : '\r\n';
    return '$text$sep[$section]\r\n$line\r\n';
  }
  final body = sec.group(1)!;
  final bodyStart = sec.start + sec.group(0)!.length - body.length;
  final keyRe = RegExp(
    '^${RegExp.escape(key)}[ \\t]*=[^\\r\\n]*',
    multiLine: true,
  );
  String newBody;
  if (keyRe.hasMatch(body)) {
    newBody = body.replaceFirstMapped(keyRe, (_) => line);
  } else {
    final trimmed = body.replaceFirst(RegExp(r'[\r\n]+$'), '');
    final tail = body.substring(trimmed.length);
    newBody =
        '${trimmed.isNotEmpty ? '$trimmed\r\n' : ''}$line${tail.isNotEmpty ? tail : '\r\n'}';
  }
  return text.substring(0, bodyStart) +
      newBody +
      text.substring(bodyStart + body.length);
}

String removeUeIniValue(String text, String section, String key) {
  final sec = _ueSection(text, section);
  if (sec == null) return text;
  final body = sec.group(1)!;
  final bodyStart = sec.start + sec.group(0)!.length - body.length;
  final newBody = body.replaceAll(
    RegExp('^${RegExp.escape(key)}[ \\t]*=[^\\r\\n]*\\r?\\n?', multiLine: true),
    '',
  );
  return text.substring(0, bodyStart) +
      newBody +
      text.substring(bodyStart + body.length);
}
