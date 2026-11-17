import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../widgets/common.dart';
import 'orders.dart';

/// The cart, its totals, and checkout.
class CartScreen extends StatefulWidget {
  const CartScreen({super.key, required this.app});

  final AppState app;

  @override
  State<CartScreen> createState() => CartScreenState();
}

class CartScreenState extends State<CartScreen> {
  AsyncValue<List<CartItem>> _state = const AsyncValue.loading();
  CartSummary _summary = CartSummary.empty();
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    load();
  }

  /// Public so the shell can refresh the cart when its tab is opened.
  Future<void> load() async {
    setState(() => _state = const AsyncValue.loading());
    try {
      // The list and its totals in parallel: they are independent, and doing
      // them in sequence doubles the time the spinner is on screen.
      final results = await Future.wait([
        widget.app.api.get('/cart/'),
        widget.app.api.get('/cart/summary/'),
      ]);
      final items = (results[0] as List)
          .map((e) => CartItem.fromJson(e as Map<String, dynamic>))
          .toList();
      final summary = CartSummary.fromJson(results[1] as Map<String, dynamic>);
      if (!mounted) return;
      setState(() {
        _state = AsyncValue.data(items);
        _summary = summary;
      });
      widget.app.setCartCount(summary.itemCount);
    } catch (error) {
      if (!mounted) return;
      setState(() => _state = AsyncValue.failure(error.toString()));
    }
  }

  Future<void> _updateQuantity(CartItem item, int quantity) async {
    setState(() => _busy = true);
    try {
      await widget.app.api.patch('/cart/${item.id}/', body: {'quantity': quantity});
      await load();
    } catch (error) {
      if (mounted) showApiError(context, error, widget.app);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _remove(CartItem item) async {
    setState(() => _busy = true);
    try {
      await widget.app.api.delete('/cart/${item.id}/');
      await load();
      if (mounted) showMessage(context, 'Removed');
    } catch (error) {
      if (mounted) showApiError(context, error, widget.app);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _checkout(List<CartItem> items) async {
    // Ready-to-ship marketplace goods are refused at the fulfilment centre
    // without these marks, so the server requires them. Collect them here
    // rather than letting checkout fail with a validation error.
    final needing = items.where((i) => i.needsLabels).toList();
    final Map<String, Map<String, String>> lines = {};

    if (needing.isNotEmpty) {
      final collected = await showDialog<Map<String, Map<String, String>>>(
        context: context,
        builder: (_) => _LabelDialog(items: needing),
      );
      if (collected == null) return; // cancelled
      lines.addAll(collected);
    }

    // The label dialog is awaited above, so this widget may have been disposed
    // (the user switched tabs, or the session was dropped) before we get here.
    // Using its context after that throws.
    if (!mounted) return;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Place this order?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${_summary.itemCount} item(s)'),
            const SizedBox(height: 6),
            Text('Total ${_summary.currency} ${_summary.total}',
                style: const TextStyle(fontWeight: FontWeight.w800)),
            const SizedBox(height: 10),
            const Text(
              'Your order is created as a draft. Our team confirms shipping '
              'costs before anything is charged.',
              style: TextStyle(fontSize: 12, color: Brand.muted),
            ),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Place order')),
        ],
      ),
    );
    if (confirmed != true) return;

    setState(() => _busy = true);
    try {
      final data = await widget.app.api.post('/checkout/', body: {'lines': lines});
      final order = Order.fromJson(data as Map<String, dynamic>);
      await load();
      await widget.app.refreshCartCount();
      if (!mounted) return;
      showMessage(context, 'Order #${order.id} placed');
      Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => OrderDetailScreen(app: widget.app, orderId: order.id),
      ));
    } catch (error) {
      if (mounted) showApiError(context, error, widget.app);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(
          child: AsyncView<List<CartItem>>(
            state: _state,
            onRetry: load,
            emptyMessage: 'Your cart is empty.\nBrowse the catalogue to add products.',
            emptyIcon: Icons.shopping_cart_outlined,
            isEmpty: (items) => items.isEmpty,
            builder: (items) => RefreshIndicator(
              onRefresh: load,
              child: ListView.separated(
                padding: const EdgeInsets.all(12),
                itemCount: items.length,
                separatorBuilder: (_, __) => const SizedBox(height: 10),
                itemBuilder: (_, i) => _CartRow(
                  item: items[i],
                  busy: _busy,
                  onQuantity: (q) => _updateQuantity(items[i], q),
                  onRemove: () => _remove(items[i]),
                ),
              ),
            ),
          ),
        ),
        if ((_state.value ?? const []).isNotEmpty) _totals(_state.value!),
      ],
    );
  }

  Widget _totals(List<CartItem> items) {
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
        decoration: const BoxDecoration(
          border: Border(top: BorderSide(color: Color(0xFFE4E5E9))),
        ),
        child: Column(
          children: [
            // Every figure here comes from the server. The commission rule lives
            // in one place, and recomputing it on the phone is how an app ends
            // up disagreeing with the invoice by a cent.
            _row('Subtotal', _summary.subtotal),
            if (_summary.commission != '0.00')
              _row('Commission', _summary.commission),
            const Divider(height: 18),
            _row('Total', _summary.total, bold: true),
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _busy ? null : () => _checkout(items),
                style: FilledButton.styleFrom(
                  backgroundColor: Brand.ink,
                  padding: const EdgeInsets.symmetric(vertical: 15),
                ),
                child: _busy
                    ? const SizedBox(height: 18, width: 18,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white))
                    : const Text('Checkout'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _row(String label, String amount, {bool bold = false}) {
    final style = TextStyle(
      fontWeight: bold ? FontWeight.w800 : FontWeight.w500,
      fontSize: bold ? 16 : 14,
      color: bold ? Brand.ink : Brand.muted,
    );
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: style),
          Text('${_summary.currency} $amount', style: style),
        ],
      ),
    );
  }
}

