// Parses REAL responses captured from https://mudassirllc.com/api/v1/.
//
// The other test file uses payloads I wrote, which proves the parsing matches
// what I THINK the API returns. This one proves it matches what the API
// actually returns — the difference being every field I might have renamed,
// mistyped, or assumed was always present.
//
// The fixtures in test/fixtures/ are committed on purpose. Fetching live data
// during a test would make the suite fail when the office wifi drops, and
// couple it to whatever happens to be in the catalogue that day.
//
// Refresh them with:
//   curl -s "https://mudassirllc.com/api/v1/products/?page_size=3" \
//     -o test/fixtures/products__page_size_3.json

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mudassir_app/api/models.dart';

Map<String, dynamic> _fixture(String name) {
  final file = File('test/fixtures/$name.json');
  expect(file.existsSync(), isTrue, reason: 'missing fixture $name.json');
  return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
}

void main() {
  group('live product list', () {
    test('parses a real page of the production catalogue', () {
      final page = ApiPage.fromJson(
          _fixture('products__page_size_3'), Product.fromJson);

      expect(page.count, greaterThan(0));
      expect(page.results, isNotEmpty);
      expect(page.hasMore, isTrue, reason: '122 products should paginate');

      for (final product in page.results) {
        // The fields every screen reads. A rename on the server surfaces here
        // rather than as a blank row on a phone.
        expect(product.id, greaterThan(0));
        expect(product.name, isNotEmpty);
        expect(product.slug, isNotEmpty, reason: 'the detail route keys on slug');
        expect(product.price, isNotEmpty);
        expect(product.moq, greaterThanOrEqualTo(1));
      }
    });

    test('a null weight becomes empty, never the string "null"', () {
      // Production sends "weight": null on most products. Rendered naively that
      // puts a chip reading "null kg" on the product page.
      final page = ApiPage.fromJson(
          _fixture('products__page_size_3'), Product.fromJson);
      for (final product in page.results) {
        expect(product.weight, isNot('null'));
      }
    });

    test('image URLs are absolute, so Image.network can load them', () {
      final page = ApiPage.fromJson(
          _fixture('products__page_size_3'), Product.fromJson);
      final withImages = page.results.where((p) => p.images.isNotEmpty);
      expect(withImages, isNotEmpty, reason: 'the fixture should include a photo');
      for (final product in withImages) {
        for (final url in product.images) {
          expect(url, startsWith('http'),
              reason: 'a relative /media/ path cannot be loaded from a phone');
        }
      }
    });

    test('products with no SKU do not break the card', () {
      // Production SKUs are blank — the generator has only run locally. The
      // catalogue card must simply omit the chip, and a null must never reach
      // the widget as the literal string "null".
      final page = ApiPage.fromJson(
          _fixture('products__page_size_3'), Product.fromJson);
      for (final product in page.results) {
        expect(product.sku, isNot('null'));
      }
    });
  });

  group('live product detail', () {
    test('parses the real detail response', () {
      final product = Product.fromJson(_fixture('product_detail'));
      expect(product.slug, isNotEmpty);
      expect(product.name, isNotEmpty);
      // No variants on this one, so the "from" price must fall back to the
      // product's own price rather than throwing on an empty list.
      expect(product.displayPrice, product.price);
      expect(product.displayPrice, isNotEmpty);
    });
  });

  group('live categories', () {
    test('parses categories and their subcategories', () {
      final page =
          ApiPage.fromJson(_fixture('categories__page_size_5'), Category.fromJson);
      expect(page.results, isNotEmpty);

      for (final category in page.results) {
        expect(category.slug, isNotEmpty,
            reason: 'the catalogue filters by ?category__slug=');
        expect(category.name, isNotEmpty);
      }

      final withChildren =
          page.results.where((c) => c.subcategories.isNotEmpty);
      expect(withChildren, isNotEmpty);
      for (final child in withChildren.first.subcategories) {
        expect(child.slug, isNotEmpty);
        expect(child.name, isNotEmpty);
      }
    });
  });
}
