import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../widgets.dart';
import 'order_create.dart';

/// Order model choices, mirrored from orders/models.py.
///
/// Hard-coded rather than fetched: they are a two-value enum that has not
/// changed in the life of the project, and a dropdown that cannot render until
/// a second request lands is worse than one that is occasionally out of date.
/// If they ever grow, the API's own validation is what catches a stale client.
const _orderStatuses = {'draft': 'Draft', 'confirmed': 'Confirmed'};
const _paymentStatuses = {'unpaid': 'Unpaid', 'partial': 'Partial', 'paid': 'Paid'};

class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key});
  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  late Future<List<Map<String, dynamic>>> _future;
  final _search = TextEditingController();
  String? _status;

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
    _future = Api.instance.orders(
      search: _search.text.trim().isEmpty ? null : _search.text.trim(),
      status: _status,
    );
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Orders')),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: Brand.ink,
        foregroundColor: Colors.white,
        onPressed: () async {
          final created = await Navigator.push<bool>(context,
              MaterialPageRoute(builder: (_) => const OrderCreateScreen()));
          if (created == true) _load();
        },
        icon: const Icon(Icons.add),
        label: const Text('New order'),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 6),
            child: TextField(
              controller: _search,
              textInputAction: TextInputAction.search,
              // Submitted rather than filtered as you type: search runs on the
              // server across every order, so a request per keystroke would be
              // both slow and rate-limited.
              onSubmitted: (_) => _load(),
              decoration: InputDecoration(
                hintText: 'Search orders, customer or tracking…',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _search.text.isEmpty
                    ? null
                    : IconButton(
                        icon: const Icon(Icons.clear),
                        onPressed: () { _search.clear(); _load(); },
                      ),
              ),
            ),
          ),
          SizedBox(
            height: 44,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              children: [
                _filter('All', null),
                ..._orderStatuses.entries.map((e) => _filter(e.value, e.key)),
              ],
            ),
          ),
          const Divider(height: 12),
          Expanded(
            child: FutureBuilder<List<Map<String, dynamic>>>(
              future: _future,
              builder: (context, snap) => AsyncBody(
                snapshot: snap,
                onRetry: _load,
                emptyIcon: Icons.receipt_long_outlined,
                emptyText: 'No orders match.',
                isEmpty: (d) => d.isEmpty,
                builder: (orders) => RefreshIndicator(
                  onRefresh: () async => _load(),
                  child: ListView.separated(
                    padding: const EdgeInsets.fromLTRB(12, 12, 12, 88),
                    itemCount: orders.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (_, i) => _OrderCard(
                      order: orders[i],
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

  Widget _filter(String label, String? value) {
    final on = _status == value;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ChoiceChip(
        label: Text(label),
        selected: on,
        onSelected: (_) { _status = value; _load(); },
      ),
    );
  }
}

class _OrderCard extends StatelessWidget {
  const _OrderCard({required this.order, required this.onChanged});
  final Map<String, dynamic> order;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    final tracking = (order['tracking_number'] ?? '').toString();
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () async {
          await Navigator.push(
            context,
            MaterialPageRoute(
                builder: (_) => OrderDetailScreen(id: order['id'] as int)),
          );
          onChanged();
        },
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '${order['customer_name'] ?? 'Order'}',
                      style: const TextStyle(
                          fontSize: 15, fontWeight: FontWeight.w700),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  StatusChip('${_orderStatuses[order['status']] ?? order['status'] ?? '—'}'),
                ],
              ),
              const SizedBox(height: 6),
              Row(
                children: [
                  Text('#${order['id']}',
                      style: const TextStyle(color: Brand.muted, fontSize: 12.5)),
                  const SizedBox(width: 10),
                  Text(prettyDate(order['date'] as String?),
                      style: const TextStyle(color: Brand.muted, fontSize: 12.5)),
                  const Spacer(),
                  Text(money(order['total']),
                      style: const TextStyle(
                          fontWeight: FontWeight.w800, fontSize: 15)),
                ],
              ),
              if (tracking.isNotEmpty) ...[
                const SizedBox(height: 6),
                Row(
                  children: [
                    const Icon(Icons.local_shipping_outlined,
                        size: 13, color: Brand.muted),
                    const SizedBox(width: 5),
                    Text(tracking,
                        style: const TextStyle(
                            fontSize: 12, color: Brand.goldText,
                            fontFeatures: [])),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// One order, with the fields staff may change.
class OrderDetailScreen extends StatefulWidget {
  const OrderDetailScreen({super.key, required this.id});
  final int id;
  @override
  State<OrderDetailScreen> createState() => _OrderDetailScreenState();
}

class _OrderDetailScreenState extends State<OrderDetailScreen> {
  late Future<Map<String, dynamic>> _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() => setState(() => _future = Api.instance.order(widget.id));

  Future<void> _patch(Map<String, dynamic> fields, String label) async {
    final ok = await runWrite(
      context,
      () => Api.instance.updateOrder(widget.id, fields),
      success: label,
    );
    if (ok) _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Order #${widget.id}')),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, snap) => AsyncBody(
          snapshot: snap,
          onRetry: _load,
          builder: (order) {
            final items = List<Map<String, dynamic>>.from(
                (order['items'] as List?) ?? const []);
            return RefreshIndicator(
              onRefresh: () async => _load(),
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  SectionCard(
                    title: '${order['customer_name'] ?? 'Customer'}',
                    child: Column(
                      children: [
                        DetailRow('Placed', prettyDate(order['date'] as String?)),
                        DetailRow('Total', money(order['total'])),
                        DetailRow('Tracking', '${order['tracking_number'] ?? ''}'),
                        DetailRow('Shipping', money(order['shipping_cost'])),
                        DetailRow('Weight', '${order['total_weight'] ?? '—'}'),
                        DetailRow('CBM', '${order['total_cbm'] ?? '—'}'),
                      ],
                    ),
                  ),
                  const SizedBox(height: 14),

                  SectionCard(
                    title: 'Status',
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _Picker(
                          label: 'Order status',
                          value: '${order['status'] ?? ''}',
                          options: _orderStatuses,
                          onChanged: (v) => _patch({'status': v}, 'Status updated'),
                        ),
                        const SizedBox(height: 12),
                        _Picker(
                          label: 'Payment',
                          value: '${order['payment_status'] ?? ''}',
                          options: _paymentStatuses,
                          onChanged: (v) =>
                              _patch({'payment_status': v}, 'Payment updated'),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 14),

                  SectionCard(
                    title: 'Items (${items.length})',
                    child: items.isEmpty
                        ? const Text('No items on this order.',
                            style: TextStyle(color: Brand.muted))
                        : Column(
                            children: items
                                .map((it) => Padding(
                                      padding:
                                          const EdgeInsets.symmetric(vertical: 6),
                                      child: Row(
                                        children: [
                                          Expanded(
                                            child: Text(
                                              '${it['product_name'] ?? 'Item'}',
                                              style: const TextStyle(fontSize: 13.5),
                                            ),
                                          ),
                                          Text('×${it['quantity'] ?? 1}',
                                              style: const TextStyle(
                                                  color: Brand.muted,
                                                  fontSize: 13)),
                                          const SizedBox(width: 12),
                                          Text(money(it['price']),
                                              style: const TextStyle(
                                                  fontWeight: FontWeight.w700,
                                                  fontSize: 13.5)),
                                        ],
                                      ),
                                    ))
                                .toList(),
                          ),
                  ),
                  const SizedBox(height: 14),

                  _NotesCard(
                    initial: '${order['notes'] ?? ''}',
                    onSave: (text) => _patch({'notes': text}, 'Notes saved'),
                  ),
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}

class _Picker extends StatelessWidget {
  const _Picker({
    required this.label,
    required this.value,
    required this.options,
    required this.onChanged,
  });
  final String label;
  final String value;
  final Map<String, String> options;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    // An unknown value (an enum grew server-side) would make the dropdown throw,
    // so it falls back to no selection rather than crashing the screen.
    final current = options.containsKey(value) ? value : null;
    return DropdownButtonFormField<String>(
      initialValue: current,
      decoration: InputDecoration(labelText: label),
      items: options.entries
          .map((e) => DropdownMenuItem(value: e.key, child: Text(e.value)))
          .toList(),
      onChanged: (v) { if (v != null && v != value) onChanged(v); },
    );
  }
}

class _NotesCard extends StatefulWidget {
  const _NotesCard({required this.initial, required this.onSave});
  final String initial;
  final ValueChanged<String> onSave;
  @override
  State<_NotesCard> createState() => _NotesCardState();
}

class _NotesCardState extends State<_NotesCard> {
  late final TextEditingController _c = TextEditingController(text: widget.initial);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SectionCard(
      title: 'Notes',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          TextField(
            controller: _c,
            maxLines: 4,
            decoration: const InputDecoration(
                hintText: 'Internal notes about this order…'),
          ),
          const SizedBox(height: 10),
          FilledButton(
            onPressed: () => widget.onSave(_c.text),
            child: const Text('Save notes'),
          ),
        ],
      ),
    );
  }
}
