import 'package:flutter/material.dart';

import '../api/client.dart';
import '../state/app_state.dart';

/// Brand colours, taken from the website so the app does not look like a
/// different company.
class Brand {
  static const ink = Color(0xFF0A0A0A);
  static const gold = Color(0xFFB08421);
  static const goldDark = Color(0xFF8A661A);
  static const success = Color(0xFF157F4A);
  static const danger = Color(0xFFB3261E);
  static const muted = Color(0xFF6B6B70);
  static const surface = Color(0xFFF3F4F7);
}

/// The four states any loaded screen can be in.
///
/// Written once because getting this wrong is the most common way a list screen
/// misleads: an empty list and a failed request look identical if both just
/// render nothing, so a user with no orders is told the same thing as a user
/// whose request failed.
class AsyncView<T> extends StatelessWidget {
  const AsyncView({
    super.key,
    required this.state,
    required this.builder,
    required this.onRetry,
    this.emptyMessage = 'Nothing here yet.',
    this.emptyIcon = Icons.inbox_outlined,
    this.isEmpty,
  });

  final AsyncValue<T> state;
  final Widget Function(T value) builder;
  final VoidCallback onRetry;
  final String emptyMessage;
  final IconData emptyIcon;
  final bool Function(T value)? isEmpty;

  @override
  Widget build(BuildContext context) {
    if (state.loading) {
      return const Center(child: Padding(
        padding: EdgeInsets.all(32), child: CircularProgressIndicator()));
    }
    if (state.error != null) {
      return _ErrorState(message: state.error!, onRetry: onRetry);
    }
    final value = state.value;
    if (value == null) return _ErrorState(message: 'No data.', onRetry: onRetry);
    if (isEmpty != null && isEmpty!(value)) {
      return _EmptyState(message: emptyMessage, icon: emptyIcon);
    }
    return builder(value);
  }
}

/// A value that is loading, failed, or arrived.
class AsyncValue<T> {
  const AsyncValue._({this.value, this.error, this.loading = false});

  const AsyncValue.loading() : this._(loading: true);
  const AsyncValue.data(T data) : this._(value: data);
  const AsyncValue.failure(String message) : this._(error: message);

  final T? value;
  final String? error;
  final bool loading;
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off_outlined, size: 44, color: Brand.muted),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center,
                style: const TextStyle(color: Brand.muted)),
            const SizedBox(height: 16),
            FilledButton.tonal(onPressed: onRetry, child: const Text('Try again')),
          ],
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.message, required this.icon});

  final String message;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 44, color: Brand.muted),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center,
                style: const TextStyle(color: Brand.muted)),
          ],
        ),
      ),
    );
  }
}

/// Show an error to the user, and sign them out if the session has gone.
///
/// Centralised so every screen handles a revoked token the same way. Without
/// this, one screen shows "session expired" while the rest keep failing with
/// their own messages.
void showApiError(BuildContext context, Object error, AppState app) {
  final message = error is ApiException ? error.message : 'Something went wrong.';
  if (error is ApiException && error.isAuthFailure) {
    app.handleAuthFailure();
    return;
  }
  if (!context.mounted) return;
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(message), backgroundColor: Brand.danger),
  );
}

void showMessage(BuildContext context, String message) {
  if (!context.mounted) return;
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
}

/// A price with its currency symbol.
class Money extends StatelessWidget {
  const Money(this.amount, {super.key, this.currency = '¥', this.style});

  final String amount;
  final String currency;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) {
    return Text(
      amount.isEmpty ? '—' : '$currency$amount',
      style: style ?? const TextStyle(fontWeight: FontWeight.w800),
    );
  }
}

/// A small coloured status pill.
class StatusChip extends StatelessWidget {
  const StatusChip(this.label, {super.key, this.colour});

  final String label;
  final Color? colour;

  @override
  Widget build(BuildContext context) {
    final c = colour ?? Brand.muted;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: c),
      ),
    );
  }
}

/// Product photo with a placeholder, because a listing without one is common.
class ProductThumb extends StatelessWidget {
  const ProductThumb({super.key, required this.url, this.size = 72});

  final String url;
  final double size;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(10),
      child: SizedBox(
        width: size,
        height: size,
        child: url.isEmpty
            ? Container(color: Brand.surface,
                child: const Icon(Icons.inventory_2_outlined, color: Brand.muted))
            : Image.network(
                url,
                fit: BoxFit.cover,
                // A broken supplier URL must show a placeholder, not a red error
                // box with a stack trace in it.
                errorBuilder: (_, __, ___) => Container(color: Brand.surface,
                    child: const Icon(Icons.image_not_supported_outlined,
                        color: Brand.muted)),
                loadingBuilder: (context, child, progress) => progress == null
                    ? child
                    : Container(color: Brand.surface),
              ),
      ),
    );
  }
}
