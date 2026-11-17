# Mudassir LLC — customer app

A Flutter app for the customer side of the platform: browse the catalogue, add
to cart, place an order, track it, and see your ledger balance.

It talks to `/api/v1/` on the Django site. Every rule that matters — pricing,
commission, minimum order quantities, what a customer may see — lives on the
server. The app renders and asks; it never decides.

## Running it

The API address is compiled in, so the same code can point at a local server or
production without editing anything:

```bash
# Against the live site (the default)
flutter run

# Against a local Django dev server, from an Android emulator.
# 10.0.2.2 is how the emulator reaches the host machine — "localhost" inside
# the emulator is the emulator itself.
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000

# From a real phone on the same wifi, use the machine's LAN address:
flutter run --dart-define=API_BASE_URL=http://192.168.1.20:8000
```

An Android emulator or a real device reaching a local server also needs that
address in Django's `DJANGO_ALLOWED_HOSTS`.

## Building

```bash
flutter build apk --release        # Android
flutter build appbundle --release  # Google Play
flutter build ios --release        # iOS (needs a Mac)
flutter build web --release        # Web
```

## What is in it

| Screen | What it does |
|---|---|
| Sign in / register | Exchanges a password for a bearer token, once. The token is stored; the password never is. Also requests a password reset. |
| Catalogue | Search, category filter, infinite scroll. |
| Product | Photos, variants, specifications, quantity, add to cart. |
| Cart | Quantities, removal, server-calculated totals, checkout. |
| Orders | History, status, per-line prices, shipment tracking. |
| Ledger | Per-currency balance and every transaction. |
| Support | Tickets, and raising a new one. |
| Profile | Name, phone and delivery address. |

## How it is put together

```
lib/
  api/client.dart     One HTTP client: base URL, bearer token, error shape.
  api/models.dart     Typed views over the JSON.
  state/app_state.dart Session and cart count, shared by every screen.
  widgets/common.dart  Loading / error / empty states, and the brand palette.
  screens/             One file per area.
```

Three decisions worth knowing, because they are easy to undo by accident:

**Money is never a double.** The API sends prices as strings on purpose, because
JSON numbers are IEEE-754 doubles and `0.1 + 0.2` is not `0.3`. The app keeps
them as strings and only displays them. Nothing here does arithmetic on money —
the cart total and the order total both come from the server, which is the only
place the commission rule exists. The one exception is the ledger balance, which
sums in integer cents rather than parsing to double.

**A stored token is not assumed to be valid.** On launch it is checked against
`/me/`. Trusting it blindly drops a user with a revoked token into the app,
which then fails on the first real request with a confusing error instead of
simply asking them to sign in.

**A 401 anywhere signs the user out.** Handled in one place, so a token revoked
mid-session cannot leave one screen working and the rest failing.

## Tests

```bash
flutter test
```

They cover the JSON parsing every screen depends on and the money handling that
must not drift — including that a price of `0.10` stays `0.10` rather than
becoming `0.1`, and that a missing MOQ never becomes zero (which would let the
quantity stepper start at 0 and have every add rejected by the server).

There are no widget tests that hit the network. Testing screens against a real
server would make the suite depend on a running Django instance and on the state
of its database.
