import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../widgets.dart';

/// Build an order: pick a customer, add lines, send it.
///
/// THE TOTAL SHOWN HERE IS A PREVIEW
///
/// It is computed on the device so the person can see the figure grow as they
/// add lines, but it is never sent. The server recomputes it from the same
/// lines and that is the number the customer is billed. If the two ever
/// disagree the server wins, which is why the confirmation step quotes what
/// came BACK rather than what was calculated here.
class OrderCreateScreen extends StatefulWidget {
  const OrderCreateScreen({super.key});
  @override
  State<OrderCreateScreen> createState() => _OrderCreateScreenState();
}

class _Line {
  _Line({
    required this.product,
    required this.quantity,
    this.variant,
    this.priceOverride,
  });

  final Map<String, dynamic> product;
  int quantity;
  Map<String, dynamic>? variant;
  String? priceOverride;

  /// What this line costs, in the same order of precedence the server uses:
  /// an explicit override, else the variation, else the product.
  double get unitPrice {
    if ((priceOverride ?? '').isNotEmpty) {
      return double.tryParse(priceOverride!) ?? 0;
    }
    if (variant != null) return double.tryParse('${variant!['price']}') ?? 0;
    return double.tryParse('${product['price']}') ?? 0;
  }

  double get lineTotal => unitPrice * quantity;

  Map<String, dynamic> toJson() => {
        'product': product['id'],
        if (variant != null) 'variant': variant!['id'],
        'quantity': quantity,
        if ((priceOverride ?? '').isNotEmpty) 'price': priceOverride,
      };
}

