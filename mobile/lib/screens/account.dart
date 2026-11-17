import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../widgets/common.dart';
import 'orders.dart' show prettyDate, statusColour;

/// Profile, ledger balance and support tickets.
class AccountScreen extends StatefulWidget {
  const AccountScreen({super.key, required this.app});

  final AppState app;

  @override
  State<AccountScreen> createState() => AccountScreenState();
}

class AccountScreenState extends State<AccountScreen> {
  @override
  Widget build(BuildContext context) {
    final me = widget.app.me;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(children: [
          CircleAvatar(
            radius: 26,
            backgroundColor: Brand.gold.withValues(alpha: 0.15),
            child: Text(
              (me?.displayName ?? '?').characters.first.toUpperCase(),
              style: const TextStyle(
                  fontSize: 22, fontWeight: FontWeight.w800, color: Brand.goldDark),
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(me?.displayName ?? '—',
                    style: const TextStyle(
                        fontSize: 17, fontWeight: FontWeight.w800)),
                if ((me?.email ?? '').isNotEmpty)
                  Text(me!.email,
                      style: const TextStyle(color: Brand.muted, fontSize: 13)),
              ],
            ),
          ),
        ]),
        const SizedBox(height: 22),

        _tile(
          icon: Icons.account_balance_wallet_outlined,
          title: 'Account ledger',
          subtitle: 'Your balance and transactions',
          onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => LedgerScreen(app: widget.app))),
        ),
        _tile(
          icon: Icons.support_agent_outlined,
          title: 'Support',
          subtitle: 'Ask a question or track a ticket',
          onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => TicketsScreen(app: widget.app))),
        ),
        _tile(
          icon: Icons.person_outline,
          title: 'Your details',
          subtitle: 'Name, phone and address',
          onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => ProfileScreen(app: widget.app))),
        ),

        const SizedBox(height: 24),
        OutlinedButton.icon(
          onPressed: () async {
            final confirmed = await showDialog<bool>(
              context: context,
              builder: (context) => AlertDialog(
                title: const Text('Sign out?'),
                content: const Text(
                    'You will need your password to sign in again on this device.'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('Cancel')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('Sign out')),
                ],
              ),
            );
            if (confirmed == true) await widget.app.signOut();
          },
          icon: const Icon(Icons.logout, color: Brand.danger),
          label: const Text('Sign out', style: TextStyle(color: Brand.danger)),
          style: OutlinedButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 14)),
        ),
      ],
    );
  }

  Widget _tile({
    required IconData icon,
    required String title,
    required String subtitle,
    required VoidCallback onTap,
  }) {
    return Card(
      elevation: 0,
      margin: const EdgeInsets.only(bottom: 10),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: Color(0xFFE4E5E9)),
      ),
      child: ListTile(
        leading: Icon(icon, color: Brand.goldDark),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
        subtitle: Text(subtitle, style: const TextStyle(fontSize: 12)),
        trailing: const Icon(Icons.chevron_right, color: Brand.muted),
        onTap: onTap,
      ),
    );
  }
}

/// The customer's own ledger: entries and a per-currency balance.
class LedgerScreen extends StatefulWidget {
  const LedgerScreen({super.key, required this.app});

  final AppState app;

  @override
  State<LedgerScreen> createState() => _LedgerScreenState();
}

