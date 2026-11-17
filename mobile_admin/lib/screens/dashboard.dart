import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../widgets.dart';

/// The home screen: one request, every module the signer-in can see.
///
/// The figures are chosen to answer "is there anything waiting for me", not
/// "how big is the business". A count that never reaches zero stops being read
/// within a week, so totals are secondary and the queue numbers lead.
class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late Future<Map<String, dynamic>> _future;

  @override
  void initState() {
    super.initState();
    _future = Api.instance.dashboard();
  }

  void _reload() => setState(() => _future = Api.instance.dashboard());

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Back Office'),
        actions: [
          IconButton(onPressed: _reload, icon: const Icon(Icons.refresh)),
        ],
      ),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, snap) => AsyncBody(
          snapshot: snap,
          onRetry: _reload,
          builder: (data) => RefreshIndicator(
            onRefresh: () async => _reload(),
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _Greeting(data['user'] as Map? ?? const {}),
                const SizedBox(height: 18),

                if (data['orders'] != null)
                  _Block(
                    title: 'Orders',
                    icon: Icons.receipt_long,
                    stats: [
                      _Stat('Awaiting action', data['orders']['awaiting_action'],
                          highlight: true),
                      _Stat('This week', data['orders']['this_week']),
                      _Stat('Delivered', data['orders']['delivered']),
                      _Stat('Total', data['orders']['total']),
                    ],
                  ),

                if (data['products'] != null)
                  _Block(
                    title: 'Catalogue',
                    icon: Icons.inventory_2,
                    stats: [
                      // Surfaced here because it is invisible everywhere else:
                      // a product with no photo looks fine on every list and is
                      // silently absent from every catalogue ad.
                      _Stat('No photo', data['products']['missing_photo'],
                          highlight: true),
                      _Stat('Drafts', data['products']['drafts']),
                      _Stat('Public', data['products']['public']),
                      _Stat('Total', data['products']['total']),
                    ],
                  ),

                if (data['support'] != null)
                  _Block(
                    title: 'Support',
                    icon: Icons.support_agent,
                    stats: [
                      _Stat('Open tickets', data['support']['open'],
                          highlight: true),
                      _Stat('Total', data['support']['total']),
                    ],
                  ),

                if (data['customers'] != null)
                  _Block(
                    title: 'Customers',
                    icon: Icons.people,
                    stats: [
                      _Stat('New this week', data['customers']['new_this_week']),
                      _Stat('Total', data['customers']['total']),
                    ],
                  ),

                if (data['ledger'] != null)
                  _Block(
                    title: 'Khata',
                    icon: Icons.account_balance_wallet,
                    stats: [
                      _Stat('Outstanding', data['ledger']['outstanding'],
                          highlight: true, isMoney: true),
                      _Stat('Credited', data['ledger']['credit'], isMoney: true),
                      _Stat('Debited', data['ledger']['debit'], isMoney: true),
                    ],
                  ),

                const SizedBox(height: 8),
                Text('Updated ${TimeOfDay.now().format(context)}',
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: Brand.muted, fontSize: 11.5)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Greeting extends StatelessWidget {
  const _Greeting(this.user);
  final Map user;

  @override
  Widget build(BuildContext context) {
    final hour = DateTime.now().hour;
    final part = hour < 12 ? 'Good morning' : (hour < 18 ? 'Good afternoon' : 'Good evening');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(part, style: const TextStyle(color: Brand.muted, fontSize: 13)),
        Text(
          '${user['name'] ?? ''}',
          style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
        ),
      ],
    );
  }
}

class _Stat {
  _Stat(this.label, this.value, {this.highlight = false, this.isMoney = false});
  final String label;
  final dynamic value;
  final bool highlight;
  final bool isMoney;
}

class _Block extends StatelessWidget {
  const _Block({required this.title, required this.icon, required this.stats});
  final String title;
  final IconData icon;
  final List<_Stat> stats;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: SectionCard(
        title: title,
        trailing: Icon(icon, size: 18, color: Brand.goldText),
        child: Wrap(
          spacing: 10,
          runSpacing: 12,
          children: stats.map((s) {
            final text = s.isMoney ? money(s.value) : '${s.value ?? 0}';
            // A highlighted figure only turns amber when it is non-zero.
            // Colouring "0 awaiting action" red says there is a problem when
            // the truth is the opposite.
            final n = double.tryParse('${s.value ?? 0}') ?? 0;
            final hot = s.highlight && n > 0;
            return SizedBox(
              width: (MediaQuery.of(context).size.width - 32 - 32 - 10) / 2,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    text,
                    style: TextStyle(
                      fontSize: 24,
                      fontWeight: FontWeight.w800,
                      color: hot ? Brand.warn : Brand.ink,
                    ),
                  ),
                  Text(s.label,
                      style: const TextStyle(fontSize: 12, color: Brand.muted)),
                ],
              ),
            );
          }).toList(),
        ),
      ),
    );
  }
}
