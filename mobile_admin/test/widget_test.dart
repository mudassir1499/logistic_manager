import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:backoffice/main.dart';

void main() {
  testWidgets('unconfigured app opens on the sign-in screen', (tester) async {
    // With no saved server and no token, the gate must show setup rather than
    // the shell - otherwise a fresh install lands on an empty dashboard and
    // looks broken.
    await tester.pumpWidget(const BackOfficeApp());
    await tester.pump();

    expect(find.text('Back Office'), findsOneWidget);
    expect(find.text('Sign in'), findsOneWidget);
    expect(find.byType(NavigationBar), findsNothing);
  });
}
