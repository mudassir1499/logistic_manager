import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../widgets.dart';
import 'product_edit.dart';

/// The catalogue: search, inspect, and edit the fields worth editing on a phone.
///
/// Price, MOQ, draft and private are here. Images, variations and specifications
/// are not — they need a real screen and a keyboard, and a half-finished editor
/// that silently drops a variation is worse than sending somebody to the laptop.
class ProductsScreen extends StatefulWidget {
  const ProductsScreen({super.key});
  @override
  State<ProductsScreen> createState() => _ProductsScreenState();
}

class _ProductsScreenState extends State<ProductsScreen> {
  late Future<List<Map<String, dynamic>>> _future;
  final _search = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  void _load() {
    _future = Api.instance.products(
        search: _search.text.trim().isEmpty ? null : _search.text.trim());
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Products')),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: Brand.ink,
        foregroundColor: Colors.white,
        onPressed: () async {
          final changed = await Navigator.push<bool>(context,
              MaterialPageRoute(builder: (_) => const ProductEditScreen()));
          if (changed == true) _load();
        },
        icon: const Icon(Icons.add),
        label: const Text('New listing'),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: TextField(
              controller: _search,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => _load(),
              decoration: InputDecoration(
                hintText: 'Search by name or SKU…',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _search.text.isEmpty
                    ? null
                    : IconButton(
                        icon: const Icon(Icons.clear),
                        onPressed: () { _search.clear(); _load(); }),
              ),
            ),
          ),
          Expanded(
            child: FutureBuilder<List<Map<String, dynamic>>>(
              future: _future,
              builder: (context, snap) => AsyncBody(
                snapshot: snap,
                onRetry: _load,
                emptyIcon: Icons.inventory_2_outlined,
                emptyText: 'No products match.',
                isEmpty: (d) => d.isEmpty,
                builder: (rows) => RefreshIndicator(
                  onRefresh: () async => _load(),
                  child: ListView.separated(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 88),
                    itemCount: rows.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (_, i) => _ProductCard(
                      product: rows[i],
                      onChanged: _load,
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Pull the first usable image out of whatever shape the serializer returned.
String? imageOf(Map<String, dynamic> product, String? baseUrl) {
  final images = product['images'];
  if (images is List && images.isNotEmpty) {
    final first = images.first;
    final url = first is Map ? (first['url'] ?? first['src'] ?? first['image']) : first;
    if (url is String && url.isNotEmpty) {
      return url.startsWith('http') ? url : '${baseUrl ?? ''}$url';
    }
  }
  return null;
}

class _ProductCard extends StatelessWidget {
  const _ProductCard({required this.product, required this.onChanged});
  final Map<String, dynamic> product;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    final img = imageOf(product, Api.instance.baseUrl);
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () async {
          await Navigator.push(
            context,
            MaterialPageRoute(
                builder: (_) => ProductDetailScreen(
                    slug: '${product['slug']}', name: '${product['name']}')),
          );
          onChanged();
        },
        child: Padding(
          padding: const EdgeInsets.all(10),
          child: Row(
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: SizedBox(
                  width: 56,
                  height: 56,
                  child: img == null
                      ? Container(
                          color: Brand.bg,
                          child: const Icon(Icons.image_not_supported_outlined,
                              color: Brand.muted, size: 20))
                      : Image.network(img, fit: BoxFit.cover,
                          errorBuilder: (_, __, ___) => Container(
                              color: Brand.bg,
                              child: const Icon(Icons.broken_image_outlined,
                                  color: Brand.muted, size: 20))),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('${product['name'] ?? ''}',
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontSize: 14, fontWeight: FontWeight.w600)),
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        Text(money(product['price']),
                            style: const TextStyle(
                                fontWeight: FontWeight.w800, fontSize: 14)),
                        const SizedBox(width: 8),
                        Text('MOQ ${product['moq'] ?? '—'}',
                            style: const TextStyle(
                                color: Brand.muted, fontSize: 12)),
                        const Spacer(),
                        if (product['is_draft'] == true)
                          const StatusChip('Draft', colour: Brand.warn),
                        if (product['is_private'] == true) ...[
                          const SizedBox(width: 4),
                          const StatusChip('Private', colour: Brand.goldText),
                        ],
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class ProductDetailScreen extends StatefulWidget {
  const ProductDetailScreen({super.key, required this.slug, this.name});
  /// Slug, not id: ProductViewSet sets lookup_field = 'slug'.
  final String slug;
  final String? name;
  @override
  State<ProductDetailScreen> createState() => _ProductDetailScreenState();
}

class _ProductDetailScreenState extends State<ProductDetailScreen> {
  late Future<Map<String, dynamic>> _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() => setState(() => _future = Api.instance.product(widget.slug));

  Future<void> _patch(Map<String, dynamic> fields, String label) async {
    final ok = await runWrite(
        context, () => Api.instance.updateProduct(widget.slug, fields),
        success: label);
    if (ok) _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.name ?? 'Product', overflow: TextOverflow.ellipsis),
        actions: [
          IconButton(
            icon: const Icon(Icons.edit_outlined),
            onPressed: () async {
              final data = await _future;
              if (!context.mounted) return;
              final changed = await Navigator.push<bool>(
                  context,
                  MaterialPageRoute(
                      builder: (_) => ProductEditScreen(product: data)));
              if (changed == true) _load();
            },
          ),
        ],
      ),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, snap) => AsyncBody(
          snapshot: snap,
          onRetry: _load,
          builder: (p) {
            final img = imageOf(p, Api.instance.baseUrl);
            final variants = List<Map<String, dynamic>>.from(
                (p['variants'] as List?) ?? const []);
            return ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (img != null)
                  ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child: Image.network(img,
                        height: 200, width: double.infinity, fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) => const SizedBox.shrink()),
                  ),
                const SizedBox(height: 14),
                Text('${p['name'] ?? ''}',
                    style: const TextStyle(
                        fontSize: 19, fontWeight: FontWeight.w800)),
                const SizedBox(height: 14),

                SectionCard(
                  title: 'Details',
                  child: Column(
                    children: [
                      DetailRow('SKU', '${p['sku'] ?? ''}'),
                      DetailRow('Price', money(p['price'])),
                      DetailRow('MOQ', '${p['moq'] ?? ''}'),
                      DetailRow('Weight', '${p['weight'] ?? '—'} kg'),
                      DetailRow('Pcs/carton', '${p['carton_qty'] ?? '—'}'),
                    ],
                  ),
                ),
                const SizedBox(height: 14),

                _EditCard(
                  price: '${p['price'] ?? ''}',
                  moq: '${p['moq'] ?? ''}',
                  onSave: (price, moq) => _patch(
                      {'price': price, 'moq': int.tryParse(moq) ?? 0},
                      'Product updated'),
                ),
                const SizedBox(height: 14),

                SectionCard(
                  title: 'Visibility',
                  child: Column(
                    children: [
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Draft'),
                        subtitle: const Text('Hidden from customers',
                            style: TextStyle(fontSize: 12)),
                        value: p['is_draft'] == true,
                        onChanged: (v) =>
                            _patch({'is_draft': v}, v ? 'Marked draft' : 'Published'),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Private'),
                        subtitle: const Text('Only assigned customers see it',
                            style: TextStyle(fontSize: 12)),
                        value: p['is_private'] == true,
                        onChanged: (v) => _patch(
                            {'is_private': v}, v ? 'Made private' : 'Made public'),
                      ),
                    ],
                  ),
                ),

                if (variants.isNotEmpty) ...[
                  const SizedBox(height: 14),
                  SectionCard(
                    title: 'Variations (${variants.length})',
                    child: Column(
                      children: variants
                          .map((v) => Padding(
                                padding: const EdgeInsets.symmetric(vertical: 5),
                                child: Row(
                                  children: [
                                    Expanded(
                                        child: Text('${v['name'] ?? ''}',
                                            style: const TextStyle(fontSize: 13.5))),
                                    Text(money(v['price']),
                                        style: const TextStyle(
                                            fontWeight: FontWeight.w700,
                                            fontSize: 13.5)),
                                  ],
                                ),
                              ))
                          .toList(),
                    ),
                  ),
                ],
              ],
            );
          },
        ),
      ),
    );
  }
}

class _EditCard extends StatefulWidget {
  const _EditCard({required this.price, required this.moq, required this.onSave});
  final String price;
  final String moq;
  final void Function(String price, String moq) onSave;
  @override
  State<_EditCard> createState() => _EditCardState();
}

class _EditCardState extends State<_EditCard> {
  late final _price = TextEditingController(text: widget.price);
  late final _moq = TextEditingController(text: widget.moq);

  @override
  void dispose() {
    _price.dispose();
    _moq.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SectionCard(
      title: 'Edit',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _price,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(labelText: 'Price'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: TextField(
                  controller: _moq,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'MOQ'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: () => widget.onSave(_price.text.trim(), _moq.text.trim()),
            child: const Text('Save changes'),
          ),
        ],
      ),
    );
  }
}