class _CartRow extends StatelessWidget {
  const _CartRow({
    required this.item,
    required this.busy,
    required this.onQuantity,
    required this.onRemove,
  });

  final CartItem item;
  final bool busy;
  final ValueChanged<int> onQuantity;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: Color(0xFFE4E5E9)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(item.productName,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontWeight: FontWeight.w700)),
                      if (item.variantName.isNotEmpty &&
                          item.variantName != 'null') ...[
                        const SizedBox(height: 2),
                        Text(item.variantName,
                            style: const TextStyle(
                                fontSize: 12, color: Brand.muted)),
                      ],
                      const SizedBox(height: 6),
                      Text('¥${item.unitPrice} each',
                          style: const TextStyle(
                              fontSize: 12, color: Brand.muted)),
                    ],
                  ),
                ),
                IconButton(
                  onPressed: busy ? null : onRemove,
                  icon: const Icon(Icons.delete_outline, color: Brand.danger),
                  tooltip: 'Remove',
                ),
              ],
            ),
            const SizedBox(height: 6),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Row(children: [
                  IconButton(
                    onPressed: busy || item.quantity <= 1
                        ? null
                        : () => onQuantity(item.quantity - 1),
                    icon: const Icon(Icons.remove_circle_outline, size: 20),
                    visualDensity: VisualDensity.compact,
                  ),
                  Text('${item.quantity}',
                      style: const TextStyle(fontWeight: FontWeight.w700)),
                  IconButton(
                    onPressed: busy ? null : () => onQuantity(item.quantity + 1),
                    icon: const Icon(Icons.add_circle_outline, size: 20),
                    visualDensity: VisualDensity.compact,
                  ),
                ]),
                Money(item.lineTotal),
              ],
            ),
            if (item.needsLabels)
              Container(
                margin: const EdgeInsets.only(top: 6),
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Brand.gold.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Row(children: [
                  Icon(Icons.label_outline, size: 15, color: Brand.goldDark),
                  SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      'Needs a label mark and carton mark at checkout',
                      style: TextStyle(fontSize: 11.5, color: Brand.goldDark),
                    ),
                  ),
                ]),
              ),
          ],
        ),
      ),
    );
  }
}

/// Collects the label marks the server requires for ready-to-ship goods.
class _LabelDialog extends StatefulWidget {
  const _LabelDialog({required this.items});

  final List<CartItem> items;

  @override
  State<_LabelDialog> createState() => _LabelDialogState();
}

class _LabelDialogState extends State<_LabelDialog> {
  final _formKey = GlobalKey<FormState>();
  late final Map<int, TextEditingController> _labelMarks;
  late final Map<int, TextEditingController> _cartonMarks;

  @override
  void initState() {
    super.initState();
    _labelMarks = {for (final i in widget.items) i.id: TextEditingController()};
    _cartonMarks = {for (final i in widget.items) i.id: TextEditingController()};
  }

  @override
  void dispose() {
    for (final c in _labelMarks.values) {
      c.dispose();
    }
    for (final c in _cartonMarks.values) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Label details'),
      content: SizedBox(
        width: 400,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'These items ship straight to a fulfilment centre, which '
                  'refuses cartons without them.',
                  style: TextStyle(fontSize: 12, color: Brand.muted),
                ),
                const SizedBox(height: 12),
                for (final item in widget.items) ...[
                  Text(item.productName,
                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
                  const SizedBox(height: 6),
                  TextFormField(
                    controller: _labelMarks[item.id],
                    decoration: const InputDecoration(
                        labelText: 'Label mark', isDense: true),
                    validator: (v) =>
                        (v == null || v.trim().isEmpty) ? 'Required' : null,
                  ),
                  const SizedBox(height: 8),
                  TextFormField(
                    controller: _cartonMarks[item.id],
                    decoration: const InputDecoration(
                        labelText: 'Carton mark', isDense: true),
                    validator: (v) =>
                        (v == null || v.trim().isEmpty) ? 'Required' : null,
                  ),
                  const SizedBox(height: 16),
                ],
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: () {
            if (!_formKey.currentState!.validate()) return;
            Navigator.pop(context, {
              for (final item in widget.items)
                '${item.id}': {
                  'label_mark': _labelMarks[item.id]!.text.trim(),
                  'carton_mark': _cartonMarks[item.id]!.text.trim(),
                }
            });
          },
          child: const Text('Continue'),
        ),
      ],
    );
  }
}
