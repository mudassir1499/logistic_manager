import 'dart:async';

import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../state/app_state.dart';
import '../widgets/common.dart';
import 'product_detail.dart';

/// The catalogue: search, category filter, infinite scroll.
class CatalogueScreen extends StatefulWidget {
  const CatalogueScreen({super.key, required this.app});

  final AppState app;

  @override
  State<CatalogueScreen> createState() => _CatalogueScreenState();
}

class _CatalogueScreenState extends State<CatalogueScreen> {
  final _scroll = ScrollController();
  final _searchController = TextEditingController();

  final List<Product> _products = [];
  List<Category> _categories = [];
  String? _categorySlug;
  String _search = '';

  int _page = 1;
  bool _loading = true;
  bool _loadingMore = false;
  bool _hasMore = false;
  String? _error;
  Timer? _debounce;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
    _loadCategories();
    _load(reset: true);
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _scroll.dispose();
    _searchController.dispose();
    super.dispose();
  }

  void _onScroll() {
    // 400px of runway rather than waiting for the exact bottom, so the next page
    // is usually already there by the time the user reaches it.
    if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 400) {
      _loadMore();
    }
  }

  Future<void> _loadCategories() async {
    try {
      final data = await widget.app.api.get('/categories/', query: {'page_size': 100});
      final page = ApiPage.fromJson(data as Map<String, dynamic>, Category.fromJson);
      if (mounted) setState(() => _categories = page.results);
    } on ApiException {
      // The filter row simply does not appear. Not worth blocking the catalogue.
    }
  }

  Future<void> _load({bool reset = false}) async {
    if (reset) {
      setState(() {
        _loading = true;
        _error = null;
        _page = 1;
      });
    }
    try {
      final data = await widget.app.api.get('/products/', query: {
        'page': _page,
        'page_size': 20,
        'search': _search,
        'category__slug': _categorySlug,
      });
      final page = ApiPage.fromJson(data as Map<String, dynamic>, Product.fromJson);
      if (!mounted) return;
      setState(() {
        if (reset) _products.clear();
        _products.addAll(page.results);
        _hasMore = page.hasMore;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      if (error is ApiException && error.isAuthFailure) {
        widget.app.handleAuthFailure();
        return;
      }
      setState(() {
        _loading = false;
        _error = error.toString();
      });
    }
  }

  Future<void> _loadMore() async {
    if (_loadingMore || !_hasMore || _loading) return;
    setState(() => _loadingMore = true);
    _page += 1;
    await _load();
    if (mounted) setState(() => _loadingMore = false);
  }

  void _onSearchChanged(String value) {
    // Debounced: a request per keystroke would fire a dozen for one word, and
    // the answers can arrive out of order so the list flickers between results.
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), () {
      _search = value.trim();
      _load(reset: true);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: TextField(
            controller: _searchController,
            onChanged: _onSearchChanged,
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(
              hintText: 'Search products or SKU',
              prefixIcon: const Icon(Icons.search),
              isDense: true,
              suffixIcon: _searchController.text.isEmpty
                  ? null
                  : IconButton(
                      icon: const Icon(Icons.clear),
                      onPressed: () {
                        _searchController.clear();
                        _search = '';
                        _load(reset: true);
                      },
                    ),
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
            ),
          ),
        ),
        if (_categories.isNotEmpty)
          SizedBox(
            height: 44,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              children: [
                _categoryChip(null, 'All'),
                for (final category in _categories)
                  _categoryChip(category.slug, category.name),
              ],
            ),
          ),
        Expanded(child: _body()),
      ],
    );
  }

  Widget _categoryChip(String? slug, String label) {
    final selected = _categorySlug == slug;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ChoiceChip(
        label: Text(label),
        selected: selected,
        onSelected: (_) {
          setState(() => _categorySlug = slug);
          _load(reset: true);
        },
      ),
    );
  }

  Widget _body() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return AsyncView<int>(
        state: AsyncValue.failure(_error!),
        onRetry: () => _load(reset: true),
        builder: (_) => const SizedBox.shrink(),
      );
    }
    if (_products.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.search_off, size: 44, color: Brand.muted),
            const SizedBox(height: 12),
            Text(
              _search.isEmpty && _categorySlug == null
                  ? 'No products in the catalogue yet.'
                  : 'Nothing matched that search.',
              style: const TextStyle(color: Brand.muted),
              textAlign: TextAlign.center,
            ),
          ]),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: () => _load(reset: true),
      child: ListView.separated(
        controller: _scroll,
        padding: const EdgeInsets.all(12),
        itemCount: _products.length + (_hasMore ? 1 : 0),
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (context, index) {
          if (index >= _products.length) {
            return const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator()),
            );
          }
          return _ProductCard(
            product: _products[index],
            onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => ProductDetailScreen(
                app: widget.app, slug: _products[index].slug),
            )),
          );
        },
      ),
    );
  }
}

class _ProductCard extends StatelessWidget {
  const _ProductCard({required this.product, required this.onTap});

  final Product product;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: Color(0xFFE4E5E9)),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(10),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ProductThumb(url: product.images.isEmpty ? '' : product.images.first),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(product.name,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontWeight: FontWeight.w700, height: 1.25)),
                    const SizedBox(height: 6),
                    Row(children: [
                      // "from" when variants differ in price, so a £20 accessory
                      // does not read as the price of the £113 machine.
                      if (product.hasVariants)
                        const Padding(
                          padding: EdgeInsets.only(right: 4),
                          child: Text('from',
                              style: TextStyle(fontSize: 11, color: Brand.muted)),
                        ),
                      Money(product.displayPrice,
                          style: const TextStyle(
                              fontWeight: FontWeight.w800, color: Brand.goldDark)),
                    ]),
                    const SizedBox(height: 4),
                    Wrap(spacing: 6, runSpacing: 4, children: [
                      StatusChip('MOQ ${product.moq}'),
                      if (product.sku.isNotEmpty) StatusChip(product.sku),
                      if (product.readyToShip)
                        const StatusChip('Ready to ship', colour: Brand.success),
                    ]),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, color: Brand.muted),
            ],
          ),
        ),
      ),
    );
  }
}
