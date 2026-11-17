import 'package:flutter/material.dart';

import 'api.dart';
import 'theme.dart';

/// Shared pieces, so every screen fails and empties the same way.
///
/// The list screens are all the same shape — fetch, show a spinner, show rows,
/// pull to refresh, say something useful when it breaks — and writing that five
/// times is how five screens end up disagreeing about what an error looks like.

/// A screen's async body: spinner, error with a retry, empty state, or content.
class AsyncBody<T> extends StatelessWidget {
  const AsyncBody({
    super.key,
    required this.snapshot,
    required this.onRetry,
    required this.builder,
    this.emptyIcon = Icons.inbox_outlined,
    this.emptyText = 'Nothing here yet.',
    this.isEmpty,
  });

  final AsyncSnapshot<T> snapshot;
  final VoidCallback onRetry;
  final Widget Function(T data) builder;
  final IconData emptyIcon;
  final String emptyText;
  final bool Function(T data)? isEmpty;

  @override
  Widget build(BuildContext context) {
    if (snapshot.connectionState == ConnectionState.waiting) {
      return const Center(child: CircularProgressIndicator());
    }
    if (snapshot.hasError) {
      final error = snapshot.error;
      return _Message(
        icon: Icons.cloud_off_outlined,
        // ApiException already carries a sentence written for a person; only a
        // genuinely unexpected error falls back to toString().
        title: error is ApiException ? error.message : 'Something went wrong.',
        action: FilledButton(onPressed: onRetry, child: const Text('Try again')),
      );
    }
    final data = snapshot.data;
    if (data == null) return const SizedBox.shrink();
    if (isEmpty?.call(data) ?? false) {
      return _Message(icon: emptyIcon, title: emptyText);
    }
    return builder(data);
  }
}

class _Message extends StatelessWidget {
  const _Message({required this.icon, required this.title, this.action});
  final IconData icon;
  final String title;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 44, color: Brand.muted),
            const SizedBox(height: 14),
            Text(title,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Brand.charcoal, fontSize: 14.5)),
            if (action != null) ...[const SizedBox(height: 18), action!],
          ],
        ),
      ),
    );
  }
}

/// A small status pill. Colour plus the word — never colour alone.
class StatusChip extends StatelessWidget {
  const StatusChip(this.label, {super.key, this.colour});
  final String label;
  final Color? colour;

  @override
  Widget build(BuildContext context) {
    final c = colour ?? statusColour(label);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: c.withValues(alpha: 0.35)),
      ),
      child: Text(
        label,
        style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: c),
      ),
    );
  }
}

/// A label/value row, used on every detail screen.
class DetailRow extends StatelessWidget {
  const DetailRow(this.label, this.value, {super.key, this.valueWidget});
  final String label;
  final String? value;
  final Widget? valueWidget;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 118,
            child: Text(label,
                style: const TextStyle(fontSize: 12.5, color: Brand.muted)),
          ),
          Expanded(
            child: valueWidget ??
                Text(
                  (value ?? '').isEmpty ? '—' : value!,
                  style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                ),
          ),
        ],
      ),
    );
  }
}

/// A titled card. Every section on every detail screen is one of these.
class SectionCard extends StatelessWidget {
  const SectionCard({super.key, this.title, required this.child, this.trailing});
  final String? title;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (title != null) ...[
              Row(
                children: [
                  Expanded(
                    child: Text(title!,
                        style: const TextStyle(
                            fontSize: 15, fontWeight: FontWeight.w700)),
                  ),
                  if (trailing != null) trailing!,
                ],
              ),
              const SizedBox(height: 10),
            ],
            child,
          ],
        ),
      ),
    );
  }
}

/// Show the outcome of a write. Success and failure look different on purpose:
/// a green flash that means "saved" must not be confusable with a red one that
/// means "not saved" when glanced at.
void toast(BuildContext context, String message, {bool error = false}) {
  if (!context.mounted) return;
  ScaffoldMessenger.of(context)
    ..clearSnackBars()
    ..showSnackBar(SnackBar(
      content: Text(message),
      backgroundColor: error ? Brand.danger : Brand.ok,
      behavior: SnackBarBehavior.floating,
      duration: Duration(seconds: error ? 5 : 2),
    ));
}

/// Run a write with a busy state, and report either way.
Future<bool> runWrite(
  BuildContext context,
  Future<void> Function() action, {
  String success = 'Saved',
}) async {
  try {
    await action();
    if (context.mounted) toast(context, success);
    return true;
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message, error: true);
  } catch (_) {
    if (context.mounted) toast(context, 'Could not save.', error: true);
  }
  return false;
}

String money(dynamic value, [String currency = '']) {
  if (value == null) return '—';
  final n = double.tryParse('$value');
  if (n == null) return '$value';
  final s = n.toStringAsFixed(2);
  return currency.isEmpty ? s : '$s $currency';
}

String prettyDate(String? iso) {
  if (iso == null || iso.isEmpty) return '—';
  final d = DateTime.tryParse(iso);
  if (d == null) return iso;
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return '${d.day} ${months[d.month - 1]} ${d.year}';
}
