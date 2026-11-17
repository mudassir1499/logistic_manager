// Drives the app's REAL ApiClient against a REAL server over the network.
//
// Deliberately NOT in test/ — `flutter test` runs everything there, and a suite
// that needs the internet fails on a train. Run this one on purpose:
//
//   flutter test test_live/production_smoke_test.dart
//   flutter test test_live/production_smoke_test.dart --dart-define=API_BASE_URL=http://127.0.0.1:8000
//
// It is the closest thing to running the app without a device: same client,
// same parsing, same error handling. Every call is a GET or a deliberately
// failing login, so it creates nothing and changes nothing on the server.

import 'package:flutter_test/flutter_test.dart';
import 'package:mudassir_app/api/client.dart';
import 'package:mudassir_app/api/models.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  late ApiClient api;

  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    // The token store is a platform plugin with no implementation in a test
    // process; without this every call that touches storage throws.
    //
    // The ignore is because this file sits outside test/ on purpose — it needs
    // the network, and `flutter test` must not run it by default — so the
    // analyzer does not treat it as test code.
    // ignore: invalid_use_of_visible_for_testing_member
    SharedPreferences.setMockInitialValues({});
    api = ApiClient();
    // ignore: avoid_print
    print('Target: ${ApiClient.defaultBaseUrl}');
  });

  test('catalogue list loads and parses', () async {
    final page = ApiPage.fromJson(
        await api.get('/products/', query: {'page_size': 5}) as Map<String, dynamic>,
        Product.fromJson);
    expect(page.count, greaterThan(0));
    expect(page.results, isNotEmpty);
    final first = page.results.first;
    expect(first.name, isNotEmpty);
    expect(first.slug, isNotEmpty);
    // ignore: avoid_print
    print('  ${page.count} products; first "${first.name}" @ ${first.displayPrice}, '
        'MOQ ${first.moq}, ${first.images.length} image(s)');
  }, timeout: const Timeout(Duration(seconds: 60)));

  test('search returns a narrower set', () async {
    final all = ApiPage.fromJson(
        await api.get('/products/', query: {'page_size': 1}) as Map<String, dynamic>,
        Product.fromJson);
    final hits = ApiPage.fromJson(
        await api.get('/products/', query: {'search': 'drill', 'page_size': 5})
            as Map<String, dynamic>,
        Product.fromJson);
    expect(hits.count, lessThanOrEqualTo(all.count));
    // ignore: avoid_print
    print('  search "drill": ${hits.count} of ${all.count}');
  }, timeout: const Timeout(Duration(seconds: 60)));

  test('categories load with their subcategories', () async {
    final page = ApiPage.fromJson(
        await api.get('/categories/', query: {'page_size': 50}) as Map<String, dynamic>,
        Category.fromJson);
    expect(page.results, isNotEmpty);
    final subs = page.results.fold<int>(0, (n, c) => n + c.subcategories.length);
    for (final category in page.results) {
      expect(category.slug, isNotEmpty);
    }
    // ignore: avoid_print
    print('  ${page.results.length} categories, $subs subcategories');
  }, timeout: const Timeout(Duration(seconds: 60)));

  test('product detail loads by slug', () async {
    final page = ApiPage.fromJson(
        await api.get('/products/', query: {'page_size': 1}) as Map<String, dynamic>,
        Product.fromJson);
    final slug = page.results.first.slug;
    final product =
        Product.fromJson(await api.get('/products/$slug/') as Map<String, dynamic>);
    expect(product.slug, slug);
    expect(product.displayPrice, isNotEmpty);
    // ignore: avoid_print
    print('  "$slug" -> ${product.name}, ${product.variants.length} variant(s), '
        '${product.attributes.length} spec(s)');
  }, timeout: const Timeout(Duration(seconds: 60)));

  test('a protected endpoint answers 401, not an HTML error page', () async {
    // The app signs the user out on a 401. If the server answered with HTML
    // instead, the client would report a generic failure and the session would
    // hang around broken.
    expect(
      () => api.get('/me/'),
      throwsA(isA<ApiException>().having((e) => e.isAuthFailure, 'isAuthFailure', true)),
    );
  }, timeout: const Timeout(Duration(seconds: 60)));

  test('bad credentials are refused cleanly', () async {
    await expectLater(
      api.login(email: 'nobody@example.invalid', password: 'definitely-wrong'),
      throwsA(isA<ApiException>()),
    );
    expect(api.isSignedIn, isFalse, reason: 'a failed login must not store a token');
  }, timeout: const Timeout(Duration(seconds: 60)));

  test('an unknown slug is a clean 404', () async {
    await expectLater(
      api.get('/products/definitely-not-a-real-slug-xyz/'),
      throwsA(isA<ApiException>().having((e) => e.statusCode, 'statusCode', 404)),
    );
  }, timeout: const Timeout(Duration(seconds: 60)));
}