class _OrderCreateScreenState extends State<OrderCreateScreen> {
  Map<String, dynamic>? _customer;
  final List<_Line> _lines = [];
  final _shipping = TextEditingController();
  final _notes = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _shipping.dispose();
    _notes.dispose();
    super.dispose();
  }

  double get _goodsTotal => _lines.fold(0.0, (sum, l) => sum + l.lineTotal);
  double get _grandTotal =>
      _goodsTotal + (double.tryParse(_shipping.text.trim()) ?? 0);

  Future<void> _pickCustomer() async {
    final chosen = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const _PickerSheet(title: 'Choose customer', isProduct: false),
    );
    if (chosen != null) setState(() => _customer = chosen);
  }

  Future<void> _addLine() async {
    final product = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const _PickerSheet(title: 'Add product', isProduct: true),
    );
    if (product == null || !mounted) return;

    final line = await showModalBottomSheet<_Line>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _LineSheet(product: product),
    );
    if (line != null) setState(() => _lines.add(line));
  }

  Future<void> _submit() async {
    if (_customer == null) {
      toast(context, 'Choose a customer first.', error: true);
      return;
    }
    if (_lines.isEmpty) {
      toast(context, 'Add at least one product.', error: true);
      return;
    }

    setState(() => _busy = true);
    try {
      final created = await Api.instance.createOrder({
        'customer': _customer!['id'],
        'items': _lines.map((l) => l.toJson()).toList(),
        if (_shipping.text.trim().isNotEmpty) 'shipping_cost': _shipping.text.trim(),
        if (_notes.text.trim().isNotEmpty) 'notes': _notes.text.trim(),
      });
      if (!mounted) return;

      // Quotes the figures that came BACK, not the preview: the server is the
      // authority on the total and the tracking number does not exist until
      // the row is written.
      await showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Order created'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Tracking number',
                  style: TextStyle(fontSize: 12, color: Brand.muted)),
              SelectableText('${created['tracking_number']}',
                  style: const TextStyle(
                      fontSize: 16, fontWeight: FontWeight.w800)),
              const SizedBox(height: 12),
              Text('Total ${money(created['total'])}  ·  '
                  '${created['items']} line(s)'),
            ],
          ),
          actions: [
            FilledButton(
                onPressed: () => Navigator.pop(c), child: const Text('Done')),
          ],
        ),
      );
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('New order')),
      bottomNavigationBar: Container(
        padding: EdgeInsets.only(
            left: 16, right: 16, top: 12,
            bottom: MediaQuery.of(context).padding.bottom + 12),
        decoration: const BoxDecoration(
          color: Brand.card,
          border: Border(top: BorderSide(color: Brand.border)),
        ),
        child: Row(
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text('Total (preview)',
                    style: TextStyle(fontSize: 11, color: Brand.muted)),
                Text(money(_grandTotal),
                    style: const TextStyle(
                        fontSize: 20, fontWeight: FontWeight.w800)),
              ],
            ),
            const Spacer(),
            FilledButton(
              onPressed: _busy ? null : _submit,
              child: Text(_busy ? 'Creating…' : 'Create order'),
            ),
          ],
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SectionCard(
            title: 'Customer',
            child: _customer == null
                ? OutlinedButton.icon(
                    onPressed: _pickCustomer,
                    icon: const Icon(Icons.person_search),
                    label: const Text('Choose customer'),
                  )
                : ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text('${_customer!['name']}',
                        style: const TextStyle(fontWeight: FontWeight.w700)),
                    subtitle: Text('${_customer!['phone'] ?? ''}'),
                    trailing: TextButton(
                        onPressed: _pickCustomer, child: const Text('Change')),
                  ),
          ),
          const SizedBox(height: 14),

          SectionCard(
            title: 'Items (${_lines.length})',
            trailing: IconButton(
                icon: const Icon(Icons.add, size: 20), onPressed: _addLine),
            child: _lines.isEmpty
                ? const Text('No items yet. Tap + to add a product.',
                    style: TextStyle(fontSize: 12.5, color: Brand.muted))
                : Column(
                    children: _lines.asMap().entries.map((e) {
                      final i = e.key;
                      final l = e.value;
                      return Padding(
                        padding: const EdgeInsets.symmetric(vertical: 6),
                        child: Row(
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text('${l.product['name']}',
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(
                                          fontSize: 13.5,
                                          fontWeight: FontWeight.w600)),
                                  Text(
                                    [
                                      if (l.variant != null) '${l.variant!['name']}',
                                      '${l.quantity} × ${money(l.unitPrice)}',
                                      if ((l.priceOverride ?? '').isNotEmpty)
                                        'custom price',
                                    ].join('  ·  '),
                                    style: const TextStyle(
                                        fontSize: 12, color: Brand.muted),
                                  ),
                                ],
                              ),
                            ),
                            Text(money(l.lineTotal),
                                style: const TextStyle(
                                    fontWeight: FontWeight.w700, fontSize: 13.5)),
                            IconButton(
                              icon: const Icon(Icons.close,
                                  size: 17, color: Brand.danger),
                              onPressed: () => setState(() => _lines.removeAt(i)),
                            ),
                          ],
                        ),
                      );
                    }).toList(),
                  ),
          ),
          const SizedBox(height: 14),

          SectionCard(
            title: 'Costs and notes',
            child: Column(
              children: [
                TextField(
                  controller: _shipping,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  onChanged: (_) => setState(() {}),
                  decoration: const InputDecoration(labelText: 'Shipping cost'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _notes,
                  maxLines: 3,
                  decoration: const InputDecoration(
                      labelText: 'Notes', hintText: 'Internal notes…'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
        ],
      ),
    );
  }
}

/// Search-and-pick for customers or products. One sheet, because the two are
/// the same interaction over a different endpoint.
class _PickerSheet extends StatefulWidget {
  const _PickerSheet({required this.title, required this.isProduct});
  final String title;
  final bool isProduct;
  @override
  State<_PickerSheet> createState() => _PickerSheetState();
}

class _PickerSheetState extends State<_PickerSheet> {
  final _search = TextEditingController();
  late Future<List<Map<String, dynamic>>> _future;

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
    final q = _search.text.trim().isEmpty ? null : _search.text.trim();
    _future = widget.isProduct
        ? Api.instance.products(search: q)
        : Api.instance.customers(search: q);
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SizedBox(
        height: MediaQuery.of(context).size.height * 0.75,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: [
                  Text(widget.title,
                      style: const TextStyle(
                          fontSize: 17, fontWeight: FontWeight.w800)),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _search,
                    autofocus: true,
                    textInputAction: TextInputAction.search,
                    onSubmitted: (_) => _load(),
                    decoration: InputDecoration(
                      hintText: 'Search…',
                      prefixIcon: const Icon(Icons.search),
                      suffixIcon: IconButton(
                          icon: const Icon(Icons.arrow_forward),
                          onPressed: _load),
                    ),
                  ),
                ],
              ),
            ),
            Expanded(
              child: FutureBuilder<List<Map<String, dynamic>>>(
                future: _future,
                builder: (context, snap) => AsyncBody(
                  snapshot: snap,
                  onRetry: _load,
                  emptyText: 'Nothing matches.',
                  isEmpty: (d) => d.isEmpty,
                  builder: (rows) => ListView.builder(
                    itemCount: rows.length,
                    itemBuilder: (_, i) {
                      final row = rows[i];
                      return ListTile(
                        title: Text('${row['name'] ?? ''}',
                            maxLines: 2, overflow: TextOverflow.ellipsis),
                        subtitle: Text(widget.isProduct
                            ? money(row['price'])
                            : '${row['phone'] ?? ''}'),
                        onTap: () => Navigator.pop(context, row),
                      );
                    },
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Quantity, variation and an optional negotiated price for one line.
class _LineSheet extends StatefulWidget {
  const _LineSheet({required this.product});
  final Map<String, dynamic> product;
  @override
  State<_LineSheet> createState() => _LineSheetState();
}

class _LineSheetState extends State<_LineSheet> {
  final _qty = TextEditingController(text: '1');
  final _price = TextEditingController();
  Map<String, dynamic>? _variant;
  late final List<Map<String, dynamic>> _variants = List<Map<String, dynamic>>.from(
      (widget.product['variants'] as List?) ?? const []);

  @override
  void initState() {
    super.initState();
    // A product that HAS variations has no single price — the customer buys a
    // specific one — so the first is preselected rather than leaving the line
    // priced off the parent.
    if (_variants.isNotEmpty) _variant = _variants.first;
    _qty.text = '${widget.product['moq'] ?? 1}';
  }

  @override
  void dispose() {
    _qty.dispose();
    _price.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 16, right: 16, top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('${widget.product['name']}',
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          const SizedBox(height: 16),
          if (_variants.isNotEmpty) ...[
            DropdownButtonFormField<int>(
              initialValue: _variant?['id'] as int?,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Variation'),
              items: _variants
                  .map((v) => DropdownMenuItem(
                        value: v['id'] as int,
                        child: Text('${v['name']} — ${money(v['price'])}',
                            overflow: TextOverflow.ellipsis),
                      ))
                  .toList(),
              onChanged: (id) => setState(() =>
                  _variant = _variants.firstWhere((v) => v['id'] == id)),
            ),
            const SizedBox(height: 12),
          ],
          TextField(
            controller: _qty,
            keyboardType: TextInputType.number,
            decoration: InputDecoration(
                labelText: 'Quantity',
                helperText: 'MOQ ${widget.product['moq'] ?? 1}'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _price,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(
              labelText: 'Price override',
              // Said explicitly: the obvious fear when typing a different price
              // is that it changes the listing for everybody.
              helperText: 'Leave blank to use the catalogue price. '
                  'This changes the order only, never the listing.',
              helperMaxLines: 2,
            ),
          ),
          const SizedBox(height: 18),
          FilledButton(
            onPressed: () {
              final qty = int.tryParse(_qty.text.trim()) ?? 0;
              if (qty < 1) {
                toast(context, 'Quantity must be at least 1.', error: true);
                return;
              }
              Navigator.pop(
                context,
                _Line(
                  product: widget.product,
                  quantity: qty,
                  variant: _variant,
                  priceOverride: _price.text.trim().isEmpty ? null : _price.text.trim(),
                ),
              );
            },
            child: const Text('Add to order'),
          ),
        ],
      ),
    );
  }
}
