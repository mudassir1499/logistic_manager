// Tests for the parts worth testing without a server: the JSON parsing that
// every screen depends on, and the money handling that must not drift.
//
// The scaffold's default test was removed — it referenced MyApp, which this app
// does not have, so it could never have compiled.

import 'package:flutter_test/flutter_test.dart';
import 'package:mudassir_app/api/models.dart';

void main() {
  group('Product', () {
    test('parses the API shape', () {
      final product = Product.fromJson({
        'id': 7,
        'name': 'Impact Drill',
        'slug': 'impact-drill',
        'sku': 'THI-0023',
        'price': '99.00',
        'moq': 5,
        'weight': '2.000',
        'ready_to_ship': true,
        'images': [
          {'id': 1, 'url': 'https://example.com/a.jpg'},
          {'id': 2, 'url': ''},
        ],
        'variants': [
          {'id': 11, 'name': 'Blue', 'price': '113.00', 'stock': 5, 'is_active': true},
          {'id': 12, 'name': 'Battery', 'price': '20.00', 'stock': 9, 'is_active': true},
        ],
        'attributes': [
          {'name': 'Brand', 'value': 'Acme'},
        ],
      });

      expect(product.id, 7);
      expect(product.sku, 'THI-0023');
      expect(product.moq, 5);
      expect(product.readyToShip, isTrue);
      // The blank URL is dropped rather than rendering an empty image slot.
      expect(product.images, ['https://example.com/a.jpg']);
      expect(product.variants.length, 2);
      expect(product.attributes.single.name, 'Brand');
    });

    test('shows the cheapest variant as the "from" price', () {
      final product = Product.fromJson({
        'id': 1, 'name': 'x', 'slug': 'x', 'price': '99.00', 'moq': 1,
        'variants': [
          {'id': 1, 'name': 'a', 'price': '113.00'},
          {'id': 2, 'name': 'b', 'price': '20.00'},
          {'id': 3, 'name': 'c', 'price': '68.00'},
        ],
      });
      // Exactly the server's string, not a re-formatted number.
      expect(product.displayPrice, '20.00');
    });

    test('falls back to the product price when there are no variants', () {
      final product = Product.fromJson({
        'id': 1, 'name': 'x', 'slug': 'x', 'price': '12.50', 'moq': 1,
      });
      expect(product.displayPrice, '12.50');
    });

    test('a missing MOQ never becomes zero', () {
      // A zero MOQ would let the quantity stepper start at 0 and every add be
      // rejected by the server.
      final product = Product.fromJson({'id': 1, 'name': 'x', 'slug': 'x'});
      expect(product.moq, 1);
    });

    test('survives missing and null fields', () {
      final product = Product.fromJson({'id': 1});
      expect(product.name, '');
      expect(product.images, isEmpty);
      expect(product.variants, isEmpty);
      expect(product.readyToShip, isFalse);
    });
  });

  group('money', () {
    test('prices keep the server text exactly', () {
      // Parsed as a double and printed back, 0.10 would render as "0.1" and
      // 1234.50 could render as "1234.5". Both are wrong on an invoice.
      final item = CartItem.fromJson({
        'id': 1, 'product': 2, 'product_name': 'x', 'quantity': 3,
        'unit_price': '0.10', 'line_total': '1234.50',
      });
      expect(item.unitPrice, '0.10');
      expect(item.lineTotal, '1234.50');
    });

    test('cart summary reads the server totals verbatim', () {
      final summary = CartSummary.fromJson({
        'item_count': 2, 'currency': 'RMB', 'subtotal': '250.00',
        'commission_amount': '25.00', 'total': '275.00',
      });
      expect(summary.total, '275.00');
      expect(summary.commission, '25.00');
      expect(summary.itemCount, 2);
    });
  });

  group('ApiPage', () {
    test('reports whether more pages exist', () {
      final page = ApiPage.fromJson({
        'count': 40,
        'next': 'https://example.com/api/v1/products/?page=2',
        'results': [
          {'id': 1, 'name': 'a', 'slug': 'a'},
        ],
      }, Product.fromJson);
      expect(page.count, 40);
      expect(page.hasMore, isTrue);
      expect(page.results.single.name, 'a');
    });

    test('the last page has no more', () {
      final page = ApiPage.fromJson(
        {'count': 1, 'next': null, 'results': []}, Product.fromJson);
      expect(page.hasMore, isFalse);
    });
  });

  group('Me', () {
    test('prefers the customer name for display', () {
      final me = Me.fromJson({
        'username': 'a@b.com', 'full_name': 'Aisha R', 'role': 'customer',
        'customer': {'name': 'Acme Trading', 'phone': '+971', 'email': 'a@b.com'},
      });
      expect(me.displayName, 'Acme Trading');
      expect(me.phone, '+971');
    });

    test('falls back when there is no customer record', () {
      final me = Me.fromJson({
        'username': 'a@b.com', 'full_name': '', 'role': 'customer', 'customer': null,
      });
      expect(me.displayName, 'a@b.com');
    });
  });
}
