import 'package:flutter/material.dart';

import 'app/app.dart';
import 'app/app_model.dart';

Future<void> main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  final model = AppModel(args: args);
  runApp(HelixApp(model: model));
  await model.init();
}
