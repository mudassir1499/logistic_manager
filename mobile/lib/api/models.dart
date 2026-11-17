/// Typed views over the API's JSON.
///
/// MONEY IS KEPT AS A STRING, NOT PARSED INTO A DOUBLE.
///
/// The API serialises prices as strings precisely because JSON numbers are
/// IEEE-754 doubles, and 0.1 + 0.2 is not 0.3. Parsing them into `double` here
/// would reintroduce the error the server took care to avoid, and a cart total
/// that is a cent out is the kind of bug nobody can reproduce.
///
/// So amounts stay as the exact text the server sent and are only ever
/// displayed. Nothing in this app does arithmetic on money — the cart summary
/// and the order total both come from the server, which is the only place the
/// commission rules live.
library;

String _string(dynamic value) => value?.toString() ?? '';

int _int(dynamic value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse(value?.toString() ?? '') ?? 0;
}

class Category {
  Category({required this.slug, required this.name, required this.subcategories});

  final String slug;
  final String name;
  final List<Category> subcategories;

  factory Category.fromJson(Map<String, dynamic> json) => Category(
        slug: _string(json['slug']),
        name: _string(json['name']),
        subcategories: ((json['subcategories'] as List?) ?? const [])
            .map((e) => Category.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

class ProductVariant {
  ProductVariant({
    required this.id,
    required this.name,
    required this.price,
    required this.stock,
    required this.image,
  });

  final int id;
  final String name;
  final String price;
  final int stock;
  final String image;

  factory ProductVariant.fromJson(Map<String, dynamic> json) => ProductVariant(
        id: _int(json['id']),
        name: _string(json['name']),
        price: _string(json['price']),
        stock: _int(json['stock']),
        image: _string(json['image']),
      );
}

class ProductAttribute {
  ProductAttribute({required this.name, required this.value});

  final String name;
  final String value;

  factory ProductAttribute.fromJson(Map<String, dynamic> json) => ProductAttribute(
        name: _string(json['name']),
        value: _string(json['value']),
      );
}

class Product {
  Product({
    required this.id,
    required this.name,
    required this.slug,
    required this.sku,
    required this.price,
    required this.moq,
    required this.weight,
    required this.images,
    required this.variants,
    required this.attributes,
    required this.readyToShip,
  });

  final int id;
  final String name;
  final String slug;
  final String sku;
  final String price;
  final int moq;
  final String weight;
  final List<String> images;
  final List<ProductVariant> variants;
  final List<ProductAttribute> attributes;
  final bool readyToShip;

  bool get hasVariants => variants.isNotEmpty;

  /// The cheapest variant price, or the product's own when it has none.
  ///
  /// Compared as numbers only to pick which STRING to show — the chosen value
  /// is still the server's exact text.
  String get displayPrice {
    if (variants.isEmpty) return price;
    var best = variants.first.price;
    var bestValue = double.tryParse(best) ?? double.infinity;
    for (final variant in variants) {
      final value = double.tryParse(variant.price) ?? double.infinity;
      if (value < bestValue) {
        bestValue = value;
        best = variant.price;
      }
    }
    return best;
  }

  factory Product.fromJson(Map<String, dynamic> json) => Product(
        id: _int(json['id']),
        name: _string(json['name']),
        slug: _string(json['slug']),
        sku: _string(json['sku']),
        price: _string(json['price']),
        moq: _int(json['moq']) == 0 ? 1 : _int(json['moq']),
        weight: _string(json['weight']),
        images: ((json['images'] as List?) ?? const [])
            .map((e) => _string((e as Map<String, dynamic>)['url']))
            .where((url) => url.isNotEmpty)
            .toList(),
        variants: ((json['variants'] as List?) ?? const [])
            .map((e) => ProductVariant.fromJson(e as Map<String, dynamic>))
            .toList(),
        attributes: ((json['attributes'] as List?) ?? const [])
            .map((e) => ProductAttribute.fromJson(e as Map<String, dynamic>))
            .toList(),
        readyToShip: json['ready_to_ship'] == true,
      );
}

class CartItem {
  CartItem({
    required this.id,
    required this.productId,
    required this.productName,
    required this.variantName,
    required this.quantity,
    required this.unitPrice,
    required this.lineTotal,
    required this.needsLabels,
  });

  final int id;
  final int productId;
  final String productName;
  final String variantName;
  final int quantity;
  final String unitPrice;
  final String lineTotal;
  final bool needsLabels;

  factory CartItem.fromJson(Map<String, dynamic> json) => CartItem(
        id: _int(json['id']),
        productId: _int(json['product']),
        productName: _string(json['product_name']),
        variantName: _string(json['variant_name']),
        quantity: _int(json['quantity']),
        unitPrice: _string(json['unit_price']),
        lineTotal: _string(json['line_total']),
        needsLabels: json['needs_labels'] == true,
      );
}

class CartSummary {
  CartSummary({
    required this.itemCount,
    required this.currency,
    required this.subtotal,
    required this.commission,
    required this.total,
  });

  final int itemCount;
  final String currency;
  final String subtotal;
  final String commission;
  final String total;

  factory CartSummary.fromJson(Map<String, dynamic> json) => CartSummary(
        itemCount: _int(json['item_count']),
        currency: _string(json['currency']),
        subtotal: _string(json['subtotal']),
        commission: _string(json['commission_amount']),
        total: _string(json['total']),
      );

  static CartSummary empty() => CartSummary(
        itemCount: 0, currency: '', subtotal: '0.00', commission: '0.00', total: '0.00');
}

class OrderLine {
  OrderLine({required this.productName, required this.quantity, required this.price});

  final String productName;
  final int quantity;
  final String price;

  factory OrderLine.fromJson(Map<String, dynamic> json) => OrderLine(
        productName: _string(json['product_name']),
        quantity: _int(json['quantity']),
        price: _string(json['price']),
      );
}

class Order {
  Order({
    required this.id,
    required this.status,
    required this.paymentStatus,
    required this.total,
    required this.date,
    required this.items,
  });

  final int id;
  final String status;
  final String paymentStatus;
  final String total;
  final String date;
  final List<OrderLine> items;

  factory Order.fromJson(Map<String, dynamic> json) => Order(
        id: _int(json['id']),
        status: _string(json['status']),
        paymentStatus: _string(json['payment_status']),
        total: _string(json['total']),
        date: _string(json['date']),
        items: ((json['items'] as List?) ?? const [])
            .map((e) => OrderLine.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

class LedgerEntry {
  LedgerEntry({
    required this.id,
    required this.entryType,
    required this.amount,
    required this.currency,
    required this.date,
    required this.description,
  });

  final int id;
  final String entryType;
  final String amount;
  final String currency;
  final String date;
  final String description;

  bool get isCredit => entryType == 'credit';

  factory LedgerEntry.fromJson(Map<String, dynamic> json) => LedgerEntry(
        id: _int(json['id']),
        entryType: _string(json['entry_type']),
        amount: _string(json['amount']),
        currency: _string(json['currency']),
        date: _string(json['date']),
        description: _string(json['description']),
      );
}

class Ticket {
  Ticket({
    required this.id,
    required this.subject,
    required this.status,
    required this.priority,
    required this.updatedAt,
  });

  final int id;
  final String subject;
  final String status;
  final String priority;
  final String updatedAt;

  factory Ticket.fromJson(Map<String, dynamic> json) => Ticket(
        id: _int(json['id']),
        subject: _string(json['subject']),
        status: _string(json['status']),
        priority: _string(json['priority']),
        updatedAt: _string(json['updated_at']),
      );
}

class Me {
  Me({
    required this.username,
    required this.fullName,
    required this.role,
    required this.customerName,
    required this.phone,
    required this.address,
    required this.email,
  });

  final String username;
  final String fullName;
  final String role;
  final String customerName;
  final String phone;
  final String address;
  final String email;

  String get displayName =>
      customerName.isNotEmpty ? customerName : (fullName.isNotEmpty ? fullName : username);

  factory Me.fromJson(Map<String, dynamic> json) {
    final customer = (json['customer'] as Map<String, dynamic>?) ?? const {};
    return Me(
      username: _string(json['username']),
      fullName: _string(json['full_name']),
      role: _string(json['role']),
      customerName: _string(customer['name']),
      phone: _string(customer['phone']),
      address: _string(customer['address']),
      email: _string(customer['email']).isNotEmpty
          ? _string(customer['email'])
          : _string(json['email']),
    );
  }
}

/// One page of a paginated list endpoint.
class ApiPage<T> {
  ApiPage({required this.results, required this.count, required this.next});

  final List<T> results;
  final int count;
  final String? next;

  bool get hasMore => next != null && next!.isNotEmpty;

  factory ApiPage.fromJson(
    Map<String, dynamic> json,
    T Function(Map<String, dynamic>) item,
  ) =>
      ApiPage(
        results: ((json['results'] as List?) ?? const [])
            .map((e) => item(e as Map<String, dynamic>))
            .toList(),
        count: _int(json['count']),
        next: json['next'] as String?,
      );
}