class _LedgerScreenState extends State<LedgerScreen> {
  AsyncValue<List<LedgerEntry>> _state = const AsyncValue.loading();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _state = const AsyncValue.loading());
    try {
      final data = await widget.app.api.get('/ledger/', query: {'page_size': 100});
      final page = ApiPage.fromJson(data as Map<String, dynamic>, LedgerEntry.fromJson);
      if (!mounted) return;
      setState(() => _state = AsyncValue.data(page.results));
    } catch (error) {
      if (!mounted) return;
      setState(() => _state = AsyncValue.failure(error.toString()));
    }
  }

  /// Balance per currency, as a string, without floating-point arithmetic.
  ///
  /// Amounts are decimal strings with two places, so they are summed in the
  /// smallest unit as integers and formatted back. Parsing to double and adding
  /// would drift by a cent on a long ledger, which on a balance is the one
  /// place it will be noticed.
  Map<String, int> _balancesInCents(List<LedgerEntry> entries) {
    final totals = <String, int>{};
    for (final entry in entries) {
      final cents = _toCents(entry.amount);
      totals.update(
        entry.currency,
        (value) => value + (entry.isCredit ? cents : -cents),
        ifAbsent: () => entry.isCredit ? cents : -cents,
      );
    }
    return totals;
  }

  int _toCents(String amount) {
    final parts = amount.split('.');
    final whole = int.tryParse(parts[0].replaceAll(RegExp(r'[^\d-]'), '')) ?? 0;
    var fraction = 0;
    if (parts.length > 1) {
      final digits = parts[1].padRight(2, '0').substring(0, 2);
      fraction = int.tryParse(digits) ?? 0;
    }
    final sign = whole < 0 ? -1 : 1;
    return whole * 100 + sign * fraction;
  }

  String _fromCents(int cents) {
    final negative = cents < 0;
    final value = cents.abs();
    return '${negative ? '-' : ''}${value ~/ 100}.'
        '${(value % 100).toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Account ledger')),
      body: AsyncView<List<LedgerEntry>>(
        state: _state,
        onRetry: _load,
        emptyMessage: 'No ledger entries yet.',
        emptyIcon: Icons.account_balance_wallet_outlined,
        isEmpty: (entries) => entries.isEmpty,
        builder: (entries) {
          final balances = _balancesInCents(entries);
          return RefreshIndicator(
            onRefresh: _load,
            child: ListView(
              padding: const EdgeInsets.all(12),
              children: [
                for (final currency in balances.keys)
                  Container(
                    margin: const EdgeInsets.only(bottom: 10),
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: Brand.ink,
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text('Balance ($currency)',
                            style: const TextStyle(color: Colors.white70)),
                        Text(
                          '$currency ${_fromCents(balances[currency]!)}',
                          style: TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w800,
                            color: balances[currency]! >= 0
                                ? const Color(0xFF6EE7A8)
                                : const Color(0xFFFFA39E),
                          ),
                        ),
                      ],
                    ),
                  ),
                const SizedBox(height: 6),
                const Padding(
                  padding: EdgeInsets.only(left: 4, bottom: 8),
                  child: Text(
                    'A positive balance is credit with us; negative is owing.',
                    style: TextStyle(fontSize: 11.5, color: Brand.muted),
                  ),
                ),
                ...entries.map((entry) => ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: Icon(
                        entry.isCredit
                            ? Icons.arrow_downward_rounded
                            : Icons.arrow_upward_rounded,
                        color: entry.isCredit ? Brand.success : Brand.danger,
                      ),
                      title: Text(
                        entry.description.isEmpty
                            ? (entry.isCredit ? 'Payment received' : 'Charge')
                            : entry.description,
                        style: const TextStyle(fontSize: 14),
                      ),
                      subtitle: Text(prettyDate(entry.date),
                          style: const TextStyle(fontSize: 12)),
                      trailing: Text(
                        '${entry.isCredit ? '+' : '−'}${entry.currency} ${entry.amount}',
                        style: TextStyle(
                          fontWeight: FontWeight.w700,
                          color: entry.isCredit ? Brand.success : Brand.danger,
                        ),
                      ),
                    )),
              ],
            ),
          );
        },
      ),
    );
  }
}

class TicketsScreen extends StatefulWidget {
  const TicketsScreen({super.key, required this.app});

  final AppState app;

  @override
  State<TicketsScreen> createState() => _TicketsScreenState();
}

