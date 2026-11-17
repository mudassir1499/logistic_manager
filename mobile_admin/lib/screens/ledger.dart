import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../widgets.dart';

/// Khata: what a customer owes, and recording a payment against it.
///
/// Opens either as the whole ledger (from More) or scoped to one customer
/// (from their detail screen). Scoped is the useful case — "how much does this
/// person owe me" is the question actually asked, usually while standing in
/// front of them.
class LedgerScreen extends StatefulWidget {
  const LedgerScreen({super.key, this.customerId, this.customerName});
  final int? customerId;
  final String? customerName;

  @override
  State<LedgerScreen> createState() => _LedgerScreenState();
}

class _LedgerScreenState extends State<LedgerScreen> {
  late Future<List<Map<String, dynamic>>> _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() => setState(
      () => _future = Api.instance.ledger(customerId: widget.customerId));

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.customerName ?? 'Khata')),
      floatingActionButton: widget.customerId == null
          // Adding an entry needs a customer, and choosing one from a list of
          // hundreds on a phone is a worse flow than opening the customer first.
          ? null
          : FloatingActionButton.extended(
              backgroundColor: Brand.ink,
              foregroundColor: Colors.white,
              onPressed: () async {
                final added = await showModalBottomSheet<bool>(
                  context: context,
                  isScrollControlled: true,
                  builder: (_) => _AddEntrySheet(customerId: widget.customerId!),
                );
                if (added == true) _load();
              },
              icon: const Icon(Icons.add),
              label: const Text('Entry'),
            ),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _future,
        builder: (context, snap) => AsyncBody(
          snapshot: snap,
          onRetry: _load,
          emptyIcon: Icons.account_balance_wallet_outlined,
          emptyText: 'No ledger entries yet.',
          isEmpty: (d) => d.isEmpty,
          builder: (rows) {
            // Computed here rather than requested: the endpoint returns entries,
            // and one more round trip for a subtraction the client can do is a
            // second chance to be slow on a bad connection.
            double credit = 0, debit = 0;
            for (final r in rows) {
              final amount = double.tryParse('${r['amount']}') ?? 0;
              if (r['entry_type'] == 'credit') {
                credit += amount;
              } else {
                debit += amount;
              }
            }
            final outstanding = debit - credit;

            return RefreshIndicator(
              onRefresh: () async => _load(),
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 88),
                children: [
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        children: [
                          Text('Outstanding',
                              style: TextStyle(
                                  color: Brand.muted, fontSize: 12.5)),
                          const SizedBox(height: 4),
                          Text(
                            money(outstanding),
                            style: TextStyle(
                              fontSize: 30,
                              fontWeight: FontWeight.w800,
                              // Owing money and being in credit are opposite
                              // facts; colour carries it but so does the sign.
                              color: outstanding > 0 ? Brand.danger : Brand.ok,
                            ),
                          ),
                          const SizedBox(height: 12),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                            children: [
                              _Total('Debited', debit, Brand.warn),
                              _Total('Credited', credit, Brand.ok),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 14),
                  ...rows.map((r) {
                    final isCredit = r['entry_type'] == 'credit';
                    return Card(
                      margin: const EdgeInsets.only(bottom: 8),
                      child: ListTile(
                        leading: Icon(
                          isCredit ? Icons.south_west : Icons.north_east,
                          color: isCredit ? Brand.ok : Brand.warn,
                        ),
                        title: Text(
                          money(r['amount'], '${r['currency'] ?? ''}'),
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        subtitle: Text(
                          [
                            if (widget.customerId == null) '${r['customer_name'] ?? ''}',
                            prettyDate(r['date'] as String?),
                            if ((r['description'] ?? '').toString().isNotEmpty)
                              '${r['description']}',
                          ].where((s) => s.isNotEmpty).join('  ·  '),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                        trailing: StatusChip(isCredit ? 'Credit' : 'Debit',
                            colour: isCredit ? Brand.ok : Brand.warn),
                      ),
                    );
                  }),
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}

class _Total extends StatelessWidget {
  const _Total(this.label, this.value, this.colour);
  final String label;
  final double value;
  final Color colour;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(money(value),
            style: TextStyle(
                fontSize: 16, fontWeight: FontWeight.w700, color: colour)),
        Text(label, style: const TextStyle(fontSize: 11.5, color: Brand.muted)),
      ],
    );
  }
}

class _AddEntrySheet extends StatefulWidget {
  const _AddEntrySheet({required this.customerId});
  final int customerId;
  @override
  State<_AddEntrySheet> createState() => _AddEntrySheetState();
}

class _AddEntrySheetState extends State<_AddEntrySheet> {
  final _amount = TextEditingController();
  final _description = TextEditingController();
  // Credit by default: the overwhelmingly common reason to open this on a
  // phone is that somebody has just paid you.
  String _type = 'credit';
  bool _busy = false;

  @override
  void dispose() {
    _amount.dispose();
    _description.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final amount = double.tryParse(_amount.text.trim());
    if (amount == null || amount <= 0) {
      toast(context, 'Enter an amount greater than zero.', error: true);
      return;
    }
    setState(() => _busy = true);
    final ok = await runWrite(
      context,
      () => Api.instance.addLedgerEntry({
        'customer': widget.customerId,
        'entry_type': _type,
        'amount': amount.toStringAsFixed(2),
        'description': _description.text.trim(),
      }),
      success: 'Entry recorded',
    );
    if (mounted) setState(() => _busy = false);
    if (ok && mounted) Navigator.pop(context, true);
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
          const Text('Record an entry',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          const SizedBox(height: 16),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(
                  value: 'credit',
                  label: Text('Payment in'),
                  icon: Icon(Icons.south_west)),
              ButtonSegment(
                  value: 'debit',
                  label: Text('Charge'),
                  icon: Icon(Icons.north_east)),
            ],
            selected: {_type},
            onSelectionChanged: (s) => setState(() => _type = s.first),
          ),
          const SizedBox(height: 14),
          TextField(
            controller: _amount,
            autofocus: true,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'Amount'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _description,
            decoration: const InputDecoration(
                labelText: 'Note', hintText: 'What was this for?'),
          ),
          const SizedBox(height: 18),
          FilledButton(
            onPressed: _busy ? null : _save,
            child: Text(_busy ? 'Saving…' : 'Record'),
          ),
        ],
      ),
    );
  }
}
