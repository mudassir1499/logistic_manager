import 'package:flutter_test/flutter_test.dart';

import 'package:backoffice/api.dart';

void main() {
  group('base URL normalisation', () {
    test('accepts the address exactly as the user gave it', () {
      // The live site, with the trailing slash it is usually copied with.
      expect(Api.normaliseBaseUrl('https://mudassirllc.com/'),
          'https://mudassirllc.com');
    });

    test('assumes https for a bare hostname', () {
      // Nobody types the scheme. Defaulting to http would send a staff
      // password in clear.
      expect(Api.normaliseBaseUrl('mudassirllc.com'), 'https://mudassirllc.com');
    });

    test('keeps only the origin when a page URL is pasted', () {
      // Copying the address bar while logged into the back office is the
      // obvious thing to do; without trimming, every call would be sent to
      // /dashboard/api/v1/... and 404 with no clue why.
      expect(Api.normaliseBaseUrl('https://mudassirllc.com/dashboard/'),
          'https://mudassirllc.com');
      expect(Api.normaliseBaseUrl('https://mudassirllc.com/products/?q=drill'),
          'https://mudassirllc.com');
    });

    test('tolerates whitespace from a paste', () {
      expect(Api.normaliseBaseUrl('  https://mudassirllc.com  '),
          'https://mudassirllc.com');
    });

    test('preserves a port for local testing', () {
      expect(Api.normaliseBaseUrl('http://127.0.0.1:8000'),
          'http://127.0.0.1:8000');
    });

    test('does not downgrade an explicit http address', () {
      // Someone testing against a LAN box should get what they asked for.
      expect(Api.normaliseBaseUrl('http://192.168.1.50:8000/'),
          'http://192.168.1.50:8000');
    });
  });
}