class _TicketsScreenState extends State<TicketsScreen> {
  AsyncValue<List<Ticket>> _state = const AsyncValue.loading();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _state = const AsyncValue.loading());
    try {
      final data = await widget.app.api.get('/tickets/', query: {'page_size': 50});
      final page = ApiPage.fromJson(data as Map<String, dynamic>, Ticket.fromJson);
      if (!mounted) return;
      setState(() => _state = AsyncValue.data(page.results));
    } catch (error) {
      if (!mounted) return;
      setState(() => _state = AsyncValue.failure(error.toString()));
    }
  }

  Future<void> _newTicket() async {
    final subject = TextEditingController();
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('New support ticket'),
        content: TextField(
          controller: subject,
          autofocus: true,
          decoration: const InputDecoration(
            labelText: 'What do you need help with?',
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Create')),
        ],
      ),
    );
    if (created != true || subject.text.trim().isEmpty) return;

    try {
      await widget.app.api.post('/tickets/', body: {
        'subject': subject.text.trim(),
        'category': 'general',
        'priority': 'normal',
        'status': 'open',
      });
      await _load();
      if (mounted) showMessage(context, 'Ticket created');
    } catch (error) {
      if (mounted) showApiError(context, error, widget.app);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Support')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _newTicket,
        backgroundColor: Brand.ink,
        icon: const Icon(Icons.add, color: Colors.white),
        label: const Text('New ticket', style: TextStyle(color: Colors.white)),
      ),
      body: AsyncView<List<Ticket>>(
        state: _state,
        onRetry: _load,
        emptyMessage: 'No support tickets.\nTap "New ticket" to ask us something.',
        emptyIcon: Icons.support_agent_outlined,
        isEmpty: (tickets) => tickets.isEmpty,
        builder: (tickets) => RefreshIndicator(
          onRefresh: _load,
          child: ListView.builder(
            padding: const EdgeInsets.all(12),
            itemCount: tickets.length,
            itemBuilder: (_, i) {
              final ticket = tickets[i];
              return Card(
                elevation: 0,
                margin: const EdgeInsets.only(bottom: 10),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                  side: const BorderSide(color: Color(0xFFE4E5E9)),
                ),
                child: ListTile(
                  title: Text(ticket.subject,
                      style: const TextStyle(fontWeight: FontWeight.w700)),
                  subtitle: Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Wrap(spacing: 6, children: [
                      StatusChip(ticket.status, colour: statusColour(ticket.status)),
                      StatusChip(ticket.priority),
                    ]),
                  ),
                ),
              );
            },
          ),
        ),
      ),
    );
  }
}

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key, required this.app});

  final AppState app;

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  late final TextEditingController _name;
  late final TextEditingController _phone;
  late final TextEditingController _address;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    final me = widget.app.me;
    _name = TextEditingController(text: me?.customerName ?? '');
    _phone = TextEditingController(text: me?.phone ?? '');
    _address = TextEditingController(text: me?.address ?? '');
  }

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    _address.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await widget.app.api.patch('/me/', body: {
        'name': _name.text.trim(),
        'phone': _phone.text.trim(),
        'address': _address.text.trim(),
      });
      await widget.app.refreshMe();
      if (mounted) showMessage(context, 'Saved');
    } catch (error) {
      if (mounted) showApiError(context, error, widget.app);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Your details')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _name,
            decoration: const InputDecoration(labelText: 'Name or company'),
          ),
          const SizedBox(height: 14),
          TextField(
            controller: _phone,
            keyboardType: TextInputType.phone,
            decoration: const InputDecoration(
              labelText: 'Phone',
              helperText: 'Used to reach you about orders',
            ),
          ),
          const SizedBox(height: 14),
          TextField(
            controller: _address,
            maxLines: 3,
            decoration: const InputDecoration(labelText: 'Delivery address'),
          ),
          const SizedBox(height: 22),
          FilledButton(
            onPressed: _saving ? null : _save,
            style: FilledButton.styleFrom(
              backgroundColor: Brand.ink,
              padding: const EdgeInsets.symmetric(vertical: 15),
            ),
            child: Text(_saving ? 'Saving…' : 'Save changes'),
          ),
          const SizedBox(height: 12),
          const Text(
            'Your email address is how you sign in and cannot be changed here. '
            'Contact support if you need it updated.',
            style: TextStyle(fontSize: 12, color: Brand.muted),
          ),
        ],
      ),
    );
  }
}
