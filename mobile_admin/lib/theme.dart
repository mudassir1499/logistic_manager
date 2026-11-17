import 'package:flutter/material.dart';

/// The brand, taken from the website's own tokens so the two do not drift.
///
/// Monochrome with gold reserved for accents — the same rule portal.css
/// follows. Gold has two values because one is not legible everywhere: the
/// bright mark is fine for icons and rules, but gold TEXT on white needs the
/// darker one to clear 4.5:1.
class Brand {
  static const ink = Color(0xFF0A0A0A);
  static const charcoal = Color(0xFF3F3F42);
  static const muted = Color(0xFF6A6A6C);
  static const bg = Color(0xFFF3F4F7);
  static const card = Color(0xFFFFFFFF);
  static const border = Color(0xFFDFE1E6);

  static const gold = Color(0xFFB08421);      // the star mark
  static const goldText = Color(0xFF8A661A);  // gold at body size

  static const ok = Color(0xFF157F4A);
  static const warn = Color(0xFFC2410C);
  static const danger = Color(0xFFB3261E);
  static const info = Color(0xFF44546A);
}

ThemeData buildTheme() {
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: ColorScheme.fromSeed(
      seedColor: Brand.gold,
      primary: Brand.ink,
      surface: Brand.card,
      brightness: Brightness.light,
    ),
    scaffoldBackgroundColor: Brand.bg,
  );

  return base.copyWith(
    appBarTheme: const AppBarTheme(
      backgroundColor: Brand.ink,
      foregroundColor: Colors.white,
      elevation: 0,
      centerTitle: false,
    ),
    cardTheme: CardThemeData(
      color: Brand.card,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: Brand.border),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Brand.card,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: Brand.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: Brand.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: Brand.ink, width: 1.6),
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: Brand.ink,
        foregroundColor: Colors.white,
        // 48dp: a warehouse phone is used one-handed, often in a hurry.
        minimumSize: const Size(0, 48),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: Brand.card,
      indicatorColor: Brand.gold.withValues(alpha: 0.18),
      labelTextStyle: WidgetStateProperty.all(
        const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600),
      ),
    ),
    chipTheme: base.chipTheme.copyWith(
      side: const BorderSide(color: Brand.border),
      backgroundColor: Brand.card,
    ),
    dividerTheme: const DividerThemeData(color: Brand.border, thickness: 1, space: 1),
  );
}

/// One place for the status colours, so a badge means the same thing on every
/// screen. Keyed on the values ShipmentStatus and Order use.
Color statusColour(String? value) {
  switch ((value ?? '').toLowerCase()) {
    case 'delivered':
    case 'paid':
    case 'completed':
    case 'closed':
      return Brand.ok;
    case 'cancelled':
    case 'unpaid':
      return Brand.danger;
    case 'draft':
    case 'preparing':
    case 'open':
      return Brand.warn;
    default:
      return Brand.info;
  }
}
