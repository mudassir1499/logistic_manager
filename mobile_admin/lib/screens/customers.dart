import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api.dart';
import '../theme.dart';
import '../widgets.dart';
import 'ledger.dart';

/// Customers: find one, call or WhatsApp them, see their balance, edit or add.
///
/// Tap-to-call is the reason this screen earns a tab. Looking a customer up on
/// a laptop and then typing their number into a phone is the single most common
/// thing this app removes.
class CustomersScreen extends StatefulWidget {
  const CustomersScreen({super.key});
  @override
  State<CustomersScreen> createState() => _CustomersScreenState();
}

class _CustomersScreenState extends State<CustomersScreen> {
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
    _future = Api.instance.customers(
        search: _search.text.trim().isEmpty ? null : _search.text.trim());
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Customers')),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: Brand.ink,
        foregroundColor: Colors.white,
        onPressed: () async {
          final saved = await Navigator.push<bool>(context,
              MaterialPageRoute(builder: (_) => const CustomerEditScreen()));
          if (saved == true) _load();
        },
        icon: const Icon(Icons.person_add_alt),
        label: const Text('New'),
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
                hintText: 'Search name, phone or email…',
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
                emptyIcon: Icons.people_outline,
                emptyText: 'No customers match.',
                isEmpty: (d) => d.isEmpty,
                builder: (rows) => RefreshIndicator(
                  onRefresh: () async => _load(),
                  child: ListView.separated(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 88),
                    itemCount: rows.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (_, i) {
                      final c = rows[i];
                      return Card(
                        child: ListTile(
                          leading: CircleAvatar(
                            backgroundColor: Brand.gold.withValues(alpha: 0.18),
                            child: Text(
                              '${c['name'] ?? '?'}'.characters.first.toUpperCase(),
                              style: const TextStyle(
                                  color: Brand.goldText,
                                  fontWeight: FontWeight.w800),
                            ),
                          ),
                          title: Text('${c['name'] ?? ''}',
                              style: const TextStyle(fontWeight: FontWeight.w600)),
                          subtitle: Text(
                            [c['phone'], c['email']]
                                .where((v) => (v ?? '').toString().isNotEmpty)
                                .join('  ·  '),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                          trailing: const Icon(Icons.chevron_right,
                              color: Brand.muted),
                          onTap: () async {
                            await Navigator.push(
                                context,
                                MaterialPageRoute(
                                    builder: (_) => CustomerDetailScreen(customer: c)));
                            _load();
                          },
                        ),
                      );
                    },
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

class CustomerDetailScreen extends StatefulWidget {
  const CustomerDetailScreen({super.key, required this.customer});
  final Map<String, dynamic> customer;
  @override
  State<CustomerDetailScreen> createState() => _CustomerDetailScreenState();
}

class _CustomerDetailScreenState extends State<CustomerDetailScreen> {
  late Map<String, dynamic> c = widget.customer;

  Future<void> _open(Uri uri, String failure) async {
    // canLaunchUrl is checked because a tablet with no dialler returns false
    // rather than throwing, and a button that silently does nothing is the
    // worst outcome.
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    } else if (mounted) {
      toast(context, failure, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final phone = '${c['phone'] ?? ''}'.replaceAll(RegExp(r'[^0-9+]'), '');
    final email = '${c['email'] ?? ''}';
    return Scaffold(
      appBar: AppBar(
        title: Text('${c['name'] ?? 'Customer'}'),
        actions: [
          IconButton(
            icon: const Icon(Icons.edit_outlined),
            onPressed: () async {
              final saved = await Navigator.push<bool>(
                  context,
                  MaterialPageRoute(
                      builder: (_) => CustomerEditScreen(customer: c)));
              if (saved == true && mounted) Navigator.pop(context);
            },
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (phone.isNotEmpty)
            Row(
              children: [
                Expanded(
                  child: FilledButton.icon(
                    onPressed: () => _open(Uri.parse('tel:$phone'),
                        'No dialler on this device.'),
                    icon: const Icon(Icons.call),
                    label: const Text('Call'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: FilledButton.icon(
                    style: FilledButton.styleFrom(backgroundColor: Brand.ok),
                    onPressed: () => _open(
                        Uri.parse('https://wa.me/${phone.replaceAll('+', '')}'),
                        'WhatsApp is not installed.'),
                    icon: const Icon(Icons.chat),
                    label: const Text('WhatsApp'),
                  ),
                ),
              ],
            ),
          const SizedBox(height: 14),
          SectionCard(
            title: 'Contact',
            child: Column(
              children: [
                DetailRow('Phone', phone),
                DetailRow('Email', email),
                DetailRow('Address', '${c['address'] ?? ''}'),
                DetailRow('Status', null,
                    valueWidget: StatusChip(
                        c['is_active'] == false ? 'Inactive' : 'Active',
                        colour: c['is_active'] == false ? Brand.muted : Brand.ok)),
                DetailRow('Since', prettyDate(c['created_at'] as String?)),
              ],
            ),
          ),
          const SizedBox(height: 14),
          Card(
            child: ListTile(
              leading: const Icon(Icons.account_balance_wallet_outlined,
                  color: Brand.goldText),
              title: const Text('Ledger',
                  style: TextStyle(fontWeight: FontWeight.w600)),
              subtitle: const Text('Balance and payments',
                  style: TextStyle(fontSize: 12.5)),
              trailing: const Icon(Icons.chevron_right, color: Brand.muted),
              onTap: () => Navigator.push(
                  context,
                  MaterialPageRoute(
                      builder: (_) => LedgerScreen(
                            customerId: c['id'] as int?,
                            customerName: '${c['name'] ?? ''}',
                          ))),
            ),
          ),
        ],
      ),
    );
  }
}

/// Create or edit. One screen for both — the only difference is whether an id
/// is sent, and duplicating the form would guarantee the two drift.
class CustomerEditScreen extends StatefulWidget {
  const CustomerEditScreen({super.key, this.customer});
  final Map<String, dynamic>? customer;
  @override
  State<CustomerEditScreen> createState() => _CustomerEditScreenState();
}

class _CustomerEditScreenState extends State<CustomerEditScreen> {
  late final _name = TextEditingController(text: '${widget.customer?['name'] ?? ''}');
  late final _phone = TextEditingController(text: '${widget.customer?['phone'] ?? ''}');
  late final _email = TextEditingController(text: '${widget.customer?['email'] ?? ''}');
  late final _address = TextEditingController(text: '${widget.customer?['address'] ?? ''}');
  late bool _active = widget.customer?['is_active'] != false;
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    _email.dispose();
    _address.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_name.text.trim().isEmpty) {
      toast(context, 'A customer needs a name.', error: true);
      return;
    }
    setState(() => _busy = true);
    final ok = await runWrite(
      context,
      () => Api.instance.saveCustomer({
        'name': _name.text.trim(),
        'phone': _phone.text.trim(),
        'email': _email.text.trim(),
        'address': _address.text.trim(),
        'is_active': _active,
      }, id: widget.customer?['id'] as int?),
      success: widget.customer == null ? 'Customer added' : 'Customer updated',
    );
    if (mounted) setState(() => _busy = false);
    if (ok && mounted) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
          title: Text(widget.customer == null ? 'New customer' : 'Edit customer')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
              controller: _name,
              decoration: const InputDecoration(labelText: 'Name')),
          const SizedBox(height: 12),
          TextField(
              controller: _phone,
              keyboardType: TextInputType.phone,
              decoration: const InputDecoration(
                  labelText: 'Phone', hintText: '+971 50 123 4567')),
          const SizedBox(height: 12),
          TextField(
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              autocorrect: false,
              decoration: const InputDecoration(labelText: 'Email')),
          const SizedBox(height: 12),
          TextField(
              controller: _address,
              maxLines: 3,
              decoration: const InputDecoration(labelText: 'Address')),
          const SizedBox(height: 4),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Active'),
            value: _active,
            onChanged: (v) => setState(() => _active = v),
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _busy ? null : _save,
            child: Text(_busy ? 'Saving…' : 'Save'),
          ),
        ],
      ),
    );
  }
}
