import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../widgets/common.dart';

/// One product: photos, variants, specs, and add-to-cart.
class ProductDetailScreen extends StatefulWidget {
  const ProductDetailScreen({super.key, required this.app, required this.slug});

  final AppState app;
  final String slug;

  @override
  State<ProductDetailScreen> createState() => _ProductDetailScreenState();
}

class _ProductDetailScreenState extends State<ProductDetailScreen> {
  AsyncValue<Product> _state = const AsyncValue.loading();
  ProductVariant? _variant;
  int _quantity = 1;
  bool _adding = false;
  int _photoIndex = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _state = const AsyncValue.loading());
    try {
      final data = await widget.app.api.get('/products/${widget.slug}/');
      final product = Product.fromJson(data as Map<String, dynamic>);
      if (!mounted) return;
      setState(() {
        _state = AsyncValue.data(product);
        // Quantity starts at the minimum the supplier will sell, not at 1 —
        // otherwise the first tap of "Add" is rejected by the server for a rule
        // the customer was never shown.
        _quantity = product.moq;
        _variant = product.variants.isNotEmpty ? product.variants.first : null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _state = AsyncValue.failure(error.toString()));
    }
  }

  Future<void> _addToCart(Product product) async {
    setState(() => _adding = true);
    try {
      await widget.app.api.post('/cart/', body: {
        'product': product.id,
        if (_variant != null) 'variant': _variant!.id,
        'quantity': _quantity,
      });
      await widget.app.refreshCartCount();
      if (mounted) showMessage(context, 'Added to cart');
    } catch (error) {
      if (mounted) showApiError(context, error, widget.app);
    } finally {
      if (mounted) setState(() => _adding = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Product')),
      body: AsyncView<Product>(
        state: _state,
        onRetry: _load,
        builder: (product) => _content(product),
      ),
      bottomNavigationBar: _state.value == null ? null : _addBar(_state.value!),
    );
  }

  Widget _content(Product product) {
    final photos = product.images;
    final price = _variant?.price ?? product.displayPrice;

    return ListView(
      padding: const EdgeInsets.only(bottom: 24),
      children: [
        if (photos.isNotEmpty) ...[
          SizedBox(
            height: 280,
            child: PageView.builder(
              itemCount: photos.length,
              onPageChanged: (i) => setState(() => _photoIndex = i),
              itemBuilder: (_, i) => Image.network(
                photos[i],
                fit: BoxFit.contain,
                errorBuilder: (_, __, ___) => Container(
                  color: Brand.surface,
                  child: const Icon(Icons.image_not_supported_outlined,
                      size: 48, color: Brand.muted),
                ),
              ),
            ),
          ),
          if (photos.length > 1)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: List.generate(photos.length, (i) {
                  final active = i == _photoIndex;
                  return Container(
                    width: active ? 18 : 6,
                    height: 6,
                    margin: const EdgeInsets.symmetric(horizontal: 3),
                    decoration: BoxDecoration(
                      color: active ? Brand.gold : Brand.muted.withValues(alpha: 0.35),
                      borderRadius: BorderRadius.circular(999),
                    ),
                  );
                }),
              ),
            ),
        ] else
          Container(
            height: 200,
            color: Brand.surface,
            child: const Icon(Icons.inventory_2_outlined, size: 56, color: Brand.muted),
          ),

        Padding(
          padding: const EdgeInsets.fromLTRB(16, 18, 16, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(product.name,
                  style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800,
                      height: 1.3)),
              const SizedBox(height: 10),
              Money(price,
                  style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800,
                      color: Brand.goldDark)),
              const SizedBox(height: 10),
              Wrap(spacing: 8, runSpacing: 6, children: [
                StatusChip('MOQ ${product.moq}'),
                if (product.sku.isNotEmpty) StatusChip('SKU ${product.sku}'),
                if (product.weight.isNotEmpty && product.weight != 'null')
                  StatusChip('${product.weight} kg'),
                if (product.readyToShip)
                  const StatusChip('Ready to ship', colour: Brand.success),
              ]),

              if (product.hasVariants) ...[
                const SizedBox(height: 20),
                const Text('Options',
                    style: TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: product.variants.map((variant) {
                    final selected = _variant?.id == variant.id;
                    return ChoiceChip(
                      label: Text(variant.name,
                          style: const TextStyle(fontSize: 12)),
                      selected: selected,
                      onSelected: (_) => setState(() => _variant = variant),
                    );
                  }).toList(),
                ),
                if (_variant != null && _variant!.stock > 0)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text('${_variant!.stock} available',
                        style: const TextStyle(fontSize: 12, color: Brand.muted)),
                  ),
              ],

              if (product.attributes.isNotEmpty) ...[
                const SizedBox(height: 22),
                const Text('Specifications',
                    style: TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 8),
                ...product.attributes.map((attribute) => Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          SizedBox(
                            width: 130,
                            child: Text(attribute.name,
                                style: const TextStyle(
                                    color: Brand.muted, fontSize: 13)),
                          ),
                          Expanded(
                            child: Text(attribute.value,
                                style: const TextStyle(fontSize: 13)),
                          ),
                        ],
                      ),
                    )),
              ],
            ],
          ),
        ),
      ],
    );
  }

  Widget _addBar(Product product) {
    return SafeArea(
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
        decoration: const BoxDecoration(
          border: Border(top: BorderSide(color: Color(0xFFE4E5E9))),
        ),
        child: Row(
          children: [
            _QuantityStepper(
              value: _quantity,
              minimum: product.moq,
              onChanged: (value) => setState(() => _quantity = value),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: FilledButton.icon(
                onPressed: _adding ? null : () => _addToCart(product),
                style: FilledButton.styleFrom(
                  backgroundColor: Brand.ink,
                  padding: const EdgeInsets.symmetric(vertical: 15),
                ),
                icon: _adding
                    ? const SizedBox(height: 16, width: 16,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white))
                    : const Icon(Icons.add_shopping_cart, size: 18),
                label: Text(_adding ? 'Adding…' : 'Add to cart'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _QuantityStepper extends StatelessWidget {
  const _QuantityStepper({
    required this.value,
    required this.minimum,
    required this.onChanged,
  });

  final int value;
  final int minimum;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        border: Border.all(color: const Color(0xFFE4E5E9)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            // Cannot go below the MOQ: the server rejects it, so offering the
            // choice only produces an error the customer cannot act on.
            onPressed: value > minimum ? () => onChanged(value - 1) : null,
            icon: const Icon(Icons.remove, size: 18),
            visualDensity: VisualDensity.compact,
            tooltip: value > minimum ? 'Fewer' : 'Minimum order is $minimum',
          ),
          ConstrainedBox(
            constraints: const BoxConstraints(minWidth: 30),
            child: Text('$value',
                textAlign: TextAlign.center,
                style: const TextStyle(fontWeight: FontWeight.w700)),
          ),
          IconButton(
            onPressed: () => onChanged(value + 1),
            icon: const Icon(Icons.add, size: 18),
            visualDensity: VisualDensity.compact,
            tooltip: 'More',
          ),
        ],
      ),
    );
  }
}
