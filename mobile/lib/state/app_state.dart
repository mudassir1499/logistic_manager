import 'package:flutter/foundation.dart';

import '../api/client.dart';
import '../api/models.dart';

/// Everything the whole app needs to agree on: who is signed in, and what is in
/// the cart.
///
/// A ChangeNotifier held above the navigator rather than a state-management
/// package. The app has exactly two pieces of genuinely shared state, and
/// pulling in a dependency to hold two fields would be more machinery than the
/// problem deserves.
class AppState extends ChangeNotifier {
  AppState(this.api);

  final ApiClient api;

  bool _ready = false;
  bool _signedIn = false;
  Me? _me;
  int _cartCount = 0;

  bool get ready => _ready;
  bool get signedIn => _signedIn;
  Me? get me => _me;
  int get cartCount => _cartCount;

  /// Restore the saved session on launch.
  ///
  /// A stored token is not assumed to be valid — it is checked against /me/.
  /// Trusting it blindly means a revoked or expired token drops the user into
  /// the app, which then fails on the first real request with a confusing error
  /// instead of simply asking them to sign in.
  Future<void> bootstrap() async {
    await api.loadToken();
    if (api.isSignedIn) {
      try {
        await refreshMe();
        _signedIn = true;
        // Deliberately not awaited: the cart badge is not worth delaying the
        // first screen for, and it fills in a moment later.
        unawaited(refreshCartCount());
      } on ApiException catch (error) {
        if (error.isAuthFailure) {
          await api.clearTokenLocally();
        }
        _signedIn = false;
      }
    }
    _ready = true;
    notifyListeners();
  }

  Future<void> refreshMe() async {
    final data = await api.get('/me/') as Map<String, dynamic>;
    _me = Me.fromJson(data);
    notifyListeners();
  }

  Future<void> signIn(String email, String password) async {
    await api.login(email: email, password: password);
    await refreshMe();
    _signedIn = true;
    await refreshCartCount();
    notifyListeners();
  }

  Future<void> registerAccount({
    required String name,
    required String email,
    required String password,
    String phone = '',
    String address = '',
  }) async {
    await api.register(
      name: name, email: email, password: password, phone: phone, address: address);
    await refreshMe();
    _signedIn = true;
    notifyListeners();
  }

  Future<void> signOut() async {
    await api.logout();
    _signedIn = false;
    _me = null;
    _cartCount = 0;
    notifyListeners();
  }

  /// Called when any request comes back 401 mid-session.
  ///
  /// The token was revoked or expired while the app was open, so the session is
  /// dropped and the user lands back on sign-in rather than seeing a wall of
  /// failures on every screen they try.
  Future<void> handleAuthFailure() async {
    await api.clearTokenLocally();
    _signedIn = false;
    _me = null;
    _cartCount = 0;
    notifyListeners();
  }

  Future<void> refreshCartCount() async {
    if (!api.isSignedIn) return;
    try {
      final data = await api.get('/cart/summary/') as Map<String, dynamic>;
      _cartCount = (data['item_count'] as num?)?.toInt() ?? 0;
      notifyListeners();
    } on ApiException {
      // A stale badge is not worth an error dialog.
    }
  }

  void setCartCount(int value) {
    _cartCount = value;
    notifyListeners();
  }
}

/// `unawaited` without importing dart:async just for it.
void unawaited(Future<void> future) {
  future.catchError((Object _) {});
}
