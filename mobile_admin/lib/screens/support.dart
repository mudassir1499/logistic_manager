import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../widgets.dart';

/// Support tickets, and the sourcing enquiries that come off the website.
///
/// Both are inbound demand waiting on a reply, which is the one kind of work
/// where answering from a phone genuinely beats waiting to be at a desk.

class SupportScreen extends StatefulWidget {
  const SupportScreen({super.key});
  @override
  State<SupportScreen> createState() => _SupportScreenState();
}

class _SupportScreenState extends State<SupportScreen> {
  late Future<List<Map<String, dynamic>>> _future;
  String? _status = 'open';

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() =>
      setState(() => _future = Api.instance.tickets(status: _status));

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Support')),
      body: Column(
        children: [
          SizedBox(
            height: 52,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              children: [
                _chip('Open', 'open'),
                _chip('Closed', 'closed'),
                _chip('All', null),
              ],
            ),
          ),
          Expanded(
            child: FutureBuilder<List<Map<String, dynamic>>>(
              future: _future,
              builder: (context, snap) => AsyncBody(
                snapshot: snap,
                onRetry: _load,
                emptyIcon: Icons.support_agent_outlined,
                emptyText: 'No tickets here.',
                isEmpty: (d) => d.isEmpty,
                builder: (rows) => RefreshIndicator(
                  onRefresh: () async => _load(),
                  child: ListView.separated(
                    padding: const EdgeInsets.all(12),
                    itemCount: rows.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (_, i) {
                      final t = rows[i];
                      return Card(
                        child: ListTile(
                          title: Text('${t['subject'] ?? 'Ticket'}',
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                  fontWeight: FontWeight.w600, fontSize: 14)),
                          subtitle: Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(
                              '#${t['id']}  ·  ${prettyDate(t['created_at'] as String?)}',
                              style: const TextStyle(fontSize: 12),
                            ),
                          ),
                          trailing: StatusChip('${t['status'] ?? ''}'),
                          onTap: () async {
                            await Navigator.push(
                                context,
                                MaterialPageRoute(
                                    builder: (_) =>
                                        TicketDetailScreen(id: t['id'] as int)));
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

  Widget _chip(String label, String? value) => Padding(
        padding: const EdgeInsets.only(right: 8),
        child: ChoiceChip(
          label: Text(label),
          selected: _status == value,
          onSelected: (_) { _status = value; _load(); },
        ),
      );
}

class TicketDetailScreen extends StatefulWidget {
  const TicketDetailScreen({super.key, required this.id});
  final int id;
  @override
  State<TicketDetailScreen> createState() => _TicketDetailScreenState();
}

class _TicketDetailScreenState extends State<TicketDetailScreen> {
  late Future<Map<String, dynamic>> _future;
  final _reply = TextEditingController();
  bool _internal = false;
  bool _sending = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _reply.dispose();
    super.dispose();
  }

  void _load() => setState(() => _future = Api.instance.ticket(widget.id));

  Future<void> _send() async {
    if (_reply.text.trim().isEmpty) return;
    setState(() => _sending = true);
    final ok = await runWrite(
      context,
      () => Api.instance
          .replyToTicket(widget.id, _reply.text.trim(), internal: _internal),
      success: _internal ? 'Note added' : 'Reply sent',
    );
    if (mounted) setState(() => _sending = false);
    if (ok) {
      _reply.clear();
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Ticket #${widget.id}'),
        actions: [
          PopupMenuButton<String>(
            onSelected: (v) async {
              final ok = await runWrite(context,
                  () => Api.instance.updateTicket(widget.id, {'status': v}),
                  success: 'Ticket $v');
              if (ok) _load();
            },
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'closed', child: Text('Close ticket')),
              PopupMenuItem(value: 'open', child: Text('Reopen ticket')),
            ],
          ),
        ],
      ),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, snap) => AsyncBody(
          snapshot: snap,
          onRetry: _load,
          builder: (t) {
            final messages = List<Map<String, dynamic>>.from(
                (t['messages'] as List?) ?? const []);
            return Column(
              children: [
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      SectionCard(
                        title: '${t['subject'] ?? ''}',
                        trailing: StatusChip('${t['status'] ?? ''}'),
                        child: Column(
                          children: [
                            DetailRow('Opened', prettyDate(t['created_at'] as String?)),
                            DetailRow('Priority', '${t['priority'] ?? ''}'),
                            DetailRow('Category', '${t['category'] ?? ''}'),
                          ],
                        ),
                      ),
                      const SizedBox(height: 14),
                      if ((t['description'] ?? '').toString().isNotEmpty)
                        SectionCard(
                          title: 'Request',
                          child: Text('${t['description']}',
                              style: const TextStyle(fontSize: 14, height: 1.5)),
                        ),
                      const SizedBox(height: 14),
                      ...messages.map((m) => _Message(m)),
                    ],
                  ),
                ),
                _Composer(
                  controller: _reply,
                  internal: _internal,
                  sending: _sending,
                  onInternal: (v) => setState(() => _internal = v),
                  onSend: _send,
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _Message extends StatelessWidget {
  const _Message(this.m);
  final Map<String, dynamic> m;

  @override
  Widget build(BuildContext context) {
    final internal = m['is_internal'] == true;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        // An internal note is the desk talking to itself. It must look
        // unmistakably different from something the customer can read.
        color: internal ? Brand.gold.withValues(alpha: 0.10) : Brand.card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
            color: internal
                ? Brand.gold.withValues(alpha: 0.4)
                : Brand.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              if (internal) ...[
                const Icon(Icons.lock_outline, size: 12, color: Brand.goldText),
                const SizedBox(width: 4),
                const Text('Internal note',
                    style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: Brand.goldText)),
                const SizedBox(width: 8),
              ],
              Expanded(
                child: Text(prettyDate(m['created_at'] as String?),
                    style: const TextStyle(fontSize: 11, color: Brand.muted)),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text('${m['body'] ?? ''}',
              style: const TextStyle(fontSize: 13.5, height: 1.45)),
        ],
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.internal,
    required this.sending,
    required this.onInternal,
    required this.onSend,
  });
  final TextEditingController controller;
  final bool internal;
  final bool sending;
  final ValueChanged<bool> onInternal;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.only(
        left: 12, right: 12, top: 10,
        bottom: MediaQuery.of(context).viewInsets.bottom + 12,
      ),
      decoration: const BoxDecoration(
        color: Brand.card,
        border: Border(top: BorderSide(color: Brand.border)),
      ),
      child: Column(
        children: [
          Row(
            children: [
              Switch(value: internal, onChanged: onInternal),
              const Expanded(
                child: Text('Internal note — the customer will not see this',
                    style: TextStyle(fontSize: 12, color: Brand.muted)),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(
                child: TextField(
                  controller: controller,
                  maxLines: 4,
                  minLines: 1,
                  decoration: InputDecoration(
                    hintText: internal ? 'Add an internal note…' : 'Reply…',
                    isDense: true,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(
                onPressed: sending ? null : onSend,
                style: FilledButton.styleFrom(
                    minimumSize: const Size(52, 48),
                    padding: EdgeInsets.zero,
                    backgroundColor: internal ? Brand.goldText : Brand.ink),
                child: sending
                    ? const SizedBox(
                        height: 18,
                        width: 18,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white))
                    : const Icon(Icons.send, size: 18),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Sourcing enquiries submitted through the website's "Request a product" form.
class ProductRequestsScreen extends StatefulWidget {
  const ProductRequestsScreen({super.key});
  @override
  State<ProductRequestsScreen> createState() => _ProductRequestsScreenState();
}

class _ProductRequestsScreenState extends State<ProductRequestsScreen> {
  late Future<List<Map<String, dynamic>>> _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() => setState(() => _future = Api.instance.productRequests());

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Product requests')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _future,
        builder: (context, snap) => AsyncBody(
          snapshot: snap,
          onRetry: _load,
          emptyIcon: Icons.inbox_outlined,
          emptyText: 'No sourcing requests yet.',
          isEmpty: (d) => d.isEmpty,
          builder: (rows) => RefreshIndicator(
            onRefresh: () async => _load(),
            child: ListView.separated(
              padding: const EdgeInsets.all(12),
              itemCount: rows.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (_, i) {
                final r = rows[i];
                return Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('${r['product_name'] ?? r['name'] ?? 'Request'}',
                            style: const TextStyle(
                                fontWeight: FontWeight.w700, fontSize: 14.5)),
                        const SizedBox(height: 6),
                        if ((r['details'] ?? r['message'] ?? '').toString().isNotEmpty)
                          Text('${r['details'] ?? r['message']}',
                              maxLines: 3,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontSize: 13, height: 1.4)),
                        const SizedBox(height: 8),
                        Text(
                          [
                            '${r['contact_name'] ?? ''}',
                            '${r['contact_phone'] ?? r['phone'] ?? ''}',
                            prettyDate(r['created_at'] as String?),
                          ].where((s) => s.isNotEmpty).join('  ·  '),
                          style: const TextStyle(fontSize: 12, color: Brand.muted),
                        ),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
        ),
      ),
    );
  }
}
